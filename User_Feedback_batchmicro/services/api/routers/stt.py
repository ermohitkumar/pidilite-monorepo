"""
/files/transcription — STT Transcription submission endpoint.

Called by Cloud Tasks. Submits a single audio file to Google Cloud
Speech-to-Text for asynchronous transcription. Saves the returned
stt_operation_name and updates job status to STT_SUBMITTED.

Error handling maps every documented Cloud STT error to a specific
exception class — retryable errors stay as ERROR for the checker,
non-retryable errors are marked FAILED immediately.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.config import settings
from core.response import make_response
from core.exceptions import (
    STTError,
    STTCredentialsError,
    STTPermissionDeniedError,
    STTInvalidArgumentError,
    STTBadEncodingError,
    STTMultiChannelError,
    STTQuotaExhaustedError,
    STTAudioTooLongError,
    STTPayloadTooLargeError,
    STTUnavailableError,
)
from db.session import get_db
from repositories import batch_repository
from core.enums import JobStatus
from db.models import FailedJob
from schemas.schemas import STTSubmitRequest, STTSubmitResponseData
from services.shared.cloud_tasks import enqueue_gemini_stt_task
from services.shared.gemini_stt import gemini_flash_operation_name
from services.shared.stt_client import (
    _HAS_SPEECH,
    reset_speech_client,
    submit_batch_recognize,
)
from services.shared.stt_config import is_audio_media

logger = logging.getLogger(__name__)

# gRPC exception types (may not be installed in test env)
try:
    from google.api_core.exceptions import (
        InvalidArgument,
        PermissionDenied,
        ResourceExhausted,
        OutOfRange,
        DeadlineExceeded,
        ServiceUnavailable,
    )
    from google.auth.exceptions import DefaultCredentialsError
    _HAS_GRPC_ERRORS = True
except ImportError:
    _HAS_GRPC_ERRORS = False


router = APIRouter(prefix="/files", tags=["Files"])


# ── STT Submission with Granular Error Handling ───────────────────────────────

def _submit_to_stt(
    gcs_uri: str,
    gcs_output_uri_prefix: str | None = None,
    language_code: str = "hi-IN",
    model: str = "telephony",
    source_hint: str | None = None,
) -> str:
    """
    Submit an async BatchRecognize LRO to Cloud Speech-to-Text v2 telephony.
    Returns the operation name (e.g. projects/.../locations/asia-south1/operations/...).
    Raises a specific STTError subclass for each documented error.
    """
    if not _HAS_SPEECH:
        raise RuntimeError("google-cloud-speech is not installed")

    try:
        return submit_batch_recognize(
            gcs_uri,
            gcs_output_uri_prefix,
            language_code=language_code,
            model=model,
        )
    except Exception as exc:
        reset_speech_client()
        if _HAS_GRPC_ERRORS and isinstance(exc, DefaultCredentialsError):
            raise STTCredentialsError(
                f"GCP credentials not found: {exc}"
            ) from exc
        if not _HAS_GRPC_ERRORS:
            raise STTError(str(exc)) from exc
        _reraise_stt_error(exc)


def _reraise_stt_error(exc: Exception) -> None:
    if isinstance(exc, PermissionDenied):
        raise STTPermissionDeniedError(
            f"Permission denied — ensure STT API is enabled: {exc}"
        ) from exc

    if isinstance(exc, InvalidArgument):
        msg = str(exc).lower()
        if "single channel" in msg or "mono" in msg:
            raise STTMultiChannelError(
                f"Audio must be mono (single channel): {exc}"
            ) from exc
        if "bad encoding" in msg or "16 bit" in msg or "encoding" in msg:
            raise STTBadEncodingError(
                f"Audio encoding mismatch: {exc}"
            ) from exc
        if "payload size" in msg or "exceeds" in msg:
            raise STTPayloadTooLargeError(
                f"Request too large — use GCS URI: {exc}"
            ) from exc
        raise STTInvalidArgumentError(
            f"Invalid STT config: {exc}"
        ) from exc

    if isinstance(exc, ResourceExhausted):
        raise STTQuotaExhaustedError(
            f"STT quota exceeded — retry later: {exc}"
        ) from exc

    if isinstance(exc, OutOfRange):
        raise STTAudioTooLongError(
            f"Audio exceeds maximum duration: {exc}"
        ) from exc

    if isinstance(exc, (DeadlineExceeded, ServiceUnavailable)):
        raise STTUnavailableError(
            f"STT service temporarily unavailable: {exc}"
        ) from exc

    raise STTError(str(exc)) from exc


# ── POST /files/transcription ─────────────────────────────────────────────────

@router.post("/transcription", summary="Submit file to Vertex AI for transcription", status_code=status.HTTP_200_OK)
def submit_stt(
    payload: STTSubmitRequest,
    db: Session = Depends(get_db),
):
    """
    Called by Cloud Tasks. Submits the audio file to Cloud STT and stores
    the LRO operation name. Updates job status to STT_SUBMITTED.
    """
    job = batch_repository.get_job(db, payload.job_id)
    if not job:
        # Return 200 to prevent Cloud Tasks from retrying a non-existent job
        return make_response(
            success=True,
            message=f"Job {payload.job_id} not found, skipping.",
            data=STTSubmitResponseData(
                job_id=payload.job_id,
                status="NOT_FOUND",
            ).model_dump(),
        )

    if job.status not in (JobStatus.BATCHED, JobStatus.ERROR):
        return make_response(
            success=True,
            message=f"Job {payload.job_id} is in status {job.status.value}, skipping.",
            data=STTSubmitResponseData(
                job_id=payload.job_id,
                status=job.status.value,
            ).model_dump(),
        )
        
    file_details = job.file_details
    if file_details:
        size = file_details.file_size_bytes or 0
        if size < 100:
            error_msg = f"Corrupted audio file: size is {size} bytes"
            db.add(FailedJob(job_id=job.id, file_name=file_details.file_name, error_message=error_msg, pipeline_stage="STT"))
            batch_repository.update_job_status(db, payload.job_id, status=JobStatus.FAILED, error_message=error_msg)
            db.commit()
            return make_response(
                success=False,
                message="STT submission failed - corrupted file",
                data=STTSubmitResponseData(job_id=payload.job_id, status=JobStatus.FAILED.value).model_dump(),
                error=error_msg
            )
        
        if not is_audio_media(file_details.file_extension, file_details.mime_type):
            error_msg = f"Invalid mime type: {file_details.mime_type or ''}"
            db.add(FailedJob(job_id=job.id, file_name=file_details.file_name, error_message=error_msg, pipeline_stage="STT"))
            batch_repository.update_job_status(db, payload.job_id, status=JobStatus.FAILED, error_message=error_msg)
            db.commit()
            return make_response(
                success=False,
                message="STT submission failed - invalid mime type",
                data=STTSubmitResponseData(job_id=payload.job_id, status=JobStatus.FAILED.value).model_dump(),
                error=error_msg
            )

    if settings.stt_provider == "gemini_flash":
        try:
            enqueue_gemini_stt_task({
                "job_id": payload.job_id,
                "gcs_input_uri": payload.gcs_input_uri,
                "gcs_output_uri_prefix": payload.gcs_output_uri_prefix,
                "batch_id": payload.batch_id,
                "language_code": payload.language_code,
                "model": payload.model,
            })
        except Exception as exc:
            logger.exception("Failed to enqueue Gemini Flash STT for job %s", payload.job_id)
            error_msg = f"[Unexpected] {type(exc).__name__}: {exc}"
            file_name = job.file_details.file_name if job.file_details else None
            db.add(FailedJob(job_id=job.id, file_name=file_name, error_message=error_msg, pipeline_stage="STT"))
            batch_repository.update_job_status(
                db, payload.job_id,
                status=JobStatus.ERROR,
                error_message=error_msg,
                increment_retry=True,
            )
            db.commit()
            return make_response(
                success=False,
                message="Gemini Flash STT enqueue failed",
                data=STTSubmitResponseData(
                    job_id=payload.job_id,
                    status=JobStatus.ERROR.value,
                ).model_dump(),
                error=error_msg,
            )
        operation_name = gemini_flash_operation_name(payload.job_id)
        batch_repository.update_job_status(
            db, payload.job_id,
            status=JobStatus.STT_SUBMITTED,
            stt_operation_name=operation_name,
        )
        return make_response(
            success=True,
            message="Gemini Flash STT enqueued",
            data=STTSubmitResponseData(
                job_id=payload.job_id,
                status=JobStatus.STT_SUBMITTED.value,
                stt_operation_name=operation_name,
            ).model_dump(),
        )

    try:
        source_hint = file_details.file_extension if file_details else None
        operation_name = _submit_to_stt(
            payload.gcs_input_uri,
            gcs_output_uri_prefix=payload.gcs_output_uri_prefix,
            language_code=payload.language_code,
            model=payload.model,
            source_hint=source_hint,
        )
        batch_repository.update_job_status(
            db, payload.job_id,
            status=JobStatus.STT_SUBMITTED,
            stt_operation_name=operation_name,
        )
        return make_response(
            success=True,
            message="STT job submitted successfully",
            data=STTSubmitResponseData(
                job_id=payload.job_id,
                status=JobStatus.STT_SUBMITTED.value,
                stt_operation_name=operation_name,
            ).model_dump(),
        )

    except STTError as exc:
        logger.error("STT error for job %s: [%s] %s (retryable=%s)",
                      payload.job_id, type(exc).__name__, exc.message, exc.retryable)
                      
        error_msg = f"[{type(exc).__name__}] {exc.message}"
        file_name = job.file_details.file_name if job.file_details else None
        db.add(FailedJob(job_id=job.id, file_name=file_name, error_message=error_msg, pipeline_stage="STT"))
        
        if exc.retryable:
            # Retryable — set ERROR, checker will retry later
            batch_repository.update_job_status(
                db, payload.job_id,
                status=JobStatus.ERROR,
                error_message=error_msg,
                increment_retry=True,
            )
        else:
            # Non-retryable — mark FAILED immediately, don't waste retries
            batch_repository.update_job_status(
                db, payload.job_id,
                status=JobStatus.FAILED,
                error_message=error_msg,
            )
        db.commit()
        return make_response(
            success=False,
            message="STT submission failed",
            data=STTSubmitResponseData(
                job_id=payload.job_id,
                status=JobStatus.FAILED.value if not exc.retryable else JobStatus.ERROR.value,
            ).model_dump(),
            error=error_msg,
        )

    except Exception as exc:
        logger.exception("Unexpected error in STT for job %s", payload.job_id)
        error_msg = f"[Unexpected] {type(exc).__name__}: {str(exc)}"
        file_name = job.file_details.file_name if job.file_details else None
        db.add(FailedJob(job_id=job.id, file_name=file_name, error_message=error_msg, pipeline_stage="STT"))
        
        batch_repository.update_job_status(
            db, payload.job_id,
            status=JobStatus.ERROR,
            error_message=error_msg,
            increment_retry=True,
        )
        db.commit()
        return make_response(
            success=False,
            message="STT submission unexpected error",
            data=STTSubmitResponseData(
                job_id=payload.job_id,
                status=JobStatus.ERROR.value,
            ).model_dump(),
            error=error_msg,
        )