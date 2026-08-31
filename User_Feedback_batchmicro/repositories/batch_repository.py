"""
Shared repository helpers. Each function is a thin DB query — no business logic.
Business logic lives in the individual service routers.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.orm import Session

from db.models import (
    Batch, Job, FileDetails, ProcessedFile,
    Feedback, FeedbackCompetitor,
    Product, FeedbackTag,
    KeywordDictionary, AppConfig,
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


def claim_pending_jobs(db: Session, limit: int) -> List[Job]:
    """
    Atomically claim up to `limit` PENDING jobs for batching.

    On PostgreSQL uses FOR UPDATE SKIP LOCKED so concurrent /batch callers
    cannot claim the same rows. SQLite falls back to a plain SELECT (tests).
    """
    query = (
        db.query(Job)
        .filter(Job.status == JobStatus.PENDING)
        .order_by(Job.created_at)
        .limit(limit)
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    return query.all()


def touch_job(db: Session, job_id: str) -> Optional[Job]:
    """Bump updated_at without changing status (anti-loop cooldown after enqueue)."""
    job = get_job(db, job_id)
    if not job:
        return None
    job.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(job)
        return job
    except Exception as exc:
        db.rollback()
        logger.error("Failed to touch job %s: %s", job_id, exc, exc_info=True)
        raise


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


def get_job_by_stt_output_path(db: Session, gcs_path_segment: str) -> Optional[Job]:
    """Find a job whose gcs_stt_output_uri contains the given path segment."""
    return (
        db.query(Job)
        .filter(Job.gcs_stt_output_uri.contains(gcs_path_segment))
        .first()
    )


def create_job(db: Session, job: Job, file_details: FileDetails) -> Job:
    try:
        db.add(job)
        db.flush()  # get job.id before adding child
        file_details.job_id = job.id
        db.add(file_details)
        db.commit()
        db.refresh(job)
        logger.info("Created job %s for file '%s'", job.id, file_details.file_name)
        return job
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create job: %s", exc, exc_info=True)
        raise


def update_job_status(
    db: Session,
    job_id: str,
    status: JobStatus,
    error_message: Optional[str] = None,
    gcs_stt_output_uri: Optional[str] = None,
    stt_operation_name: Optional[str] = None,
    increment_retry: bool = False,
) -> Optional[Job]:
    job = get_job(db, job_id)
    if not job:
        logger.warning("update_job_status called for non-existent job %s", job_id)
        return None
    old_status = job.status
    job.status = status
    if error_message is not None:
        job.error_message = error_message
    elif status not in {JobStatus.ERROR, JobStatus.FAILED}:
        job.error_message = None
    if gcs_stt_output_uri is not None:
        job.gcs_stt_output_uri = gcs_stt_output_uri
    if stt_operation_name is not None:
        job.stt_operation_name = stt_operation_name
    if increment_retry:
        job.retry_count = (job.retry_count or 0) + 1
    try:
        db.commit()
        db.refresh(job)
        logger.info("Job %s status: %s → %s", job_id, old_status.value, status.value)
        if status in {JobStatus.COMPLETED, JobStatus.FAILED} and job.batch_id:
            evaluate_batch_status(db, job.batch_id)
        return job
    except Exception as exc:
        db.rollback()
        logger.error("Failed to update job %s status: %s", job_id, exc, exc_info=True)
        raise


# ── Batches ───────────────────────────────────────────────────────────────────

def get_batch(db: Session, batch_id: str) -> Optional[Batch]:
    return db.query(Batch).filter(Batch.id == batch_id).first()


def get_next_batch_number(db: Session) -> int:
    """Allocate next batch_number; lock latest row on Postgres to avoid duplicates."""
    query = db.query(Batch).order_by(Batch.batch_number.desc())
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update()
    last = query.first()
    return (last.batch_number + 1) if last else 1


def create_batch(db: Session, batch: Batch) -> Batch:
    try:
        db.add(batch)
        db.commit()
        db.refresh(batch)
        logger.info("Created batch #%d (id=%s)", batch.batch_number, batch.id)
        return batch
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create batch: %s", exc, exc_info=True)
        raise


_ACTIVE_JOB_STATUSES = {
    JobStatus.PENDING,
    JobStatus.BATCHED,
    JobStatus.STT_SUBMITTED,
    JobStatus.STT_COMPLETED,
    JobStatus.TRANSLATING,
    JobStatus.TRANSLATED,
    JobStatus.PROCESSING,
    JobStatus.NORMALIZED,
    JobStatus.INSIGHTS,
}

# ERROR is retryable as a job, but the batch should close after a checker tick
# (PARTIAL_SUCCESS if anything completed, FAILED if every job errored/failed).
_FAILED_LIKE = {JobStatus.FAILED, JobStatus.ERROR}


def evaluate_batch_status(db: Session, batch_id: str) -> bool:
    """Close a batch when every child job is COMPLETED, FAILED, or ERROR."""
    batch = get_batch(db, batch_id)
    if not batch:
        logger.warning("evaluate_batch_status called for non-existent batch %s", batch_id)
        return False
    jobs = get_jobs_by_batch_id(db, batch_id)
    if not jobs:
        return False
    statuses = [job.status for job in jobs]
    if any(status in _ACTIVE_JOB_STATUSES for status in statuses):
        return False
    all_completed = all(status == JobStatus.COMPLETED for status in statuses)
    all_failed = all(status in _FAILED_LIKE for status in statuses)
    if all_completed:
        final_status = BatchStatus.COMPLETED
    elif all_failed:
        final_status = BatchStatus.FAILED
    else:
        final_status = BatchStatus.PARTIAL_SUCCESS
    if batch.status == final_status:
        return False
    update_batch_status(db, batch_id, final_status)
    return True


def update_batch_status(db: Session, batch_id: str, status: BatchStatus) -> Optional[Batch]:
    from datetime import datetime, timezone
    batch = get_batch(db, batch_id)
    if not batch:
        logger.warning("update_batch_status called for non-existent batch %s", batch_id)
        return None
    old_status = batch.status
    batch.status = status
    if status in (BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.PARTIAL_SUCCESS):
        batch.completed_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(batch)
        logger.info("Batch %s status: %s → %s", batch_id, old_status.value, status.value)
        return batch
    except Exception as exc:
        db.rollback()
        logger.error("Failed to update batch %s status: %s", batch_id, exc, exc_info=True)
        raise


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

def get_active_products(db: Session) -> List[Product]:
    """Fetch all active products for the Vertex AI catalog prompt."""
    return db.query(Product).filter(Product.is_active==True).all()