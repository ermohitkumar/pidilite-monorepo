"""
/files/stt-complete — Eventarc orchestrator after STT output lands in GCS.

Validates job, records pipeline notes, enqueues translation Cloud Task.
Accepts STT_SUBMITTED to handle Eventarc arriving before checker marks LRO done.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.config import settings
from core.response import make_response
from core.enums import JobStatus
from db.models import ProcessedFile
from db.session import get_db
from repositories import batch_repository
from schemas.schemas import GCSObjectPayload, SttCompleteResponseData
from services.shared.cloud_tasks import enqueue_http_task
from services.shared.pipeline_debug import pipeline_response_data, record_pipeline_note
from services.shared.transcript import (
    extract_bucket_from_selflink,
    extract_job_id_from_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])

# Eventarc can fire before checker moves STT_SUBMITTED → STT_COMPLETED.
# Do NOT include TRANSLATED / TRANSLATING / COMPLETED — duplicate Eventarc must not rewind.
_STT_COMPLETE_ALLOWED = frozenset({
    JobStatus.STT_SUBMITTED,
    JobStatus.STT_COMPLETED,
    JobStatus.ERROR,
})

# Already past STT → translate; never re-enqueue from this endpoint.
_STT_COMPLETE_DOWNSTREAM = frozenset({
    JobStatus.TRANSLATING,
    JobStatus.TRANSLATED,
    JobStatus.PROCESSING,
    JobStatus.NORMALIZED,
    JobStatus.INSIGHTS,
    JobStatus.COMPLETED,
})


@router.post("/stt-complete", summary="STT output received — enqueue translation", status_code=status.HTTP_200_OK)
def stt_complete(
    payload: GCSObjectPayload,
    db: Session = Depends(get_db),
):
    bucket = payload.bucket or extract_bucket_from_selflink(payload.selfLink)
    gcs_uri = f"gs://{bucket}/{payload.name}"

    logger.info("STT complete event: gcs_uri=%s bucket=%s", gcs_uri, bucket)

    job_id = extract_job_id_from_path(payload.name)
    if not job_id:
        logger.warning("stt-complete: could not extract job_id from path=%s", payload.name)
        return make_response(
            success=True,
            message="Could not extract job_id from GCS path, skipping.",
            data=pipeline_response_data(
                job_id="unknown",
                status="SKIPPED",
                action="skipped",
                skip_reason=f"invalid GCS path (expected stt-output/{{job_id}}/output.json): {payload.name}",
            ),
        )

    job = batch_repository.get_job(db, job_id)
    if not job:
        logger.warning("stt-complete: job %s not found for %s", job_id, gcs_uri)
        return make_response(
            success=True,
            message=f"Job {job_id} not found, skipping.",
            data=SttCompleteResponseData(
                job_id=job_id,
                status="NOT_FOUND",
                action="skipped",
                skip_reason="job not in database",
            ).model_dump(),
        )

    previous_status = job.status.value

    if job.status in _STT_COMPLETE_DOWNSTREAM:
        reason = (
            f"status {previous_status} is past STT; duplicate Eventarc ignored "
            "(will not rewind or re-enqueue translate)"
        )
        logger.info("stt-complete: job %s %s", job_id, reason)
        return make_response(
            success=True,
            message=reason,
            data=SttCompleteResponseData(
                job_id=job_id,
                status=previous_status,
                action="skipped",
                previous_status=previous_status,
                skip_reason=reason,
            ).model_dump(),
        )

    if job.status not in _STT_COMPLETE_ALLOWED:
        reason = (
            f"status {previous_status} not eligible for stt-complete "
            f"(allowed: {', '.join(s.value for s in sorted(_STT_COMPLETE_ALLOWED, key=lambda x: x.value))})"
        )
        logger.warning("stt-complete: job %s skipped — %s", job_id, reason)
        record_pipeline_note(db, job_id, "stt-complete", reason, level="warning")
        return make_response(
            success=True,
            message=f"Job {job_id} skipped: {reason}",
            data=SttCompleteResponseData(
                job_id=job_id,
                status=previous_status,
                action="skipped",
                previous_status=previous_status,
                skip_reason=reason,
            ).model_dump(),
        )

    # ERROR after a successful translation must not re-enter translate via Eventarc.
    if job.status == JobStatus.ERROR:
        processed = (
            db.query(ProcessedFile)
            .filter(ProcessedFile.job_id == job_id)
            .first()
        )
        if processed and processed.translated_text:
            reason = (
                "ERROR but translation already saved; duplicate Eventarc ignored "
                "(checker will retry post-processing if needed)"
            )
            logger.info("stt-complete: job %s %s", job_id, reason)
            return make_response(
                success=True,
                message=reason,
                data=SttCompleteResponseData(
                    job_id=job_id,
                    status=previous_status,
                    action="skipped",
                    previous_status=previous_status,
                    skip_reason=reason,
                ).model_dump(),
            )

    if job.status == JobStatus.STT_SUBMITTED:
        logger.warning(
            "stt-complete: job %s still STT_SUBMITTED (Eventarc beat checker LRO poll); proceeding",
            job_id,
        )

    try:
        batch_repository.update_job_status(
            db, job_id,
            status=JobStatus.TRANSLATING,
            gcs_stt_output_uri=gcs_uri,
            error_message=None,
        )
        task_name = enqueue_http_task(
            url=settings.CLOUD_TASKS_TRANSLATE_URL,
            payload={"job_id": job_id, "gcs_transcript_uri": gcs_uri},
        )
        if task_name is None:
            msg = (
                "Translation Cloud Task was NOT created (SDK unavailable or misconfigured). "
                f"translate_url={settings.CLOUD_TASKS_TRANSLATE_URL!r} queue={settings.CLOUD_TASKS_QUEUE!r}"
            )
            logger.error("stt-complete: job %s — %s", job_id, msg)
            batch_repository.update_job_status(
                db, job_id,
                status=JobStatus.ERROR,
                error_message=f"[pipeline:stt-complete] {msg}",
                increment_retry=True,
            )
            return make_response(
                success=False,
                message=msg,
                data=SttCompleteResponseData(
                    job_id=job_id,
                    status=JobStatus.ERROR.value,
                    action="enqueue_failed",
                    previous_status=previous_status,
                    skip_reason=msg,
                ).model_dump(),
                error=msg,
            )

        note = f"translation task enqueued from Eventarc (previous_status={previous_status})"
        record_pipeline_note(db, job_id, "stt-complete", note)
        logger.info(
            "stt-complete: job %s TRANSLATING, task=%s, gcs_uri=%s",
            job_id, task_name, gcs_uri,
        )
        return make_response(
            success=True,
            message="Translation task enqueued",
            data=SttCompleteResponseData(
                job_id=job_id,
                status=JobStatus.TRANSLATING.value,
                action="enqueued_translate",
                previous_status=previous_status,
                cloud_task_name=task_name,
                gcs_stt_output_uri=gcs_uri,
            ).model_dump(),
        )
    except Exception as exc:
        logger.exception("stt-complete: failed to enqueue translation for job %s", job_id)
        batch_repository.update_job_status(
            db, job_id,
            status=JobStatus.ERROR,
            error_message=f"[pipeline:stt-complete] Translation enqueue failed: {exc}",
            increment_retry=True,
        )
        return make_response(
            success=False,
            message="Failed to enqueue translation task",
            data=SttCompleteResponseData(
                job_id=job_id,
                status=JobStatus.ERROR.value,
                action="enqueue_failed",
                previous_status=previous_status,
                skip_reason=str(exc),
            ).model_dump(),
            error=str(exc),
        )
