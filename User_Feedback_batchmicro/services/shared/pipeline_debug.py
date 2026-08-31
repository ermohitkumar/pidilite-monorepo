"""Pipeline observability — structured notes and response helpers."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from repositories import batch_repository

logger = logging.getLogger(__name__)


def record_pipeline_note(
    db: Session,
    job_id: str,
    step: str,
    message: str,
    *,
    level: str = "info",
) -> None:
    """
    Persist a human-readable note on jobs.error_message without changing status.
    Format: [pipeline:{step}] {message}
    """
    note = f"[pipeline:{step}] {message}"
    job = batch_repository.get_job(db, job_id)
    if not job:
        return
    job.error_message = note
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to record pipeline note for job %s", job_id)
        return
    log_fn = logger.warning if level == "warning" else logger.info
    log_fn("Job %s pipeline note (%s): %s", job_id, step, message)


def pipeline_response_data(
    *,
    job_id: str,
    status: str,
    action: str,
    previous_status: Optional[str] = None,
    skip_reason: Optional[str] = None,
    cloud_task_name: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Standard debug fields returned in API data envelopes."""
    data: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "action": action,
    }
    if previous_status is not None:
        data["previous_status"] = previous_status
    if skip_reason:
        data["skip_reason"] = skip_reason
    if cloud_task_name:
        data["cloud_task_name"] = cloud_task_name
    if extra:
        data.update(extra)
    return data
