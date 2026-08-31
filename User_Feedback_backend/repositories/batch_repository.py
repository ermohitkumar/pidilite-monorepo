"""
Shared repository helpers. Each function is a thin DB query — no business logic.
Business logic lives in the individual service routers.
"""
import logging
from typing import Optional, List
from sqlalchemy.orm import Session

from db.models import (
    Batch, Job, FileDetails, ProcessedFile, Feedback, 
    JobSummary, KeywordDictionary, AppConfig
)
from core.enums import JobStatus, BatchStatus

logger = logging.getLogger(__name__)


# ── Jobs ──────────────────────────────────────────────────────────────────────

def get_job(db: Session, job_id: str) -> Optional[Job]:
    return db.query(Job).filter(Job.id == job_id).first()


def get_jobs_by_status(db: Session, status: JobStatus, limit: int = 200) -> List[Job]:
    return (
        db.query(Job)
        .filter(Job.status == status)
        .order_by(Job.created_at)
        .limit(limit)
        .all()
    )


def get_jobs_by_statuses(
    db: Session, statuses: List[JobStatus], limit: int = 200
) -> List[Job]:
    """Query jobs matching ANY of the given statuses."""
    return (
        db.query(Job)
        .filter(Job.status.in_(statuses))
        .order_by(Job.created_at)
        .limit(limit)
        .all()
    )

def get_jobs_by_batch_id(db: Session, batch_id: str) -> List[Job]:
    """Fetch all jobs belonging to a specific batch."""
    return db.query(Job).filter(Job.batch_id == batch_id).all()


def get_file_details_by_job_id(db: Session, job_id: str) -> Optional[FileDetails]:
    return db.query(FileDetails).filter(FileDetails.job_id == job_id).first()


def get_job_by_stt_output_path(db: Session, gcs_path_segment: str) -> Optional[Job]:
    """Find a job whose gcs_stt_output_uri contains the given path segment."""
    return (
        db.query(Job)
        .filter(Job.gcs_stt_output_uri.contains(gcs_path_segment))
        .first()
    )


# ── Batches ───────────────────────────────────────────────────────────────────

def get_batch(db: Session, batch_id: str) -> Optional[Batch]:
    return db.query(Batch).filter(Batch.id == batch_id).first()


def get_next_batch_number(db: Session) -> int:
    last = db.query(Batch).order_by(Batch.batch_number.desc()).first()
    return (last.batch_number + 1) if last else 1


# ── Keyword Dictionary ────────────────────────────────────────────────────────

def get_active_keywords(db: Session) -> List[KeywordDictionary]:
    return (
        db.query(KeywordDictionary)
        .order_by(KeywordDictionary.priority.desc())
        .all()
    )


# ── App Config ────────────────────────────────────────────────────────────────

def get_config(db: Session, key: str) -> Optional[AppConfig]:
    return db.query(AppConfig).filter(AppConfig.key == key).first()


def get_config_value(db: Session, key: str, default=None):
    cfg = get_config(db, key)
    if cfg and "value" in cfg.value:
        return cfg.value["value"]
    return default
