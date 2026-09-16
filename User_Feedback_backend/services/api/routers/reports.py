"""Feedback reports: per-page aggregations, paginated detail, lazy conversation.

SQL lives in repositories.report_repository. Apply batchmicro
scripts/sql/pbi_views.sql and reports_indexes.sql on the database.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.exceptions import APIException
from core.permissions import Permissions
from core.response import make_response
from core.dependencies import RoleChecker
from db.session import get_db
from repositories import report_repository as report_repo
from repositories.batch_repository import get_file_details_by_job_id, get_job
from services.api.gcs_audio import content_type_for_name, is_allowed_audio_uri
from services.period_summarize import store as period_store
from services.period_summarize.period_keys import (
    group_token,
    infer_period,
    list_grain_for_filters,
    previous_period,
    resolve_grain,
    slice_grains_for_geo,
)
from services.period_summarize.runner import run as run_period_summaries

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
    "rfmm_clusters": [],
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


class PeriodSummaryRunRequest(BaseModel):
    period_type: Optional[str] = Field(None, description="month | quarter | year")
    period_key: Optional[str] = Field(None, description="2026-09, 2026-Q3, or 2026")
    force: bool = False


def _period_from_dates(start_date: Optional[date], end_date: Optional[date]) -> tuple[str, str]:
    if not start_date:
        from services.period_summarize.period_keys import current_month_key
        return "month", current_month_key()
    return infer_period(start_date, end_date or start_date)


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


def _narrative_for_tag_row(row: Any) -> tuple[Optional[str], Optional[str]]:
    if row is None:
        return None, None
    if not period_store.is_visible_summary(row):
        status = getattr(row, "status", None)
        if status == "error":
            return "Updating…", status
        return None, status
    return row.summary_text, getattr(row, "status", None)


def _serialize_visible(row: Any) -> Optional[dict[str, Any]]:
    if not period_store.is_visible_summary(row):
        return None
    return period_store.serialize_row(row)


def _attach_tag_ai_summaries(
    db: Session,
    tags: list[dict[str, Any]],
    period_type: str,
    period_key: str,
    *,
    feedback_group: Optional[str] = None,
    division: Optional[str] = None,
    zone: Optional[str] = None,
    cluster: Optional[str] = None,
    fme_code: Optional[str] = None,
) -> list[dict[str, Any]]:
    token = group_token(feedback_group)
    geo_grain, geo_key = resolve_grain(
        fme_code=fme_code, cluster=cluster, zone=zone, division=division,
    )
    slices = slice_grains_for_geo(geo_grain)
    tag_grain = slices["tag"]
    rows = period_store.list_current(
        db, grain=tag_grain, period_type=period_type, period_key=period_key,
    )
    rows = period_store.filter_group(rows, token, identity=geo_key if geo_grain else None)
    if not rows and tag_grain != "tag":
        rows = period_store.list_current(
            db, grain="tag", period_type=period_type, period_key=period_key,
        )
        rows = period_store.filter_group(rows, token)
    if not rows:
        latest = period_store.latest_period(db, grain=tag_grain, period_type=period_type)
        if not latest and tag_grain != "tag":
            latest = period_store.latest_period(db, grain="tag", period_type=period_type)
            tag_grain = "tag"
        if latest:
            period_type, period_key = latest
            rows = period_store.filter_group(
                period_store.list_current(
                    db, grain=tag_grain, period_type=period_type, period_key=period_key,
                ),
                token,
                identity=geo_key if geo_grain and tag_grain != "tag" else None,
            )
    by_label: dict[str, Any] = {}
    for row in rows:
        if not period_store.is_visible_summary(row):
            continue
        for key in period_store.label_keys(row.grain_label) + period_store.label_keys(row.grain_key):
            by_label.setdefault(key, row)
    attached = []
    for tag in tags:
        item = dict(tag)
        row = None
        for key in period_store.label_keys(item.get("feedback_tag")):
            row = by_label.get(key)
            if row:
                break
        summary, status = _narrative_for_tag_row(row)
        item["ai_summary"] = summary
        item["summary_status"] = status
        attached.append(item)
    return attached


def _lookup_geo_summary(db, grain, grain_key, period_type, period_key, token):
    if not grain or not grain_key:
        return None
    return period_store.get_current_scoped(db, grain, grain_key, period_type, period_key, token)


def _lookup_product_summary(db, product_name, period_type, period_key, token, geo_grain, geo_key):
    if not product_name:
        return None
    if geo_grain and geo_key:
        slice_grain = slice_grains_for_geo(geo_grain)["product"]
        row = period_store.get_current_by_label(
            db, slice_grain, product_name, period_type, period_key,
            group_token=token, identity=geo_key,
        )
        if row:
            return row
    return period_store.get_current_scoped(db, "product", product_name, period_type, period_key, token)


def _lookup_tag_summary(db, feedback_tag, period_type, period_key, token, geo_grain, geo_key):
    if not feedback_tag:
        return None
    if geo_grain and geo_key:
        slice_grain = slice_grains_for_geo(geo_grain)["tag"]
        row = period_store.get_current_by_label(
            db, slice_grain, feedback_tag, period_type, period_key,
            group_token=token, identity=geo_key,
        )
        if row:
            return row
    return period_store.get_current_by_label(
        db, "tag", feedback_tag, period_type, period_key, group_token=token,
    )


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


@router.get("/filter-options")
def get_report_filter_options(
    db: DbSession,
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
):
    """Linked dropdowns from vw_filter_hierarchy / vw_filter_options."""
    fact = None
    try:
        fact = report_repo.fact_table(db)
    except report_repo.MissingFactView:
        fact = None
    try:
        options = report_repo.filter_options(
            db, fact, division=division, zone=zone, cluster=cluster,
        )
    except Exception:
        logger.exception("Failed to retrieve report filter options")
        raise APIException(
            status_code=500,
            message="Failed to retrieve report filter options",
            error="Internal Error",
        )
    return make_response(
        success=True,
        message="Report filter options retrieved successfully",
        data=options,
    )


@router.get("/period-summary")
def get_period_summary(
    db: DbSession,
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    fme_code: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    feedback_tag: Optional[str] = Query(None),
    feedback_group: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    include_previous: bool = Query(True),
):
    """Stored narrative for the most specific filter grain. Does not call Gemini."""
    period_type, period_key = _period_from_dates(start_date, end_date)
    token = group_token(feedback_group)
    grain, grain_key = resolve_grain(
        fme_code=fme_code, cluster=cluster, zone=zone, division=division,
    )
    current = None
    if grain and grain_key:
        current = _serialize_visible(
            _lookup_geo_summary(db, grain, grain_key, period_type, period_key, token)
        )
    product = _serialize_visible(
        _lookup_product_summary(db, product_name, period_type, period_key, token, grain, grain_key)
    )
    tag = _serialize_visible(
        _lookup_tag_summary(db, feedback_tag, period_type, period_key, token, grain, grain_key)
    )
    previous = None
    previous_product = None
    previous_tag = None
    if include_previous:
        prev_type, prev_key = previous_period(period_type, period_key)
        if grain and grain_key:
            previous = _serialize_visible(
                _lookup_geo_summary(db, grain, grain_key, prev_type, prev_key, token)
            )
        previous_product = _serialize_visible(
            _lookup_product_summary(db, product_name, prev_type, prev_key, token, grain, grain_key)
        )
        previous_tag = _serialize_visible(
            _lookup_tag_summary(db, feedback_tag, prev_type, prev_key, token, grain, grain_key)
        )
    return make_response(
        success=True,
        message="Period summary retrieved successfully",
        data={
            "period_type": period_type,
            "period_key": period_key,
            "grain": grain,
            "grain_key": grain_key,
            "current": current,
            "previous": previous,
            "product": product,
            "previous_product": previous_product,
            "tag": tag,
            "previous_tag": previous_tag,
        },
    )


@router.get("/period-summaries")
def get_period_summaries(
    db: DbSession,
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    fme_code: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    feedback_group: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    """List stored current rows for the selected period (division cards when unfiltered)."""
    period_type, period_key = _period_from_dates(start_date, end_date)
    token = group_token(feedback_group)
    grain = list_grain_for_filters(
        fme_code=fme_code, cluster=cluster, zone=zone, division=division,
    )
    geo_grain, geo_key = resolve_grain(
        fme_code=fme_code, cluster=cluster, zone=zone, division=division,
    )
    parent_identity = None
    identity = None
    if fme_code:
        identity = fme_code
    elif cluster:
        parent_identity = cluster
    elif zone:
        parent_identity = zone
    elif division:
        parent_identity = division
    rows = period_store.filter_group(
        period_store.list_current(
            db,
            grain=grain,
            period_type=period_type,
            period_key=period_key,
            status="ok",
        ),
        token,
        identity=identity,
        parent_identity=parent_identity,
    )
    items = [period_store.serialize_row(row) for row in rows if period_store.is_visible_summary(row)]
    slices = slice_grains_for_geo(geo_grain)
    product_grain = slices["product"]
    tag_grain = slices["tag"]
    product_rows = period_store.filter_group(
        period_store.list_current(
            db, grain=product_grain, period_type=period_type, period_key=period_key, status="ok",
        ),
        token,
        identity=geo_key if geo_grain and product_grain != "product" else None,
    )
    if not product_rows and product_grain != "product":
        product_rows = period_store.filter_group(
            period_store.list_current(
                db, grain="product", period_type=period_type, period_key=period_key, status="ok",
            ),
            token,
        )
    products = [
        period_store.serialize_row(row)
        for row in product_rows
        if period_store.is_visible_summary(row)
    ]
    tag_rows = period_store.filter_group(
        period_store.list_current(
            db, grain=tag_grain, period_type=period_type, period_key=period_key, status="ok",
        ),
        token,
        identity=geo_key if geo_grain and tag_grain != "tag" else None,
    )
    if not tag_rows and tag_grain != "tag":
        tag_rows = period_store.filter_group(
            period_store.list_current(
                db, grain="tag", period_type=period_type, period_key=period_key, status="ok",
            ),
            token,
        )
    tags = [
        period_store.serialize_row(row)
        for row in tag_rows
        if period_store.is_visible_summary(row)
    ]
    available_filters = {
        "divisions": period_store.display_values(
            period_store.filter_group(
                period_store.list_current(
                    db, grain="division", period_type=period_type, period_key=period_key, status="ok",
                ),
                token,
            )
        ),
        "zones": period_store.display_values(
            period_store.filter_group(
                period_store.list_current(
                    db, grain="zone", period_type=period_type, period_key=period_key, status="ok",
                ),
                token,
            )
        ),
        "rfmm_clusters": period_store.display_values(
            period_store.filter_group(
                period_store.list_current(
                    db, grain="rfmm", period_type=period_type, period_key=period_key, status="ok",
                ),
                token,
            )
        ),
        "fme_codes": period_store.display_values(
            period_store.filter_group(
                period_store.list_current(
                    db, grain="bde", period_type=period_type, period_key=period_key, status="ok",
                ),
                token,
            )
        ),
        "products": list(dict.fromkeys(
            (row.grain_label or "")
            for row in product_rows
            if period_store.is_visible_summary(row) and row.grain_label
        )),
    }
    return make_response(
        success=True,
        message="Period summaries retrieved successfully",
        data={
            "period_type": period_type,
            "period_key": period_key,
            "grain": grain,
            "items": items,
            "products": products,
            "tags": tags,
            "available_filters": available_filters,
        },
    )


@router.post("/period-summaries/run")
def run_period_summary_job(
    db: DbSession,
    payload: PeriodSummaryRunRequest = Body(default=PeriodSummaryRunRequest()),
):
    """Nightly / ops job: generate stored period summaries. Scheduler hits this path."""
    try:
        result = run_period_summaries(
            db,
            period_type=payload.period_type,
            period_key=payload.period_key,
            force=payload.force,
        )
    except ValueError as exc:
        raise APIException(status_code=400, message=str(exc), error="Validation Error") from exc
    except Exception:
        logger.exception("Period summary run failed")
        raise APIException(
            status_code=500,
            message="Failed to run period summaries",
            error="Internal Error",
        )
    return make_response(
        success=True,
        message="Period summaries run completed",
        data=result,
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
        period_type, period_key = _period_from_dates(start_date, end_date)
        counts["tags"] = _attach_tag_ai_summaries(
            db,
            counts.get("tags") or [],
            period_type,
            period_key,
            feedback_group=feedback_group,
            division=division,
            zone=zone,
            cluster=cluster,
            fme_code=fme_code,
        )
        options = report_repo.filter_options(
            db, fact, division=division, zone=zone, cluster=cluster,
        )
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
        options = report_repo.filter_options(
            db, report_repo.FAT_VIEW, division=division, zone=zone, cluster=cluster,
        )
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
