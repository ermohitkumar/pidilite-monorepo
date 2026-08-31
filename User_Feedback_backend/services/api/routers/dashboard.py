import json
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload, load_only, noload
from sqlalchemy import inspect as sa_inspect, or_, String, func, case, asc, desc, text

from core.response import make_response
from core.exceptions import APIException
from core.enums import BatchStatus, JobStatus
from core.permissions import Permissions
from db.session import get_db
from db.models import Job, Batch, FileDetails, ProcessedFile
from core.dependencies import RoleChecker

from schemas.schemas import (
    APIResponse,
    DashboardSummaryResponse,
    DashboardBatchesResponse,
    DashboardSingleBatchResponse,
    DashboardJobsResponse,
    _coerce_datetime,
)
_INTERNAL_ERROR = "Internal Error"
logger = logging.getLogger(__name__)

# ── Annotated dependency aliases ──
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
SortDir = Annotated[Optional[str], Query()]

_JOB_SORT = {
    "job_id": Job.id,
    "batch_id": Job.batch_id,
    "file_name": FileDetails.file_name,
    "created_at": Job.created_at,
    "status": Job.status,
}
_BATCH_SORT = {
    "batch_id": Batch.id,
    "batch_number": Batch.batch_number,
    "status": Batch.status,
    "created_at": Batch.created_at,
    "completed_at": Batch.completed_at,
}


def _escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters to prevent wildcard injection."""
    return value.replace("%", r"\%").replace("_", r"\_")


# SECURED ROUTER: Only logged-in Admins/Super Admins can access
router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(RoleChecker(Permissions.VIEW_DASHBOARD))]
)


def _get_pagination_meta(page: int, size: int, total: int) -> dict:
    total_pages = math.ceil(total / size) if size > 0 else 0
    return {
        "current_page": page,
        "page_size": size,
        "total_items": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    }


def _order(column, sort_dir: Optional[str]):
    return desc(column) if (sort_dir or "desc") != "asc" else asc(column)


def _apply_job_sort(query, sort_by: Optional[str], sort_dir: Optional[str], *, joined_files: bool):
    column = _JOB_SORT.get(sort_by or "created_at", Job.created_at)
    if column is FileDetails.file_name and not joined_files:
        query = query.outerjoin(FileDetails)
    return query.order_by(_order(column, sort_dir), desc(Job.id))


def _apply_batch_sort(query, sort_by: Optional[str], sort_dir: Optional[str]):
    column = _BATCH_SORT.get(sort_by or "created_at", Batch.created_at)
    return query.order_by(_order(column, sort_dir), desc(Batch.id))


def _batch_job_counts(db: Session, batch_ids: list[str]) -> dict:
    if not batch_ids:
        return {}
    rows = (
        db.query(
            Job.batch_id,
            func.count(Job.id),
            func.coalesce(func.sum(case((Job.status == JobStatus.COMPLETED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Job.status.in_(
                [JobStatus.FAILED, JobStatus.ERROR]), 1), else_=0)), 0),
        )
        .filter(Job.batch_id.in_(batch_ids))
        .group_by(Job.batch_id)
        .all()
    )
    return {
        str(batch_id): {
            "total_jobs": int(total),
            "completed_jobs": int(completed),
            "failed_jobs": int(failed),
        }
        for batch_id, total, completed, failed in rows
    }


def _job_item(job: Job, *, include_batch: bool = False) -> dict:
    item = {
        "job_id": str(job.id),
        "file_name": job.file_details.file_name if job.file_details else "Unknown",
        "status": job.status.value,
        "created_at": job.created_at,
        "has_insights": job.summary is not None,
        "error_message": job.error_message,
    }
    if include_batch:
        item["batch_id"] = str(job.batch_id) if job.batch_id else None
        item["batch_number"] = job.batch.batch_number if job.batch else None
    return item


def _table_columns(db: Session, table: str) -> set[str]:
    try:
        return {column["name"] for column in sa_inspect(db.get_bind()).get_columns(table)}
    except Exception:
        logger.debug("Could not inspect table %s", table, exc_info=True)
        return set()


def _feedbacks_columns(db: Session) -> set[str]:
    return _table_columns(db, "feedbacks")


def _as_text(value) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _insight_feedbacks(db: Session, job: Job) -> list[dict]:
    """Production uses ai_summary / group_type; local tests still use remarks."""
    columns = _feedbacks_columns(db)
    if "ai_summary" in columns:
        tag_link_cols = _table_columns(db, "feedback_tag_link")
        tag_cols = _table_columns(db, "feedback_tags")
        tag_pk = "tag_id" if "tag_id" in tag_cols else "id"
        tag_select = (
            f"""
                    (
                        SELECT string_agg(t.tag_name, ', ')
                        FROM feedback_tag_link l
                        JOIN feedback_tags t ON t.{tag_pk} = l.tag_id
                        WHERE l.feedback_id = f.id
                    ) AS tag_name
            """
            if tag_link_cols and tag_cols
            else "NULL AS tag_name"
        )
        rows = db.execute(
            text(
                f"""
                SELECT
                    f.product_name,
                    f.group_type,
                    f.category_type AS category_name,
                    f.verbatim_quote,
                    f.ai_summary AS remarks,
                    {tag_select}
                FROM feedbacks f
                WHERE f.job_id::text = :job_id
                ORDER BY f.created_at
                """
            ),
            {"job_id": str(job.id)},
        ).mappings().all()
        return [
            {
                "product_name": _as_text(row["product_name"]),
                "category_name": _as_text(row["category_name"]),
                "tag_name": _as_text(row["tag_name"]),
                "group_type": _as_text(row["group_type"]),
                "verbatim_quote": _as_text(row["verbatim_quote"]),
                "remarks": _as_text(row["remarks"]),
                "sentiment_label": None,
                "sentiment_score": None,
            }
            for row in rows
        ]

    return [{
        "product_name": _as_text(fb.product.product_name) if fb.product else None,
        "category_name": _as_text(fb.category.category_name) if getattr(fb, "category", None) else None,
        "tag_name": _as_text(fb.tag.tag_name) if getattr(fb, "tag", None) else None,
        "group_type": _as_text(getattr(fb, "group_type", None)),
        "verbatim_quote": _as_text(fb.verbatim_quote),
        "remarks": _as_text(fb.remarks),
        "sentiment_label": _as_text(fb.sentiment_label),
        "sentiment_score": fb.sentiment_score,
    } for fb in job.feedbacks.all()]


def _feedbacks_from_raw_json(db: Session, job_id) -> list[dict]:
    """Gemini payload on processed_file when PDT skips left feedbacks empty."""
    if "insights_raw_json" not in _table_columns(db, "processed_file"):
        return []
    row = db.execute(
        text(
            "SELECT insights_raw_json FROM processed_file WHERE job_id::text = :job_id"
        ),
        {"job_id": str(job_id)},
    ).first()
    payload = row[0] if row else None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, list):
        return []
    items = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        items.append({
            "product_name": _as_text(item.get("product_name")),
            "category_name": _as_text(
                item.get("category_type") or item.get("category_name")),
            "tag_name": _as_text(item.get("tag_name")),
            "group_type": _as_text(item.get("group_type")),
            "verbatim_quote": _as_text(item.get("verbatim_quote")),
            "remarks": _as_text(
                item.get("summary") or item.get("remarks") or item.get("ai_summary")),
            "sentiment_label": _as_text(item.get("sentiment_label")),
            "sentiment_score": item.get("sentiment_score"),
        })
    return items


def _job_summary_row(db: Session, job_id) -> Optional[dict]:
    columns = _table_columns(db, "job_summaries")
    wanted = [
        "overall_sentiment_label",
        "overall_sentiment_score",
        "summary_product",
        "summary_price_schemes",
        "summary_quality",
        "summary_service",
        "created_at",
    ]
    select_cols = [column for column in wanted if column in columns]
    if not select_cols:
        return None
    return db.execute(
        text(
            f"SELECT {', '.join(select_cols)} FROM job_summaries WHERE job_id = :job_id"
        ),
        {"job_id": str(job_id)},
    ).mappings().first()

# ── 0. Dashboard Summary (KPI Cards) ─────────────────────────────────────────


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(db: DbSession):
    """Returns KPI card data for the main Batch Monitoring page header."""
    try:
        total_batches = db.query(Batch).count()
        completed_batches = db.query(Batch).filter(
            Batch.status == BatchStatus.COMPLETED).count()
        active_batches_count = db.query(Batch).filter(
            Batch.status == BatchStatus.PROCESSING).count()
        active_jobs_count = db.query(Job).filter(
            Job.status.in_([JobStatus.PENDING, JobStatus.BATCHED,
                           JobStatus.STT_SUBMITTED, JobStatus.PROCESSING])
        ).count()

        cutoff_24h = (datetime.now(timezone.utc) -
                      timedelta(hours=24)).isoformat()
        completed_24h = db.query(Job).filter(
            Job.status == JobStatus.COMPLETED, Job.updated_at >= cutoff_24h).count()
        total_jobs = db.query(Job).count()
        success_rate = round((completed_24h / total_jobs)
                             * 100, 1) if total_jobs > 0 else 0.0

        failed_count = db.query(Job).filter(Job.status.in_(
            [JobStatus.FAILED, JobStatus.ERROR])).count()

        return make_response(
            success=True,
            message="Dashboard summary retrieved successfully",
            data={
                "total_batches": total_batches,
                "completed_batches": completed_batches,
                "active_batches": {"count": active_batches_count, "active_jobs": active_jobs_count},
                "files_processed_24h": {"count": completed_24h, "success_rate": success_rate},
                "failed_files": {"count": failed_count}
            }
        )
    except Exception:
        logger.exception("Failed to retrieve dashboard summary")
        raise APIException(
            status_code=500, message="Failed to retrieve dashboard summary", error=_INTERNAL_ERROR)

# ── 1. Batch Monitoring (Main View) ──────────────────────────────────────────


@router.get("/batches", response_model=DashboardBatchesResponse)
def list_batches(
    db: DbSession,
    page: Page = 1, size: PageSize = 10,
    search: Optional[str] = None, status: Optional[str] = None,
    sort_by: Optional[str] = None, sort_dir: SortDir = "desc",
):
    try:
        query = db.query(Batch)
        if search:
            safe_search = _escape_like(search)
            query = query.filter(or_(Batch.id.cast(String).ilike(
                f"%{safe_search}%"), Batch.batch_number.cast(String).ilike(f"%{safe_search}%")))
        if status:
            query = query.filter(Batch.status == status)

        total = query.count()
        batches = (
            _apply_batch_sort(query, sort_by, sort_dir)
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        counts = _batch_job_counts(db, [batch.id for batch in batches])

        items = []
        for batch in batches:
            stats = counts.get(str(batch.id), {
                "total_jobs": 0, "completed_jobs": 0, "failed_jobs": 0,
            })
            items.append({
                "batch_id": str(batch.id),
                "batch_number": batch.batch_number,
                "status": batch.status.value,
                **stats,
                "created_at": batch.created_at,
                "completed_at": batch.completed_at
            })

        return make_response(success=True, message="Batches retrieved successfully", data={"items": items, "metadata": _get_pagination_meta(page, size, total)})
    except Exception:
        logger.exception("Failed to retrieve batches")
        raise APIException(
            status_code=500, message="Failed to retrieve batches", error=_INTERNAL_ERROR)

# ── 2. Single Batch View ─────────────────────────────────────────────────────


@router.get("/batches/{batch_id}", response_model=DashboardSingleBatchResponse)
def get_single_batch(
    batch_id: str, db: DbSession,
    page: Page = 1, size: PageSize = 10,
    search: Optional[str] = None, status: Optional[str] = None,
    sort_by: Optional[str] = None, sort_dir: SortDir = "desc",
):
    try:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise APIException(
                status_code=404, message="Batch not found", error="NotFound")

        jobs_query = db.query(Job).filter(Job.batch_id == batch_id)
        joined_files = False
        if search:
            safe_search = _escape_like(search)
            jobs_query = jobs_query.outerjoin(FileDetails).filter(or_(Job.id.cast(
                String).ilike(f"%{safe_search}%"), FileDetails.file_name.ilike(f"%{safe_search}%")))
            joined_files = True
        if status:
            jobs_query = jobs_query.filter(Job.status == status)

        total_jobs = jobs_query.count()
        jobs = (
            _apply_job_sort(jobs_query, sort_by, sort_dir, joined_files=joined_files)
            .options(joinedload(Job.file_details), joinedload(Job.summary))
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )

        all_jobs_query = db.query(Job).filter(Job.batch_id == batch_id)
        completed = all_jobs_query.filter(
            Job.status == JobStatus.COMPLETED).count()
        failed = all_jobs_query.filter(Job.status.in_(
            [JobStatus.FAILED, JobStatus.ERROR])).count()

        items = [_job_item(job) for job in jobs]

        return make_response(success=True, message="Batch details retrieved successfully", data={
            "batch_info": {
                "batch_id": str(batch.id), "batch_number": batch.batch_number, "status": batch.status.value,
                "total_jobs": all_jobs_query.count(), "completed_jobs": completed, "failed_jobs": failed,
                "created_at": batch.created_at, "completed_at": batch.completed_at
            },
            "jobs": {
                "items": items,
                "metadata": {**_get_pagination_meta(page, size, total_jobs), "completed_jobs": completed, "failed_jobs": failed}
            }
        })
    except APIException:
        raise
    except Exception:
        logger.exception("Failed to retrieve batch details")
        raise APIException(
            status_code=500, message="Failed to retrieve batch details", error=_INTERNAL_ERROR)

# ── 3. Global Jobs List (All Files) ──────────────────────────────────────────


@router.get("/jobs", response_model=DashboardJobsResponse)
def list_jobs(
    db: DbSession,
    page: Page = 1, size: PageSize = 10,
    search: Optional[str] = None, status: Optional[str] = None,
    sort_by: Optional[str] = None, sort_dir: SortDir = "desc",
):
    try:
        query = db.query(Job)
        joined_files = False
        if search:
            safe_search = _escape_like(search)
            query = query.outerjoin(FileDetails).outerjoin(Batch).filter(or_(
                Job.id.cast(String).ilike(f"%{safe_search}%"),
                FileDetails.file_name.ilike(f"%{safe_search}%"),
                Batch.batch_number.cast(String).ilike(f"%{safe_search}%"),
                Job.batch_id.cast(String).ilike(f"%{safe_search}%"),
            ))
            joined_files = True
        if status:
            query = query.filter(Job.status == status)

        total = query.count()
        jobs = (
            _apply_job_sort(query, sort_by, sort_dir, joined_files=joined_files)
            .options(
                joinedload(Job.file_details),
                joinedload(Job.batch),
                joinedload(Job.summary),
            )
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )

        items = [_job_item(job, include_batch=True) for job in jobs]

        return make_response(success=True, message="Jobs retrieved successfully", data={"items": items, "metadata": _get_pagination_meta(page, size, total)})
    except Exception:
        logger.exception("Failed to retrieve jobs")
        raise APIException(
            status_code=500, message="Failed to retrieve jobs", error=_INTERNAL_ERROR)

# ── 4. File-Level Insights (Single Audio View) ───────────────────────────────


@router.get("/jobs/{job_id}/insights", response_model=APIResponse)
def get_job_insights(job_id: str, db: DbSession):
    """File page: transcripts, insights, and pipeline error for one job."""
    try:
        job = (
            db.query(Job)
            .options(
                joinedload(Job.file_details).load_only(FileDetails.file_name),
                noload(Job.processed_file),
                noload(Job.summary),
            )
            .filter(Job.id == job_id)
            .first()
        )
        if not job:
            raise APIException(
                status_code=404, message="Job not found", error="NotFound")

        processed = (
            db.query(ProcessedFile)
            .options(load_only(
                ProcessedFile.raw_transcript_text,
                ProcessedFile.translated_text,
                ProcessedFile.empty_reason,
            ))
            .filter(ProcessedFile.job_id == job.id)
            .first()
        )
        summary = _job_summary_row(db, job.id)
        file_details = job.file_details
        feedbacks = _insight_feedbacks(db, job)
        if not feedbacks:
            feedbacks = _feedbacks_from_raw_json(db, job.id)
        generated_at = _coerce_datetime(
            ((summary or {}).get("created_at") if summary else None) or job.updated_at
        )
        status = job.status.value if getattr(job.status, "value", None) else (
            str(job.status) if job.status else None
        )

        return make_response(
            success=True,
            message="File insights retrieved successfully",
            data={
                "job_id": str(job.id),
                "file_name": file_details.file_name if file_details and file_details.file_name else "Unknown",
                "status": status,
                "error_message": _as_text(job.error_message),
                "empty_reason": _as_text(processed.empty_reason if processed else None),
                "raw_transcript_text": _as_text(
                    processed.raw_transcript_text if processed else None),
                "translated_text": _as_text(
                    processed.translated_text if processed else None),
                "normalized_text": None,
                "summary": {
                    "overall_sentiment_label": _as_text(
                        (summary or {}).get("overall_sentiment_label")),
                    "overall_sentiment_score": (summary or {}).get(
                        "overall_sentiment_score"),
                    "summary_product": _as_text(
                        (summary or {}).get("summary_product")),
                    "summary_price_schemes": _as_text(
                        (summary or {}).get("summary_price_schemes")),
                    "summary_quality": _as_text(
                        (summary or {}).get("summary_quality")),
                    "summary_service": _as_text(
                        (summary or {}).get("summary_service")),
                },
                "feedbacks": feedbacks,
                "generated_at": generated_at.isoformat() if generated_at else None,
            }
        )

    except APIException:
        raise
    except Exception:
        logger.exception("Failed to retrieve file insights")
        raise APIException(
            status_code=500,
            message="Failed to retrieve file insights",
            error=_INTERNAL_ERROR)
