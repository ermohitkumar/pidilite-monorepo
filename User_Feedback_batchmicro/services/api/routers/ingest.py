"""
/file — Eventarc-triggered file ingestion endpoint.

Receives the GCS object upload event, parses the payload and custom metadata, 
and creates a new Job + FileDetails record in Cloud SQL with status PENDING.
"""
import logging
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.config import settings
from core.response import make_response, make_error_response
from db.session import get_db
from repositories import batch_repository
from db.models import Job, FileDetails, FailedJob
from core.enums import JobStatus
from schemas.schemas import GCSObjectPayload, IngestResponseData
from services.shared.dw_lookup import resolve_file_metadata
from services.shared.filename_metadata import FILENAME_METADATA_PATTERN  # noqa: F401
from services.shared.stt_config import resolved_audio_mime

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Files"])

def _extract_bucket_from_selflink(self_link: str | None) -> str:
    """Parse bucket name from a GCS selfLink URL."""
    if self_link:
        match = re.search(r"/b/([^/]+)/o/", self_link)
        if match:
            return match.group(1)
    return settings.GCS_INPUT_BUCKET


def _parse_gcs_time(value: str | None) -> datetime | None:
    """Parse GCS object timeCreated / updated (RFC3339, often with Z)."""
    if not value or not str(value).strip():
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Ignoring unparseable GCS timestamp: %s", value)
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

@router.post("/file", summary="Register a new uploaded file", status_code=status.HTTP_200_OK)
def ingest_file(
    payload: GCSObjectPayload,
    db: Session = Depends(get_db),
):
    bucket = payload.bucket or _extract_bucket_from_selflink(payload.selfLink)
    gcs_uri = f"gs://{bucket}/{payload.name}"
    file_name = os.path.basename(payload.name)
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    logger.info("Ingest request received: %s (size=%s)", gcs_uri, payload.size)

    existing = db.query(Job).filter(Job.gcs_input_uri == gcs_uri).first()
    if existing:
        logger.info("Duplicate ingest skipped — job %s already exists for %s", existing.id, gcs_uri)
        return make_response(
            success=True,
            message="File already ingested",
            data=IngestResponseData(
                job_id=existing.id,
                file_name=file_name,
                gcs_input_uri=gcs_uri,
                status=existing.status.value,
            ).model_dump(),
        )

    job = Job(gcs_input_uri=gcs_uri, status=JobStatus.PENDING)

    custom_meta = payload.metadata or {}
    resolved = resolve_file_metadata(db, file_name, custom_meta)

    # ── File Validation ──
    ALLOWED_EXTENSIONS = {"webm", "mp3", "wav", "ogg"}

    if extension not in ALLOWED_EXTENSIONS:
        logger.warning("Rejected ingest: Unsupported file extension '%s' for %s", extension, file_name)
        job.status = JobStatus.FAILED

    call_date = resolved.get("call_date")
    if isinstance(call_date, str):
        call_date = _parse_gcs_time(call_date)

    file_details = FileDetails(
        file_name=file_name,
        mime_type=resolved_audio_mime(extension, payload.contentType),
        file_size_bytes=payload.size,
        file_extension=extension,
        checksum_sha256=payload.md5Hash,
        file_uploaded_at=(
            _parse_gcs_time(payload.timeCreated)
            or _parse_gcs_time(payload.updated)
            or datetime.now(timezone.utc)
        ),
        call_date=call_date,
        state=resolved.get("state"),
        division=resolved.get("division"),
        zone=resolved.get("zone"),
        cluster=resolved.get("cluster"),
        rfmm_cluster=resolved.get("rfmm_cluster") or resolved.get("rbdm_cluster"),
        town_city=resolved.get("town_city"),
        tsi_territory_code=resolved.get("tsi_territory_code"),
        fme_code=resolved.get("fme_code") or resolved.get("bde_code"),
        tty_code=resolved.get("tty_code"),
        user_id_metadata=resolved.get("user_id"),
        user_type=resolved.get("user_type"),
        data_source=resolved.get("data_source", "Voice Conversations"),
        site_number=resolved.get("site_number"),
        membership_no=resolved.get("membership_no"),
        bde_code=resolved.get("bde_code"),
        visit_sfid=resolved.get("visit_sfid"),
        cmdi_code=resolved.get("cmdi_code"),
        site_id=resolved.get("site_id"),
        additional_event_id=resolved.get("additional_event_id"),
    )

    try:
        job = batch_repository.create_job(db, job, file_details)
        if job.status == JobStatus.FAILED:
            error_msg = f"Unsupported file format '.{extension}'. Accepted formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            db.add(FailedJob(job_id=job.id, file_name=file_name, error_message=error_msg, pipeline_stage="INGEST"))
            db.commit()
            return make_response(
                success=True,
                message="File rejected due to unsupported format",
                data=IngestResponseData(
                    job_id=job.id,
                    file_name=file_name,
                    gcs_input_uri=gcs_uri,
                    status=job.status.value,
                ).model_dump(),
                error=error_msg
            )
    except Exception as exc:
        logger.error("Failed to create job for %s: %s", gcs_uri, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error_response(
                message="Failed to create job",
                error=str(exc),
            ).model_dump(),
        )

    logger.info("Job %s created successfully for %s", job.id, file_name)
    return make_response(
        success=True,
        message="File ingested successfully",
        data=IngestResponseData(
            job_id=job.id,
            file_name=file_name,
            gcs_input_uri=gcs_uri,
            status=job.status.value,
        ).model_dump(),
    )