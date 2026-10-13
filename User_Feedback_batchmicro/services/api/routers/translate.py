"""
/files/translate — Cloud Task handler for Vertex AI translation to English.

On success, enqueues post-processing Cloud Task.
"""
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.config import settings
from core.response import make_response
from core.enums import JobStatus
from db.session import get_db
from db.models import ProcessedFile, FailedJob
from repositories import batch_repository
from schemas.schemas import TranslateRequest, TranslateResponseData
from services.shared.cloud_tasks import enqueue_http_task
from services.shared.pipeline_debug import record_pipeline_note
from services.shared.transcript import (
    download_stt_json,
    extract_transcript_from_stt_json,
    MIN_TRANSCRIPT_WORDS,
    TOO_FEW_WORDS_MESSAGE,
    timed_utterances,
    word_count,
    transcript_meets_min_words,
)
from services.shared import vertex_ai
from services.shared.product_catalog import build_product_tsv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Files"])

_TRANSLATE_ALLOWED = frozenset({
    JobStatus.TRANSLATING,
    JobStatus.STT_COMPLETED,
    JobStatus.ERROR,
})


@router.post("/translate", summary="Translate STT transcript to English", status_code=status.HTTP_200_OK)
def translate_transcript(
    payload: TranslateRequest,
    db: Session = Depends(get_db),
):
    logger.info(
        "translate: job_id=%s gcs_transcript_uri=%s",
        payload.job_id, payload.gcs_transcript_uri,
    )

    job = batch_repository.get_job(db, payload.job_id)
    if not job:
        logger.warning("translate: job %s not found", payload.job_id)
        return make_response(
            success=True,
            message=f"Job {payload.job_id} not found, skipping.",
            data=TranslateResponseData(
                job_id=payload.job_id,
                status="NOT_FOUND",
                action="skipped",
                skip_reason="job not in database",
            ).model_dump(),
        )

    previous_status = job.status.value

    if job.status not in _TRANSLATE_ALLOWED:
        reason = (
            f"status {previous_status} not eligible for translate "
            f"(allowed: {', '.join(s.value for s in sorted(_TRANSLATE_ALLOWED, key=lambda x: x.value))})"
        )
        logger.warning("translate: job %s skipped — %s", payload.job_id, reason)
        record_pipeline_note(db, payload.job_id, "translate", reason, level="warning")
        return make_response(
            success=True,
            message=f"Job {payload.job_id} skipped: {reason}",
            data=TranslateResponseData(
                job_id=payload.job_id,
                status=previous_status,
                action="skipped",
                previous_status=previous_status,
                skip_reason=reason,
            ).model_dump(),
        )

    processed = (
        db.query(ProcessedFile)
        .filter(ProcessedFile.job_id == payload.job_id)
        .first()
    )

    try:
        # Idempotent: skip Vertex if translation already saved
        if processed and processed.translated_text:
            logger.info("translate: job %s idempotent — translation exists", payload.job_id)
            batch_repository.update_job_status(db, payload.job_id, status=JobStatus.TRANSLATED)
            task_name = enqueue_http_task(
                url=settings.CLOUD_TASKS_POSTPROCESS_URL,
                payload={"job_id": payload.job_id},
            )
            if task_name is None:
                msg = (
                    "Post-processing Cloud Task was NOT created (SDK unavailable or misconfigured). "
                    f"postprocess_url={settings.CLOUD_TASKS_POSTPROCESS_URL!r}"
                )
                logger.error("translate: job %s (idempotent) — %s", payload.job_id, msg)
                batch_repository.update_job_status(
                    db, payload.job_id,
                    status=JobStatus.ERROR,
                    error_message=f"[pipeline:translate] {msg}",
                    increment_retry=True,
                )
                return make_response(
                    success=False,
                    message=msg,
                    data=TranslateResponseData(
                        job_id=payload.job_id,
                        status=JobStatus.ERROR.value,
                        action="enqueue_failed",
                        previous_status=previous_status,
                        skip_reason=msg,
                        translated_chars=len(processed.translated_text),
                    ).model_dump(),
                    error=msg,
                )
            return make_response(
                success=True,
                message="Translation already complete, post-processing enqueued",
                data=TranslateResponseData(
                    job_id=payload.job_id,
                    status=JobStatus.TRANSLATED.value,
                    action="idempotent",
                    previous_status=previous_status,
                    cloud_task_name=task_name,
                    translated_chars=len(processed.translated_text),
                ).model_dump(),
            )

        raw_text = (
            processed.raw_transcript_text
            if processed and processed.raw_transcript_text
            else extract_transcript_from_stt_json(payload.gcs_transcript_uri)
        )
        raw_len = len(raw_text or "")
        spoken_words = word_count(raw_text or "")

        if not raw_text or not raw_text.strip():
            msg = (
                f"STT transcript empty from {payload.gcs_transcript_uri} "
                f"(check STT output JSON has results[].alternatives[].transcript)"
            )
            logger.error("translate: job %s — %s", payload.job_id, msg)
            batch_repository.update_job_status(
                db, payload.job_id,
                status=JobStatus.ERROR,
                error_message=f"[pipeline:translate] {msg}",
                increment_retry=True,
            )
            return make_response(
                success=False,
                message=msg,
                data=TranslateResponseData(
                    job_id=payload.job_id,
                    status=JobStatus.ERROR.value,
                    action="failed",
                    previous_status=previous_status,
                    skip_reason=msg,
                    raw_transcript_chars=raw_len,
                ).model_dump(),
                error=msg,
            )

        if not transcript_meets_min_words(raw_text):
            msg = f"{TOO_FEW_WORDS_MESSAGE} Got {spoken_words} word(s)."
            logger.error("translate: job %s — %s", payload.job_id, msg)
            job_row = batch_repository.get_job(db, payload.job_id)
            file_name = (
                job_row.file_details.file_name
                if job_row and job_row.file_details
                else None
            )
            db.add(FailedJob(
                job_id=payload.job_id,
                file_name=file_name,
                error_message=f"[pipeline:translate] {msg}",
                pipeline_stage="TRANSLATE",
            ))
            if processed:
                processed.raw_transcript_text = raw_text
                processed.empty_reason = msg
                processed.translated_text = None
                processed.insights_raw_json = None
            batch_repository.update_job_status(
                db, payload.job_id,
                status=JobStatus.FAILED,
                error_message=f"[pipeline:translate] {msg}",
            )
            db.commit()
            return make_response(
                success=False,
                message=msg,
                data=TranslateResponseData(
                    job_id=payload.job_id,
                    status=JobStatus.FAILED.value,
                    action="failed",
                    previous_status=previous_status,
                    skip_reason=msg,
                    raw_transcript_chars=raw_len,
                ).model_dump(),
                error=msg,
            )

        catalog = build_product_tsv(db)
        segments: list[dict] = []
        if payload.gcs_transcript_uri:
            try:
                segments = timed_utterances(download_stt_json(payload.gcs_transcript_uri))
            except Exception:
                logger.exception(
                    "translate: timed STT segments unavailable for job %s",
                    payload.job_id,
                )
        translated = ""
        if len(segments) >= 2:
            translated, _tokens = vertex_ai.label_timed_turns(
                segments,
                audio_gcs_uri=job.gcs_input_uri,
                product_catalog_tsv=catalog,
            )
        if not translated:
            translated, _tokens = vertex_ai.translate_transcript(
                raw_text,
                product_catalog_tsv=catalog,
            )

        if not processed:
            processed = ProcessedFile(job_id=payload.job_id)
            db.add(processed)
        processed.gcs_transcript_uri = payload.gcs_transcript_uri
        processed.raw_transcript_text = raw_text
        processed.translated_text = translated
        processed.processed_at = datetime.now(timezone.utc)
        db.commit()

        batch_repository.update_job_status(
            db, payload.job_id,
            status=JobStatus.TRANSLATED,
            error_message=None,
        )

        task_name = enqueue_http_task(
            url=settings.CLOUD_TASKS_POSTPROCESS_URL,
            payload={"job_id": payload.job_id},
        )
        if task_name is None:
            msg = (
                "Post-processing Cloud Task was NOT created (SDK unavailable or misconfigured). "
                f"postprocess_url={settings.CLOUD_TASKS_POSTPROCESS_URL!r}"
            )
            logger.error("translate: job %s — %s", payload.job_id, msg)
            batch_repository.update_job_status(
                db, payload.job_id,
                status=JobStatus.ERROR,
                error_message=f"[pipeline:translate] {msg}",
                increment_retry=True,
            )
            return make_response(
                success=False,
                message=msg,
                data=TranslateResponseData(
                    job_id=payload.job_id,
                    status=JobStatus.ERROR.value,
                    action="enqueue_failed",
                    previous_status=previous_status,
                    skip_reason=msg,
                    translated_chars=len(translated),
                    raw_transcript_chars=raw_len,
                ).model_dump(),
                error=msg,
            )

        record_pipeline_note(
            db, payload.job_id, "translate",
            f"translation saved ({len(translated)} chars), post-processing enqueued",
        )
        logger.info(
            "translate: job %s TRANSLATED raw=%d translated=%d task=%s",
            payload.job_id, raw_len, len(translated), task_name,
        )

        return make_response(
            success=True,
            message="Translation completed, post-processing enqueued",
            data=TranslateResponseData(
                job_id=payload.job_id,
                status=JobStatus.TRANSLATED.value,
                action="translated",
                previous_status=previous_status,
                cloud_task_name=task_name,
                translated_chars=len(translated),
                raw_transcript_chars=raw_len,
            ).model_dump(),
        )

    except Exception as exc:
        logger.exception("translate: failed for job %s", payload.job_id)
        batch_repository.update_job_status(
            db, payload.job_id,
            status=JobStatus.ERROR,
            error_message=f"[pipeline:translate] {exc}",
            increment_retry=True,
        )
        return make_response(
            success=False,
            message="Translation failed",
            data=TranslateResponseData(
                job_id=payload.job_id,
                status=JobStatus.ERROR.value,
                action="failed",
                previous_status=previous_status,
                skip_reason=str(exc),
            ).model_dump(),
            error=str(exc),
        )
