"""Register existing GCS audio without a new upload event.

Lists objects under known sitelead day prefixes and calls the same ingest
path Eventarc uses. Duplicate gcs_input_uri rows are skipped by ingest.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from core.config import settings
from schemas.schemas import GCSObjectPayload
from services.api.routers.ingest import ingest_file

logger = logging.getLogger(__name__)

DEFAULT_DAYS = (
    "22:09:26",
    "23:09:26",
    "24:09:26",
    "25:09:26",
    "26:09:26",
    "28:09:26",
    "29:09:26",
)
AUDIO_EXTENSIONS = (".webm", ".mp3", ".wav", ".ogg")


def default_bucket() -> str:
    return (settings.GCS_INPUT_BUCKET or os.getenv("GCS_INPUT_BUCKET") or "pidilite-raw-audio").strip()


def list_audio_objects(
    *,
    bucket: Optional[str] = None,
    days: Optional[Iterable[str]] = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """List audio blobs under sitelead/<day>/ for the given day folders."""
    from google.cloud import storage

    bucket_name = bucket or default_bucket()
    client = storage.Client()
    day_list = [day.strip().strip("/") for day in (days or DEFAULT_DAYS) if day and day.strip()]
    blobs: list[dict[str, Any]] = []
    for day in day_list:
        prefix = f"sitelead/{day}/"
        for blob in client.list_blobs(bucket_name, prefix=prefix):
            name = blob.name or ""
            lower = name.lower()
            if not any(lower.endswith(ext) for ext in AUDIO_EXTENSIONS):
                continue
            time_created = None
            if blob.time_created:
                time_created = blob.time_created.astimezone(timezone.utc).isoformat()
            updated = None
            if blob.updated:
                updated = blob.updated.astimezone(timezone.utc).isoformat()
            blobs.append(
                {
                    "name": name,
                    "bucket": bucket_name,
                    "size": str(int(blob.size or 0)),
                    "contentType": blob.content_type or "audio/webm",
                    "md5Hash": blob.md5_hash,
                    "timeCreated": time_created,
                    "updated": updated,
                    "metadata": dict(blob.metadata or {}),
                    "gcs_uri": f"gs://{bucket_name}/{name}",
                }
            )
    blobs.sort(key=lambda item: item["name"])
    if limit > 0:
        return blobs[:limit]
    return blobs


def _payload_from_blob(blob: dict[str, Any]) -> GCSObjectPayload:
    return GCSObjectPayload(
        name=blob["name"],
        bucket=blob.get("bucket") or default_bucket(),
        contentType=blob.get("contentType"),
        size=str(blob.get("size") or "0"),
        md5Hash=blob.get("md5Hash"),
        timeCreated=blob.get("timeCreated"),
        updated=blob.get("updated"),
        metadata=blob.get("metadata") or {},
    )


def register_blob(db: Session, blob: dict[str, Any]) -> dict[str, Any]:
    """Register one object through ingest_file. Returns a compact result dict."""
    response = ingest_file(_payload_from_blob(blob), db)
    data = getattr(response, "data", None)
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    if isinstance(data, dict):
        payload = data
    else:
        payload = {}
    message = getattr(response, "message", "") or ""
    return {
        "gcs_uri": blob.get("gcs_uri") or f"gs://{blob.get('bucket')}/{blob['name']}",
        "job_id": payload.get("job_id"),
        "status": payload.get("status"),
        "message": message,
        "duplicate": message == "File already ingested",
    }


def replay_days(
    db: Session,
    *,
    bucket: Optional[str] = None,
    days: Optional[Iterable[str]] = None,
    limit: int = 0,
) -> dict[str, Any]:
    """List and register every audio object for the given day prefixes."""
    started = datetime.now(timezone.utc).isoformat()
    blobs = list_audio_objects(bucket=bucket, days=days, limit=limit)
    results: list[dict[str, Any]] = []
    created = 0
    duplicates = 0
    failed = 0
    for blob in blobs:
        try:
            result = register_blob(db, blob)
            results.append(result)
            if result.get("duplicate"):
                duplicates += 1
            elif str(result.get("status") or "").upper() == "FAILED":
                failed += 1
            else:
                created += 1
        except Exception as exc:
            logger.exception("backlog register failed for %s", blob.get("gcs_uri"))
            failed += 1
            results.append(
                {
                    "gcs_uri": blob.get("gcs_uri"),
                    "status": "ERROR",
                    "message": str(exc),
                    "duplicate": False,
                }
            )
    return {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "bucket": bucket or default_bucket(),
        "days": list(days or DEFAULT_DAYS),
        "listed": len(blobs),
        "created": created,
        "duplicates": duplicates,
        "failed": failed,
        "results": results,
    }
