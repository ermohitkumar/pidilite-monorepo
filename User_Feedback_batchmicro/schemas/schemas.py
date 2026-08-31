"""
Pydantic v2 schemas — request/response models for all API endpoints.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════════
# COMMON RESPONSE ENVELOPE
# ═══════════════════════════════════════════════════════════════════════════════

class APIResponse(BaseModel):
    """Standard V1 API response envelope used by all /api/v1/* endpoints."""
    success: bool
    message: str
    data: Optional[Any] = None
    error: Optional[str] = None
    timestamp: str          # ISO 8601 UTC
    request_id: str


# ═══════════════════════════════════════════════════════════════════════════════
# EVENTARC — GCS Object Payload (used by Ingest & STT-complete)
# ═══════════════════════════════════════════════════════════════════════════════

class GCSObjectPayload(BaseModel):
    """Raw GCS object metadata as sent by Eventarc on object.finalize."""
    name: str
    bucket: Optional[str] = None
    contentType: Optional[str] = None
    size: Optional[str] = None
    crc32c: Optional[str] = None
    etag: Optional[str] = None
    md5Hash: Optional[str] = None
    timeCreated: Optional[str] = None
    updated: Optional[str] = None
    storageClass: Optional[str] = None
    generation: Optional[str] = None
    metageneration: Optional[str] = None
    selfLink: Optional[str] = None
    mediaLink: Optional[str] = None
    metadata: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1 — POST /api/v1/file
# ═══════════════════════════════════════════════════════════════════════════════

class IngestResponseData(BaseModel):
    job_id: str
    file_name: str
    gcs_input_uri: str
    status: str


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 2 — POST /api/v1/batch
# ═══════════════════════════════════════════════════════════════════════════════

class BatchStartResponseData(BaseModel):
    batch_id: str
    jobs_enqueued: int


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 3 — POST /api/v1/files/transcription
# ═══════════════════════════════════════════════════════════════════════════════

class STTSubmitRequest(BaseModel):
    job_id: str
    gcs_input_uri: str
    gcs_output_uri_prefix: Optional[str] = None
    batch_id: Optional[str] = None
    language_code: str = "hi-IN"
    model: str = "telephony"


class STTSubmitResponseData(BaseModel):
    job_id: str
    status: str
    stt_operation_name: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 3b — POST /api/v1/files/gemini-stt
# ═══════════════════════════════════════════════════════════════════════════════

class GeminiSTTRequest(BaseModel):
    job_id: str
    gcs_input_uri: str
    gcs_output_uri_prefix: Optional[str] = None
    batch_id: Optional[str] = None
    language_code: str = "hi-IN"
    model: str = "telephony"


class GeminiSTTResponseData(BaseModel):
    job_id: str
    status: str
    stt_operation_name: Optional[str] = None
    gcs_stt_output_uri: Optional[str] = None
    fallback: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4a — POST /api/v1/files/stt-complete
# ═══════════════════════════════════════════════════════════════════════════════

class SttCompleteResponseData(BaseModel):
    job_id: str
    status: str
    action: str = "unknown"  # enqueued_translate | skipped | enqueue_failed
    previous_status: Optional[str] = None
    skip_reason: Optional[str] = None
    cloud_task_name: Optional[str] = None
    gcs_stt_output_uri: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4b — POST /api/v1/files/translate
# ═══════════════════════════════════════════════════════════════════════════════

class TranslateRequest(BaseModel):
    job_id: str
    gcs_transcript_uri: str


class TranslateResponseData(BaseModel):
    job_id: str
    status: str
    action: str = "unknown"  # translated | skipped | failed | idempotent
    previous_status: Optional[str] = None
    skip_reason: Optional[str] = None
    cloud_task_name: Optional[str] = None
    translated_chars: Optional[int] = None
    raw_transcript_chars: Optional[int] = None


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4c — POST /api/v1/files/post-processing
# ═══════════════════════════════════════════════════════════════════════════════

class PostProcessRequest(BaseModel):
    job_id: str


class NormalizeInsightsResponseData(BaseModel):
    job_id: str
    status: str
    insights_generated: bool


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 5 — POST /api/v1/checker/run
# ═══════════════════════════════════════════════════════════════════════════════

class CheckerRunRequest(BaseModel):
    max_jobs_to_check: int = Field(default=50, ge=1, le=500)

class CheckerRunResponseData(BaseModel):
    jobs_checked: int
    jobs_recovered: int
    jobs_marked_failed: int
    jobs_still_pending: int
    # Breakdown for debugging stuck jobs (Eventarc / Cloud Tasks / filter races)
    stt_lro_polled: int = 0
    stt_lro_completed: int = 0
    stt_lro_errored: int = 0
    translate_kicked: int = 0
    translate_kick_skipped_no_uri: int = 0
    stuck_batched_recovered: int = 0
    stuck_translating_recovered: int = 0
    stuck_translated_recovered: int = 0
    stuck_post_processing_recovered: int = 0
    batches_reconciled: int = 0
