"""Feedback reports: per-page aggregations, paginated detail, lazy conversation.

SQL lives in repositories.report_repository. Apply batchmicro
scripts/sql/pbi_views.sql and reports_indexes.sql on the database.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.exceptions import APIException
from core.permissions import Permissions
from core.response import make_response
from core.dependencies import RoleChecker
from db.session import get_db
from repositories import report_repository as report_repo
from repositories.batch_repository import get_file_details_by_job_id, get_job
from services.api.gcs_audio import content_type_for_name, is_allowed_audio_uri

logger = logging.getLogger(__name__)

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
    dependencies=[Depends(RoleChecker(Permissions.VIEW_DASHBOARD))],
)

_FACT_ERROR = "Failed to retrieve feedback fact"
_DEFAULT_LIMIT = 8000
_MAX_LIMIT = 20000
_EMPTY_FILTERS = {
    "divisions": [],
    "zones": [],
    "clusters": [],
    "states": [],
    "products": [],
    "data_sources": [],
    "fme_codes": [],
    "user_types": [],
}
_VIEW_MISSING_MSG = (
    "vw_pbi_feedback_fact is not applied on this database. "
    "Apply batchmicro scripts/sql/pbi_views.sql, then retry."
)

_DIM_COLUMNS = [
    "feedback_id",
    "job_id",
    "feedback_created_at",
    "feedback_group",
    "feedback_category",
    "feedback_tag",
    "feedback_sub_tag",
    "product_name",
    "product_id",
    "product_short_code",
    "feedback_summary_ai",
    "feedback_excerpt",
    "competitors_mentioned",
    "file_name",
    "call_date",
    "language_code",
    "state",
    "division",
    "zone",
    "cluster",
    "rfmm_cluster",
    "town_city",
    "fme_code",
    "user_type",
    "data_source",
    "job_status",
    "audio_gcs_uri",
]

_SORTABLE = set(_DIM_COLUMNS) | {"full_conversation"}
_DEFAULT_ORDER = (
    "feedback_group, product_name NULLS LAST, "
    "feedback_category, feedback_tag, feedback_id"
)


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _row_to_item(row: Any, columns: list[str], include_conversation: bool) -> dict:
    item = {col: _serialize(row[idx]) for idx, col in enumerate(columns)}
    item["full_conversation_truncated"] = False
    if not include_conversation:
        item["full_conversation"] = None
        item["full_conversation_raw"] = None
    elif not item.get("full_conversation"):
        item["full_conversation"] = item.get("full_conversation_raw")
    return item


def _order_sql(sort_by: Optional[str], sort_dir: Optional[str], include_conversation: bool) -> str:
    if not sort_by:
        return _DEFAULT_ORDER
    if sort_by not in _SORTABLE:
        raise APIException(
            status_code=400,
            message=f"Invalid sort_by '{sort_by}'",
            error="Validation Error",
        )
    if sort_by == "full_conversation" and not include_conversation:
        raise APIException(
            status_code=400,
            message="sort_by=full_conversation requires include_conversation=true",
            error="Validation Error",
        )
    direction = "DESC" if (sort_dir or "asc").lower() == "desc" else "ASC"
    return f"{sort_by} {direction} NULLS LAST, feedback_id"


def _pagination_meta(page: int, page_size: int, total: int) -> dict:
    total_pages = math.ceil(total / page_size) if page_size > 0 else 0
    return {
        "current_page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


def _unavailable(message: str = _VIEW_MISSING_MSG, extra: Optional[dict] = None):
    payload = {
        "filter_options": dict(_EMPTY_FILTERS),
        "source": "unavailable",
        **(extra or {}),
    }
    return make_response(success=True, message=message, data=payload)


def _filters(
    feedback_group: Optional[str],
    product_name: Optional[str],
    feedback_category: Optional[str],
    feedback_tag: Optional[str],
    feedback_sub_tag: Optional[str],
    division: Optional[str],
    zone: Optional[str],
    cluster: Optional[str],
    state: Optional[str],
    data_source: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    search: Optional[str],
    *,
    fme_code: Optional[str] = None,
    user_type: Optional[str] = None,
    search_sql: str = report_repo.DIM_SEARCH,
    exact_tag: bool = False,
) -> tuple[str, dict]:
    return report_repo.build_filters(
        feedback_group=feedback_group,
        product_name=product_name,
        feedback_category=feedback_category,
        feedback_tag=feedback_tag,
        feedback_sub_tag=feedback_sub_tag,
        division=division,
        zone=zone,
        cluster=cluster,
        state=state,
        data_source=data_source,
        fme_code=fme_code,
        user_type=user_type,
        start_date=start_date,
        end_date=end_date,
        search=search,
        search_sql=search_sql,
        exact_tag=exact_tag,
    )


@router.get("/summary")
def get_report_summary(
    db: DbSession,
    feedback_group: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    feedback_category: Optional[str] = Query(None),
    feedback_tag: Optional[str] = Query(None),
    feedback_sub_tag: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    data_source: Optional[str] = Query(None),
    fme_code: Optional[str] = Query(None),
    user_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
):
    """Tag matrix page: COUNT(DISTINCT feedback_id) by category/tag. No transcripts."""
    empty = {"tags": [], "categories": [], "total": 0, "filter_options": dict(_EMPTY_FILTERS)}
    try:
        fact = report_repo.fact_table(db)
        where_sql, params = _filters(
            feedback_group, product_name, feedback_category, feedback_tag, feedback_sub_tag,
            division, zone, cluster, state, data_source, start_date, end_date, search,
            fme_code=fme_code, user_type=user_type,
        )
        counts = report_repo.summary_counts(db, fact, where_sql, params)
        options = report_repo.filter_options(db, fact)
    except report_repo.MissingFactView as exc:
        logger.warning("report summary view missing: %s", exc)
        return _unavailable(extra=empty)
    except Exception:
        logger.exception("Failed to retrieve report summary")
        raise APIException(status_code=500, message="Failed to retrieve report summary", error="Internal Error")

    return make_response(
        success=True,
        message="Report summary retrieved successfully",
        data={**counts, "filter_options": options, "source": fact},
    )


@router.get("/products")
def get_report_products(
    db: DbSession,
    feedback_group: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    feedback_category: Optional[str] = Query(None),
    feedback_tag: Optional[str] = Query(None),
    feedback_sub_tag: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    data_source: Optional[str] = Query(None),
    fme_code: Optional[str] = Query(None),
    user_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
):
    """Product breakdown page: counts by product_name for the current drill."""
    try:
        fact = report_repo.fact_table(db)
        where_sql, params = _filters(
            feedback_group, product_name, feedback_category, feedback_tag, feedback_sub_tag,
            division, zone, cluster, state, data_source, start_date, end_date, search,
            fme_code=fme_code, user_type=user_type,
        )
        items, total = report_repo.product_counts(db, fact, where_sql, params)
    except report_repo.MissingFactView as exc:
        logger.warning("report products view missing: %s", exc)
        return _unavailable(extra={"items": [], "total": 0})
    except Exception:
        logger.exception("Failed to retrieve report products")
        raise APIException(status_code=500, message="Failed to retrieve report products", error="Internal Error")

    return make_response(
        success=True,
        message="Report products retrieved successfully",
        data={"items": items, "total": total, "source": fact},
    )


@router.get("/details")
def get_report_details(
    db: DbSession,
    feedback_group: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    feedback_category: Optional[str] = Query(None),
    feedback_tag: Optional[str] = Query(None),
    feedback_sub_tag: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    data_source: Optional[str] = Query(None),
    fme_code: Optional[str] = Query(None),
    user_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: Optional[str] = Query("call_datetime"),
    sort_dir: Optional[str] = Query("desc"),
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(20, ge=1, le=50),
):
    """Paginated unique feedback rows without full conversations."""
    empty_meta = _pagination_meta(page, page_size, 0)
    try:
        fact = report_repo.fact_table(db)
        where_sql, params = _filters(
            feedback_group, product_name, feedback_category, feedback_tag, feedback_sub_tag,
            division, zone, cluster, state, data_source, start_date, end_date, search,
            fme_code=fme_code, user_type=user_type,
            search_sql=report_repo.DETAIL_SEARCH,
        )
        items, total = report_repo.detail_page(
            db, fact, where_sql, params,
            page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir,
        )
    except report_repo.MissingFactView as exc:
        logger.warning("report details view missing: %s", exc)
        return _unavailable(extra={"items": [], "metadata": empty_meta})
    except Exception:
        logger.exception("Failed to retrieve report details")
        raise APIException(status_code=500, message="Failed to retrieve report details", error="Internal Error")

    meta = _pagination_meta(page, page_size, total)
    meta.update({
        "returned_items": len(items),
        "sort_by": sort_by,
        "sort_dir": (sort_dir or "desc").lower(),
    })
    return make_response(
        success=True,
        message="Report details retrieved successfully",
        data={"items": items, "metadata": meta, "source": fact},
    )


@router.get("/conversation")
def get_report_conversation(
    db: DbSession,
    feedback_id: str = Query(..., min_length=8, max_length=64),
    job_id: Optional[str] = Query(None, min_length=8, max_length=64),
):
    """Lazy-load one transcript when the user opens View full conversation."""
    try:
        item = report_repo.conversation(db, feedback_id, job_id)
    except report_repo.MissingFactView as exc:
        logger.warning("report conversation view missing: %s", exc)
        raise APIException(status_code=404, message="Conversation is not available", error="Not Found")
    except Exception:
        logger.exception("Failed to retrieve conversation")
        raise APIException(status_code=500, message="Failed to retrieve conversation", error="Internal Error")

    if not item:
        raise APIException(status_code=404, message="Conversation not found", error="Not Found")
    return make_response(success=True, message="Conversation retrieved successfully", data=item)


@router.get("/feedback-fact")
def get_feedback_fact(
    db: DbSession,
    feedback_group: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    feedback_category: Optional[str] = Query(None),
    feedback_tag: Optional[str] = Query(None),
    feedback_sub_tag: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    data_source: Optional[str] = Query(None),
    fme_code: Optional[str] = Query(None),
    user_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    include_conversation: bool = Query(False),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: Optional[int] = Query(None, ge=1, le=500),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
):
    """Return vw_pbi_feedback_fact rows. Kept for compatibility; UI uses /summary and /details."""
    columns = list(_DIM_COLUMNS)
    select_columns = list(_DIM_COLUMNS)
    if include_conversation:
        columns.extend(["full_conversation", "full_conversation_raw"])
        select_columns.extend(
            [
                "NULLIF(TRIM(full_conversation), '') AS full_conversation",
                "NULLIF(TRIM(full_conversation_raw), '') AS full_conversation_raw",
            ]
        )

    order_sql = _order_sql(sort_by, sort_dir, include_conversation)
    where_sql, params = _filters(
        feedback_group, product_name, feedback_category, feedback_tag, feedback_sub_tag,
        division, zone, cluster, state, data_source, start_date, end_date, search,
        fme_code=fme_code, user_type=user_type,
        search_sql=report_repo.FACT_SEARCH,
        exact_tag=True,
    )

    paginate = page_size is not None
    params["limit"] = page_size if paginate else limit + 1
    params["offset"] = (page - 1) * page_size if paginate else 0

    empty_meta = {
        "total_items": 0,
        "returned_items": 0,
        "truncated": False,
        "include_conversation": include_conversation,
        "current_page": page,
        "page_size": page_size or limit,
        "total_pages": 0,
        "has_next": False,
        "has_previous": False,
        "sort_by": sort_by,
        "sort_dir": (sort_dir or "asc").lower(),
    }
    try:
        rows, total = report_repo.fetch_feedback_fact(
            db, where_sql, params, select_columns, order_sql,
        )
        options = report_repo.filter_options(db, report_repo.FAT_VIEW)
    except report_repo.MissingFactView as exc:
        logger.warning("feedback fact view missing: %s", exc)
        return make_response(
            success=True,
            message=_VIEW_MISSING_MSG,
            data={
                "items": [],
                "filter_options": dict(_EMPTY_FILTERS),
                "metadata": empty_meta,
                "source": "unavailable",
            },
        )
    except Exception:
        logger.exception("Failed to retrieve feedback fact")
        raise APIException(status_code=500, message=_FACT_ERROR, error="Internal Error")

    truncated = False
    if not paginate:
        truncated = len(rows) > limit
        rows = rows[:limit]
    items = [_row_to_item(row, columns, include_conversation) for row in rows]
    effective_size = page_size or limit
    meta = _pagination_meta(page, effective_size, total)
    meta.update({
        "returned_items": len(items),
        "truncated": truncated,
        "include_conversation": include_conversation,
        "sort_by": sort_by,
        "sort_dir": (sort_dir or "asc").lower(),
    })

    return make_response(
        success=True,
        message="Feedback fact retrieved successfully",
        data={
            "items": items,
            "filter_options": options,
            "metadata": meta,
            "source": report_repo.FAT_VIEW,
        },
    )


@router.get("/audio-locator")
def get_audio_locator(
    db: DbSession,
    job_id: str = Query(..., min_length=8, max_length=64),
):
    """Return the private GCS locator for a job. Browser clients must not call this;
    the Next.js audio route uses it server-side after session checks."""
    job = get_job(db, job_id)
    if not job or not job.gcs_input_uri:
        raise APIException(
            status_code=404,
            message="Audio not found for this job",
            error="Not Found",
        )
    if not is_allowed_audio_uri(job.gcs_input_uri):
        logger.warning("Rejected audio locator for job %s: bucket not allowlisted", job_id)
        raise APIException(
            status_code=403,
            message="Audio is not in an allowed bucket",
            error="Forbidden",
        )
    details = None
    try:
        details = get_file_details_by_job_id(db, job_id)
    except Exception:
        logger.exception("file_details lookup failed for job %s; using GCS object name", job_id)
        db.rollback()
    file_name = (details.file_name if details else "") or job.gcs_input_uri.rsplit("/", 1)[-1]
    mime = details.mime_type if details else None
    return make_response(
        success=True,
        message="Audio locator retrieved",
        data={
            "job_id": job.id,
            "file_name": file_name,
            "gcs_uri": job.gcs_input_uri,
            "content_type": content_type_for_name(file_name, mime),
        },
    )
