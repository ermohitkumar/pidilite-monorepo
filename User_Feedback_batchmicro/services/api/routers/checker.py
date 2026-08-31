"""
/checker/run — Checker & Recovery endpoint.

Periodically checks for stuck or failed jobs in the processing pipeline.
Decides whether to retry or mark as failed. Helps maintain system
reliability through automated recovery.

Re-enqueue paths are age-gated (STUCK_JOB_RECOVERY_MINUTES) and touch
updated_at after a successful enqueue so frequent scheduler ticks cannot
tight-loop Cloud Task creation.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.config import settings
from core.response import make_response
from db.session import get_db
from repositories import batch_repository
from db.models import Batch, Job, ProcessedFile, Feedback
from core.enums import JobStatus, BatchStatus
from schemas.schemas import CheckerRunRequest, CheckerRunResponseData
from services.shared.cloud_tasks import enqueue_http_task
from services.shared.gcs_paths import build_stt_output_gcs_uri
from services.shared.gemini_stt import is_gemini_flash_operation
from services.shared.pipeline_debug import record_pipeline_note
from services.shared.stt_client import (
    _HAS_SPEECH,
    file_error_from_operation,
    get_operation,
    output_uri_from_operation,
    submit_batch_recognize,
)
from services.shared.transcript import gcs_blob_exists

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/checker", tags=["Checker & Recovery"])


def _as_utc_datetime(ts) -> datetime | None:
    """Job timestamps are DateTime in Postgres; some drivers/rows arrive as str."""
    if ts is None:
        return None
    if isinstance(ts, str):
        raw = ts.strip().replace("Z", "+00:00")
        try:
            ts = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _job_is_stuck(job: Job) -> bool:
    """
    True if the job has been idle long enough to warrant a recovery enqueue.

    STUCK_JOB_RECOVERY_MINUTES <= 0 disables the gate (always stuck).
    After a successful recovery enqueue we touch updated_at so the next
    checker tick will skip until the window elapses again.
    """
    minutes = settings.STUCK_JOB_RECOVERY_MINUTES
    if minutes <= 0:
        return True
    ts = _as_utc_datetime(job.updated_at or job.created_at)
    if ts is None:
        return True
    return datetime.now(timezone.utc) - ts >= timedelta(minutes=minutes)


def _mark_recovery_enqueued(db: Session, job_id: str, step: str, message: str) -> None:
    """Record note + bump updated_at so we do not re-enqueue on the next tick."""
    record_pipeline_note(db, job_id, step, message)
    batch_repository.touch_job(db, job_id)


# ── Poll outstanding STT LROs ────────────────────────────────────────────────

def _poll_gemini_flash_job(db: Session, job: Job) -> str:
    """
    Handle STT_SUBMITTED jobs whose operation name is the gemini-flash sentinel.

    Never calls Speech get_operation. If the canonical GCS blob exists, mark
    STT_COMPLETED. If the job is stuck with no blob, submit Speech v2.
    Returns completed | fallback | wait | errored.
    """
    gcs_uri = job.gcs_stt_output_uri or build_stt_output_gcs_uri(job.id)
    try:
        exists = gcs_blob_exists(gcs_uri)
    except Exception as exc:
        logger.warning("Failed to check Gemini Flash STT blob for job %s: %s", job.id, exc)
        exists = False

    if exists:
        logger.info("Gemini Flash STT blob present for job %s, marking STT_COMPLETED", job.id)
        batch_repository.update_job_status(
            db, job.id,
            status=JobStatus.STT_COMPLETED,
            gcs_stt_output_uri=gcs_uri,
        )
        return "completed"

    if not _job_is_stuck(job):
        return "wait"

    prefix = f"gs://{settings.GCS_OUTPUT_BUCKET}/stt-output/{job.id}/"
    try:
        operation_name = submit_batch_recognize(
            job.gcs_input_uri,
            prefix,
            language_code="hi-IN",
            model="telephony",
        )
    except Exception as exc:
        logger.warning("Gemini Flash stuck fallback to Speech v2 failed for job %s: %s", job.id, exc)
        return "errored"

    logger.warning(
        "Gemini Flash STT stuck with no GCS blob for job %s; submitted Speech v2 op=%s",
        job.id, operation_name,
    )
    batch_repository.update_job_status(
        db, job.id,
        status=JobStatus.STT_SUBMITTED,
        stt_operation_name=operation_name,
        error_message="Gemini Flash STT produced no GCS output; fell back to Speech v2",
    )
    _mark_recovery_enqueued(
        db, job.id, "checker",
        f"gemini-flash stuck: submitted Speech v2 LRO ({operation_name})",
    )
    return "fallback"


def _poll_stt_lros(db: Session, limit: int) -> dict:
    """
    For every job in STT_SUBMITTED status that has an stt_operation_name,
    check if STT has completed (Speech LRO or Gemini Flash GCS blob).
    """
    submitted_jobs = batch_repository.get_jobs_by_status(db, JobStatus.STT_SUBMITTED, limit=limit)
    completed, errored = 0, 0

    if not submitted_jobs:
        return {"polled": 0, "completed": 0, "errored": 0}

    for job in submitted_jobs:
        if not job.stt_operation_name:
            continue
        if is_gemini_flash_operation(job.stt_operation_name):
            result = _poll_gemini_flash_job(db, job)
            if result == "completed":
                completed += 1
            elif result == "errored":
                errored += 1
            continue
        if not _HAS_SPEECH:
            continue
        try:
            op = get_operation(job.stt_operation_name)
            if op.done:
                file_err = file_error_from_operation(op)
                top_err = getattr(op.error, "code", 0) if getattr(op, "error", None) else 0
                if top_err or file_err:
                    message = (
                        (op.error.message if top_err else None)
                        or file_err
                        or "STT LRO failed"
                    )
                    logger.warning("STT LRO error for job %s: %s", job.id, message)
                    batch_repository.update_job_status(
                        db, job.id,
                        status=JobStatus.ERROR,
                        error_message=f"STT LRO error: {message}",
                        increment_retry=True,
                    )
                    errored += 1
                    continue
                gcs_uri = output_uri_from_operation(op)
                if not gcs_uri:
                    logger.info(
                        "STT LRO done for job %s but no GCS transcript yet; will poll again",
                        job.id,
                    )
                    continue
                logger.info("STT LRO completed for job %s, gcs_stt_output_uri=%s", job.id, gcs_uri)
                batch_repository.update_job_status(
                    db, job.id,
                    status=JobStatus.STT_COMPLETED,
                    gcs_stt_output_uri=gcs_uri,
                )
                completed += 1
        except Exception as exc:
            # Could not poll — leave job as-is, retry next cycle
            logger.warning("Failed to poll STT LRO for job %s: %s", job.id, exc)

    logger.info("STT LRO poll complete: polled=%d, completed=%d, errored=%d",
                len(submitted_jobs), completed, errored)
    return {"polled": len(submitted_jobs), "completed": completed, "errored": errored}


# ── Kick STT_COMPLETED jobs that missed Eventarc ─────────────────────────────

def _kick_stt_completed_jobs(db: Session, limit: int) -> tuple[int, int]:
    """
    Enqueue translation for jobs stuck in STT_COMPLETED.

    Status transition STT_COMPLETED → TRANSLATING is the anti-loop for this path
    (no age gate). Age gate applies once the job is in TRANSLATING.
    """
    jobs = batch_repository.get_jobs_by_status(db, JobStatus.STT_COMPLETED, limit=limit)
    kicked = 0
    skipped_no_uri = 0
    for job in jobs:
        gcs_uri = job.gcs_stt_output_uri or build_stt_output_gcs_uri(job.id)
        if not job.gcs_stt_output_uri:
            logger.info(
                "checker: job %s STT_COMPLETED without gcs_stt_output_uri; inferred %s",
                job.id, gcs_uri,
            )
            batch_repository.update_job_status(
                db, job.id,
                status=job.status,
                gcs_stt_output_uri=gcs_uri,
            )
        try:
            batch_repository.update_job_status(db, job.id, status=JobStatus.TRANSLATING)
            task_name = enqueue_http_task(
                url=settings.CLOUD_TASKS_TRANSLATE_URL,
                payload={"job_id": job.id, "gcs_transcript_uri": gcs_uri},
            )
            if task_name is None:
                skipped_no_uri += 1
                msg = "Cloud Task not created (SDK/queue config); job left in TRANSLATING"
                record_pipeline_note(db, job.id, "checker", msg, level="warning")
                batch_repository.update_job_status(
                    db, job.id,
                    status=JobStatus.ERROR,
                    error_message=f"[pipeline:checker] {msg}",
                    increment_retry=True,
                )
                continue
            _mark_recovery_enqueued(
                db, job.id, "checker",
                f"translation kicked from STT_COMPLETED (task={task_name})",
            )
            kicked += 1
        except Exception as exc:
            logger.warning("Failed to kick translation for job %s: %s", job.id, exc)
            record_pipeline_note(
                db, job.id, "checker",
                f"translation kick failed: {exc}",
                level="warning",
            )
    return kicked, skipped_no_uri


def _recover_stuck_batched_jobs(db: Session, limit: int) -> int:
    """
    Re-enqueue STT for BATCHED jobs that never received stt_operation_name
    (crash between batch commit and Cloud Task create).
    """
    jobs = batch_repository.get_jobs_by_status(db, JobStatus.BATCHED, limit=limit)
    recovered = 0
    for job in jobs:
        if job.stt_operation_name:
            continue
        if not _job_is_stuck(job):
            continue
        gcs_output_prefix = f"gs://{settings.GCS_OUTPUT_BUCKET}/stt-output/{job.id}/"
        try:
            task_name = enqueue_http_task(
                url=settings.CLOUD_TASKS_CALLBACK_URL,
                payload={
                    "job_id": job.id,
                    "gcs_input_uri": job.gcs_input_uri,
                    "gcs_output_uri_prefix": gcs_output_prefix,
                },
            )
            if task_name is None:
                record_pipeline_note(
                    db, job.id, "checker",
                    "stuck BATCHED: could not create STT Cloud Task",
                    level="warning",
                )
                continue
            _mark_recovery_enqueued(
                db, job.id, "checker",
                f"stuck BATCHED: re-enqueued transcription (task={task_name})",
            )
            recovered += 1
        except Exception as exc:
            logger.warning("Failed to recover stuck BATCHED job %s: %s", job.id, exc)
    return recovered


def _recover_stuck_translated_jobs(db: Session, limit: int) -> int:
    """
    Re-enqueue post-processing for TRANSLATED jobs with no Feedback rows
    (crash after translate commit / before post-process task).
    """
    jobs = batch_repository.get_jobs_by_status(db, JobStatus.TRANSLATED, limit=limit)
    recovered = 0
    for job in jobs:
        if not _job_is_stuck(job):
            continue
        has_feedback = (
            db.query(Feedback)
            .filter(Feedback.job_id == job.id)
            .first()
        )
        if has_feedback:
            # Data present but status lagging — complete without re-enqueue.
            batch_repository.update_job_status(db, job.id, status=JobStatus.COMPLETED)
            continue
        processed = (
            db.query(ProcessedFile)
            .filter(ProcessedFile.job_id == job.id)
            .first()
        )
        if not processed or not processed.translated_text:
            continue
        try:
            task_name = enqueue_http_task(
                url=settings.CLOUD_TASKS_POSTPROCESS_URL,
                payload={"job_id": job.id},
            )
            if task_name is None:
                record_pipeline_note(
                    db, job.id, "checker",
                    "stuck TRANSLATED: could not create post-processing Cloud Task",
                    level="warning",
                )
                continue
            _mark_recovery_enqueued(
                db, job.id, "checker",
                f"stuck TRANSLATED: re-enqueued post-processing (task={task_name})",
            )
            recovered += 1
        except Exception as exc:
            logger.warning("Failed to recover stuck TRANSLATED job %s: %s", job.id, exc)
    return recovered


def _recover_stuck_post_processing_jobs(db: Session, limit: int) -> int:
    """Re-enqueue post-processing for jobs stuck after translate."""
    stuck_statuses = (JobStatus.PROCESSING, JobStatus.NORMALIZED, JobStatus.INSIGHTS)
    recovered = 0
    for stuck_status in stuck_statuses:
        jobs = batch_repository.get_jobs_by_status(db, stuck_status, limit=limit)
        for job in jobs:
            if not _job_is_stuck(job):
                continue
            has_feedback = (
                db.query(Feedback)
                .filter(Feedback.job_id == job.id)
                .first()
            )
            if has_feedback:
                continue
            processed = (
                db.query(ProcessedFile)
                .filter(ProcessedFile.job_id == job.id)
                .first()
            )
            if not processed or not processed.translated_text:
                continue
            try:
                task_name = enqueue_http_task(
                    url=settings.CLOUD_TASKS_POSTPROCESS_URL,
                    payload={"job_id": job.id},
                )
                if task_name is None:
                    continue
                _mark_recovery_enqueued(
                    db, job.id, "checker",
                    f"stuck {stuck_status.value}: re-enqueued post-processing (task={task_name})",
                )
                recovered += 1
            except Exception as exc:
                logger.warning(
                    "Failed to recover stuck post-processing job %s: %s", job.id, exc,
                )
    return recovered


def _recover_stuck_translating_jobs(db: Session, limit: int) -> int:
    """
    Jobs in TRANSLATING with no translated_text — translate task never ran or failed.
    Re-enqueue translate when gcs_stt_output_uri (or inferred path) is available.
    """
    jobs = batch_repository.get_jobs_by_status(db, JobStatus.TRANSLATING, limit=limit)
    recovered = 0
    for job in jobs:
        if not _job_is_stuck(job):
            continue
        processed = (
            db.query(ProcessedFile)
            .filter(ProcessedFile.job_id == job.id)
            .first()
        )
        if processed and processed.translated_text:
            continue
        gcs_uri = job.gcs_stt_output_uri or build_stt_output_gcs_uri(job.id)
        if not job.gcs_stt_output_uri:
            batch_repository.update_job_status(
                db, job.id,
                status=job.status,
                gcs_stt_output_uri=gcs_uri,
            )
        try:
            task_name = enqueue_http_task(
                url=settings.CLOUD_TASKS_TRANSLATE_URL,
                payload={"job_id": job.id, "gcs_transcript_uri": gcs_uri},
            )
            if task_name is None:
                record_pipeline_note(
                    db, job.id, "checker",
                    "stuck TRANSLATING: could not create Cloud Task",
                    level="warning",
                )
                continue
            _mark_recovery_enqueued(
                db, job.id, "checker",
                f"stuck TRANSLATING: re-enqueued translate (task={task_name})",
            )
            recovered += 1
        except Exception as exc:
            logger.warning("Failed to recover stuck TRANSLATING job %s: %s", job.id, exc)
    return recovered


# ── Retry ERROR jobs ─────────────────────────────────────────────────────────

def _retry_error_jobs(db: Session, limit: int) -> dict:
    """
    Re-enqueue ERROR jobs that haven't exceeded MAX_RETRY_COUNT.
    Post-STT errors re-enqueue translate or post-processing; pre-STT reset to PENDING.
    Status transitions away from ERROR prevent tight re-enqueue loops.
    """
    error_jobs = batch_repository.get_jobs_by_status(db, JobStatus.ERROR, limit=limit)
    retried, failed = 0, 0
    max_retries = settings.MAX_RETRY_COUNT

    for job in error_jobs:
        if (job.retry_count or 0) >= max_retries:
            logger.warning("Job %s exceeded max retries (%d) — marking FAILED",
                           job.id, max_retries)
            batch_repository.update_job_status(db, job.id, status=JobStatus.FAILED)
            failed += 1
            continue

        if not _job_is_stuck(job):
            continue

        processed = (
            db.query(ProcessedFile)
            .filter(ProcessedFile.job_id == job.id)
            .first()
        )
        has_feedback = (
            db.query(Feedback)
            .filter(Feedback.job_id == job.id)
            .first()
        )
        gcs_uri = job.gcs_stt_output_uri or (processed.gcs_transcript_uri if processed else None)

        try:
            if gcs_uri and (not processed or not processed.translated_text):
                logger.info("Retrying translation for job %s", job.id)
                batch_repository.update_job_status(db, job.id, status=JobStatus.TRANSLATING)
                task_name = enqueue_http_task(
                    url=settings.CLOUD_TASKS_TRANSLATE_URL,
                    payload={"job_id": job.id, "gcs_transcript_uri": gcs_uri},
                )
                if task_name is None:
                    batch_repository.update_job_status(
                        db, job.id,
                        status=JobStatus.ERROR,
                        error_message="[pipeline:checker] translate Cloud Task not created",
                        increment_retry=True,
                    )
                    continue
                _mark_recovery_enqueued(
                    db, job.id, "checker",
                    f"ERROR retry: enqueued translate (task={task_name})",
                )
                retried += 1
            elif processed and processed.translated_text and not has_feedback:
                logger.info("Retrying post-processing for job %s", job.id)
                batch_repository.update_job_status(db, job.id, status=JobStatus.PROCESSING)
                task_name = enqueue_http_task(
                    url=settings.CLOUD_TASKS_POSTPROCESS_URL,
                    payload={"job_id": job.id},
                )
                if task_name is None:
                    batch_repository.update_job_status(
                        db, job.id,
                        status=JobStatus.ERROR,
                        error_message="[pipeline:checker] post-process Cloud Task not created",
                        increment_retry=True,
                    )
                    continue
                _mark_recovery_enqueued(
                    db, job.id, "checker",
                    f"ERROR retry: enqueued post-processing (task={task_name})",
                )
                retried += 1
            else:
                logger.info("Retrying job %s from PENDING (pre-STT)", job.id)
                batch_repository.update_job_status(db, job.id, status=JobStatus.PENDING)
                retried += 1
        except Exception as exc:
            logger.warning("Failed to retry job %s: %s", job.id, exc)

    return {"retried": retried, "failed": failed}


# ── Update batch statuses ────────────────────────────────────────────────────

def _reconcile_batches(db: Session) -> int:
    """
    For each PROCESSING batch, check the state of its jobs and
    mark the batch as COMPLETED / PARTIAL_SUCCESS / FAILED accordingly.
    """
    running_batches = (
        db.query(Batch).filter(Batch.status == BatchStatus.PROCESSING).all()
    )
    updated = 0
    for batch in running_batches:
        if batch_repository.evaluate_batch_status(db, batch.id):
            updated += 1
    return updated


# ── POST /checker/run ─────────────────────────────────────────────────────────

@router.post("/run", status_code=status.HTTP_200_OK)
def run_checker(
    payload: CheckerRunRequest = CheckerRunRequest(),
    db: Session = Depends(get_db),
):
    """
    Periodically checks for stuck or failed jobs. Polls STT LROs,
    retries recoverable errors, marks exhausted jobs as FAILED, and
    reconciles batch statuses.
    """
    limit = payload.max_jobs_to_check
    logger.info("Checker run started (max_jobs_to_check=%d)", limit)

    try:
        # 1. Poll outstanding STT LROs
        lro_result = _poll_stt_lros(db, limit)

        # 2. Kick STT_COMPLETED jobs waiting for translation (one-shot status move)
        stt_kicked, kick_skipped = _kick_stt_completed_jobs(db, limit)

        # 3. Recover BATCHED jobs that never got an STT task
        stuck_batched = _recover_stuck_batched_jobs(db, limit)

        # 4. Re-enqueue translate for TRANSLATING jobs with no translated_text
        stuck_translating = _recover_stuck_translating_jobs(db, limit)

        # 5. Recover TRANSLATED jobs that never got post-processing
        stuck_translated = _recover_stuck_translated_jobs(db, limit)

        # 6. Re-enqueue post-processing for PROCESSING / NORMALIZED / INSIGHTS
        stuck_post_processing = _recover_stuck_post_processing_jobs(db, limit)

        # 7. Retry / fail ERROR jobs
        retry_result = _retry_error_jobs(db, limit)

        # 8. Reconcile batch statuses
        batches_reconciled = _reconcile_batches(db)

        # 9. Count jobs still in-flight
        still_pending = len(
            batch_repository.get_jobs_by_statuses(
                db,
                [
                    JobStatus.PENDING,
                    JobStatus.BATCHED,
                    JobStatus.STT_SUBMITTED,
                    JobStatus.STT_COMPLETED,
                    JobStatus.TRANSLATING,
                    JobStatus.TRANSLATED,
                    JobStatus.PROCESSING,
                    JobStatus.NORMALIZED,
                    JobStatus.INSIGHTS,
                ],
                limit=9999,
            )
        )

        total_checked = (
            lro_result["polled"]
            + stt_kicked
            + stuck_batched
            + stuck_translating
            + stuck_translated
            + stuck_post_processing
            + retry_result["retried"]
            + retry_result["failed"]
        )

        logger.info(
            "Checker run complete: checked=%d, stt_lro_completed=%d, translate_kicked=%d, "
            "stuck_batched=%d, stuck_translating=%d, stuck_translated=%d, "
            "stuck_post_processing=%d, recovered=%d, failed=%d, still_pending=%d, "
            "batches_reconciled=%d",
            total_checked, lro_result["completed"], stt_kicked, stuck_batched,
            stuck_translating, stuck_translated, stuck_post_processing,
            retry_result["retried"], retry_result["failed"], still_pending,
            batches_reconciled,
        )

        return make_response(
            success=True,
            message="Checker service completed successfully",
            data=CheckerRunResponseData(
                jobs_checked=total_checked,
                jobs_recovered=(
                    retry_result["retried"]
                    + stt_kicked
                    + stuck_batched
                    + stuck_translating
                    + stuck_translated
                    + stuck_post_processing
                ),
                jobs_marked_failed=retry_result["failed"],
                jobs_still_pending=still_pending,
                stt_lro_polled=lro_result["polled"],
                stt_lro_completed=lro_result["completed"],
                stt_lro_errored=lro_result["errored"],
                translate_kicked=stt_kicked,
                translate_kick_skipped_no_uri=kick_skipped,
                stuck_batched_recovered=stuck_batched,
                stuck_translating_recovered=stuck_translating,
                stuck_translated_recovered=stuck_translated,
                stuck_post_processing_recovered=stuck_post_processing,
                batches_reconciled=batches_reconciled,
            ).model_dump(),
        )

    except Exception as exc:
        logger.error("Checker service failed: %s", exc, exc_info=True)
        return make_response(
            success=False,
            message="Checker service failed",
            error=str(exc),
        )
