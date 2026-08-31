"""
/batch — Batch orchestration endpoint.

Triggers the batch orchestrator to scan PENDING jobs and group them into
batches, enqueuing Cloud Tasks for each job in the batch.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.config import settings
from core.response import make_response, make_error_response
from db.session import get_db
from repositories import batch_repository
from db.models import Batch
from core.enums import JobStatus, BatchStatus
from schemas.schemas import BatchStartResponseData
from services.shared.cloud_tasks import enqueue_http_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/batch", tags=["Batch Orchestrator"])


def _enqueue_stt_task(job_id: str, gcs_input_uri: str) -> str | None:
    """Enqueue Cloud Task for STT submission. Returns task name or None."""
    gcs_output_prefix = f"gs://{settings.GCS_OUTPUT_BUCKET}/stt-output/{job_id}/"
    return enqueue_http_task(
        url=settings.CLOUD_TASKS_CALLBACK_URL,
        payload={
            "job_id": job_id,
            "gcs_input_uri": gcs_input_uri,
            "gcs_output_uri_prefix": gcs_output_prefix,
            # Field visits are typically Hindi/Hinglish; en-IN hurts ASR.
            "language_code": "hi-IN",
            "model": "telephony",
        },
    )


def _evaluate_batch_status(db: Session, batch_id: str) -> None:
    """Scatter-gather: close the batch once every child job is terminal."""
    batch_repository.evaluate_batch_status(db, batch_id)


def _flush_pending_jobs(db: Session) -> tuple[list[Batch], int]:
    """
    Core orchestration logic:
      1. Atomically claim PENDING jobs (FOR UPDATE SKIP LOCKED on Postgres).
      2. Read batch_size from app_config (fallback to settings).
      3. Chunk into batches, persist each batch, enqueue Cloud Tasks.

    Returns (created_batches, total_jobs_enqueued).
    """
    batch_size = int(
        batch_repository.get_config_value(db, "batch_size", settings.BATCH_SIZE)
    )
    created_batches: list[Batch] = []
    total_enqueued = 0

    while True:
        # Claim one chunk at a time so concurrent /batch callers don't overlap.
        chunk = batch_repository.claim_pending_jobs(db, batch_size)
        if not chunk:
            break

        logger.info("Claimed %d pending jobs, batch_size=%d", len(chunk), batch_size)

        batch = Batch(
            batch_number=batch_repository.get_next_batch_number(db),
            batch_size=len(chunk),
            status=BatchStatus.PROCESSING,
        )
        db.add(batch)
        db.flush()  # batch.id before assigning jobs

        for job in chunk:
            job.batch_id = batch.id
            job.status = JobStatus.BATCHED

        db.commit()
        db.refresh(batch)

        for job in chunk:
            try:
                task_name = _enqueue_stt_task(job.id, job.gcs_input_uri)
                if task_name is None:
                    raise ValueError(
                        "Cloud Task not created (SDK unavailable or misconfigured)"
                    )
                total_enqueued += 1
            except Exception as exc:
                logger.error(
                    "Cloud Tasks enqueue failed for job %s in batch %s: %s",
                    job.id, batch.id, exc, exc_info=True,
                )
                job.status = JobStatus.ERROR
                job.error_message = f"Cloud Tasks enqueue failed: {exc}"
                db.commit()

        _evaluate_batch_status(db, batch.id)
        created_batches.append(batch)

    if not created_batches:
        logger.info("No pending jobs found — skipping batch orchestration")

    logger.info(
        "Batch orchestration complete: %d batches created, %d jobs enqueued",
        len(created_batches), total_enqueued,
    )
    return created_batches, total_enqueued


@router.post("", summary="Initialize a new processing batch", status_code=status.HTTP_200_OK)
def batch_start(db: Session = Depends(get_db)):
    """
    Triggers the Batch Orchestrator to scan pending jobs and group them
    into batches. Returns the batch ID and number of jobs enqueued.

    **Auth:** This endpoint is invoked by Cloud Scheduler (internal), not by Cloud
    Tasks. The service does not implement OIDC in application code — Cloud Run IAM
    requires the Scheduler job to send an OIDC token (see scripts/configure-scheduler-oidc.sh).
    """
    try:
        batches, total_enqueued = _flush_pending_jobs(db)
    except Exception as exc:
        logger.error("Batch orchestration failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error_response(
                message="Batch orchestration failed",
                error=str(exc),
            ).model_dump(),
        )

    if not batches:
        return make_response(
            success=True,
            message="No pending jobs to batch",
            data=BatchStartResponseData(
                batch_id="",
                jobs_enqueued=0,
            ).model_dump(),
        )

    # Return the last batch created (most recent) per the API design doc
    last_batch = batches[-1]
    return make_response(
        success=True,
        message="Batch orchestration completed successfully",
        data=BatchStartResponseData(
            batch_id=last_batch.id,
            jobs_enqueued=total_enqueued,
        ).model_dump(),
    )
