"""
/files/gemini-stt — Gemini Flash STT worker.

Called by Cloud Tasks on pidilite-gemini-stt-queue. Transcribes gs:// audio
via Vertex generateContent, writes the canonical STT JSON, and returns 200.
Transient failures return 503 so Tasks retries (max 3). On the last attempt,
falls back to Speech v2 BatchRecognize and returns 200.
"""
import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import JobStatus
from core.exceptions import STTError, STTGeminiTransientError
from core.response import make_response
from db.models import FailedJob
from db.session import get_db
from repositories import batch_repository
from schemas.schemas import GeminiSTTRequest, GeminiSTTResponseData
from services.api.routers.stt import _submit_to_stt
from services.shared.gemini_stt import (
    gemini_stt_output_uri,
    is_gemini_flash_operation,
    is_last_flash_attempt,
    transcribe_audio_gcs,
    write_gemini_transcript_json,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])

_GEMINI_STT_ALLOWED = frozenset({
    JobStatus.PENDING,
    JobStatus.BATCHED,
    JobStatus.STT_SUBMITTED,
    JobStatus.ERROR,
})

_GEMINI_STT_DONE = frozenset({
    JobStatus.STT_COMPLETED,
    JobStatus.TRANSLATING,
    JobStatus.TRANSLATED,
    JobStatus.PROCESSING,
    JobStatus.NORMALIZED,
    JobStatus.INSIGHTS,
    JobStatus.COMPLETED,
    JobStatus.FAILED,
})


def _retry_count_from_request(request: Request) -> int:
    raw = request.headers.get("X-CloudTasks-TaskRetryCount") or "0"
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _ok(job_id: str, job_status: str, message: str, **extra) -> dict:
    return make_response(
        success=True,
        message=message,
        data=GeminiSTTResponseData(
            job_id=job_id,
            status=job_status,
            **extra,
        ).model_dump(),
    )


_FALLBACK_MESSAGE = "Gemini Flash STT failed after 3 attempts; Speech v2 LRO submitted"


def _retry_later(job_id: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "success": False,
            "message": message,
            "data": {"job_id": job_id, "status": JobStatus.STT_SUBMITTED.value},
        },
    )


def _fallback_to_speech_v2(db: Session, job, payload: GeminiSTTRequest) -> str:
    prefix = (payload.gcs_output_uri_prefix or "").rstrip("/") + "/"
    if prefix == "/":
        prefix = f"gs://{settings.GCS_OUTPUT_BUCKET}/stt-output/{job.id}/"
    source_hint = job.file_details.file_extension if job.file_details else None
    operation_name = _submit_to_stt(
        payload.gcs_input_uri,
        gcs_output_uri_prefix=prefix,
        language_code=payload.language_code or "hi-IN",
        model=payload.model or "telephony",
        source_hint=source_hint,
    )
    batch_repository.update_job_status(
        db, job.id,
        status=JobStatus.STT_SUBMITTED,
        stt_operation_name=operation_name,
        error_message="Gemini Flash STT exhausted retries; fell back to Speech v2",
    )
    logger.warning(
        "Gemini Flash STT fallback to Speech v2 for job %s op=%s",
        job.id, operation_name,
    )
    return operation_name


def _fallback_or_fail(db: Session, job, payload: GeminiSTTRequest):
    try:
        operation_name = _fallback_to_speech_v2(db, job, payload)
        return _ok(
            job.id, JobStatus.STT_SUBMITTED.value,
            _FALLBACK_MESSAGE,
            stt_operation_name=operation_name,
            fallback="speech_v2",
        )
    except STTError as fallback_exc:
        return _fail_stt(db, job, fallback_exc)


@router.post("/gemini-stt", summary="Gemini Flash STT worker", status_code=status.HTTP_200_OK)
def gemini_stt(
    payload: GeminiSTTRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    retry_count = _retry_count_from_request(request)
    last_attempt = is_last_flash_attempt(retry_count)

    job = batch_repository.get_job(db, payload.job_id)
    if not job:
        return _ok(payload.job_id, "NOT_FOUND", f"Job {payload.job_id} not found, skipping.")

    if job.status in _GEMINI_STT_DONE:
        return _ok(
            job.id, job.status.value,
            f"Job {job.id} is in status {job.status.value}, skipping.",
        )

    if job.status not in _GEMINI_STT_ALLOWED:
        return _ok(
            job.id, job.status.value,
            f"Job {job.id} is in status {job.status.value}, skipping.",
        )

    if (
        job.status == JobStatus.STT_SUBMITTED
        and job.stt_operation_name
        and not is_gemini_flash_operation(job.stt_operation_name)
    ):
        return _ok(
            job.id, job.status.value,
            "Speech v2 LRO already submitted, skipping Gemini Flash.",
            stt_operation_name=job.stt_operation_name,
            fallback="speech_v2",
        )

    gcs_uri = gemini_stt_output_uri(job.id)

    try:
        result = transcribe_audio_gcs(
            payload.gcs_input_uri,
            source_hint=job.file_details.file_extension if job.file_details else None,
        )
        write_gemini_transcript_json(gcs_uri, result)
        batch_repository.update_job_status(
            db, job.id,
            status=JobStatus.STT_COMPLETED,
            gcs_stt_output_uri=gcs_uri,
        )
        return _ok(
            job.id, JobStatus.STT_COMPLETED.value,
            "Gemini Flash STT completed",
            gcs_stt_output_uri=gcs_uri,
        )
    except STTGeminiTransientError as exc:
        logger.warning(
            "Gemini Flash STT transient error job=%s attempt=%s last=%s: %s",
            job.id, retry_count, last_attempt, exc,
        )
        if last_attempt:
            return _fallback_or_fail(db, job, payload)
        return _retry_later(job.id, f"[{type(exc).__name__}] {exc.message}")
    except STTError as exc:
        logger.error(
            "Gemini Flash STT error job=%s: [%s] %s retryable=%s",
            job.id, type(exc).__name__, exc.message, exc.retryable,
        )
        if exc.retryable and not last_attempt:
            return _retry_later(job.id, f"[{type(exc).__name__}] {exc.message}")
        if exc.retryable and last_attempt:
            return _fallback_or_fail(db, job, payload)
        return _fail_stt(db, job, exc)
    except Exception as exc:
        logger.exception("Unexpected Gemini Flash STT error for job %s", job.id)
        if not last_attempt:
            return _retry_later(job.id, f"[Unexpected] {type(exc).__name__}: {exc}")
        try:
            return _fallback_or_fail(db, job, payload)
        except Exception:
            logger.exception("Speech v2 fallback also failed for job %s", job.id)
            error_msg = f"[Unexpected] {type(exc).__name__}: {exc}"
            file_name = job.file_details.file_name if job.file_details else None
            db.add(FailedJob(
                job_id=job.id, file_name=file_name,
                error_message=error_msg, pipeline_stage="STT",
            ))
            batch_repository.update_job_status(
                db, job.id,
                status=JobStatus.ERROR,
                error_message=error_msg,
                increment_retry=True,
            )
            db.commit()
            return _ok(job.id, JobStatus.ERROR.value, "Gemini Flash STT unexpected error")


def _fail_stt(db: Session, job, exc: STTError):
    error_msg = f"[{type(exc).__name__}] {exc.message}"
    file_name = job.file_details.file_name if job.file_details else None
    db.add(FailedJob(
        job_id=job.id, file_name=file_name,
        error_message=error_msg, pipeline_stage="STT",
    ))
    if exc.retryable:
        batch_repository.update_job_status(
            db, job.id,
            status=JobStatus.ERROR,
            error_message=error_msg,
            increment_retry=True,
        )
        job_status = JobStatus.ERROR.value
    else:
        batch_repository.update_job_status(
            db, job.id,
            status=JobStatus.FAILED,
            error_message=error_msg,
        )
        job_status = JobStatus.FAILED.value
    db.commit()
    return make_response(
        success=False,
        message="STT submission failed",
        data=GeminiSTTResponseData(job_id=job.id, status=job_status).model_dump(),
        error=error_msg,
    )
