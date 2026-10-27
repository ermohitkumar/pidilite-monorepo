"""Feedback reports: per-page aggregations, paginated detail, lazy conversation.

SQL lives in repositories.report_repository. Apply batchmicro
scripts/sql/pbi_views.sql and reports_indexes.sql on the database.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from types import SimpleNamespace
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.exceptions import APIException
from core.permissions import Permissions
from core.response import make_response
from core.dependencies import RoleChecker, get_current_user
from db.session import get_db
from repositories import report_repository as report_repo
from repositories.batch_repository import get_file_details_by_job_id, get_job
from services.api.gcs_audio import content_type_for_name, is_allowed_audio_uri
from services.period_summarize import store as period_store
from services.period_summarize.compact import format_findings, merge_findings
from services.period_summarize.period_keys import (
    group_token,
    infer_period,
    list_grain_for_filters,
    parse_insight_key,
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


# Product × tag rows already stored from the audios, used when the cluster rollup
# has not been written yet (for example the visit has no RFMM cluster).
_STORED_PRODUCT_TAG_GRAINS = ("rfmm_pt", "zone_pt", "div_pt", "bde_pt")


def _merge_same_tag(rows: list[Any]) -> list[Any]:
    """One row per tag. Several officers' product summaries are kept together."""
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(_tag_dedupe_key(row), []).append(row)
    merged: list[Any] = []
    for group in grouped.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        texts: list[str] = []
        for row in group:
            text = (getattr(row, "summary_text", None) or "").strip()
            if text and text not in texts:
                texts.append(text)
        base = group[0]
        merged.append(SimpleNamespace(
            grain=base.grain,
            grain_key=base.grain_key,
            grain_label=base.grain_label,
            summary_text="\n\n".join(texts),
            status=getattr(base, "status", None),
            highlights_json=getattr(base, "highlights_json", None),
        ))
    return merged


def _tag_dedupe_key(row: Any) -> str:
    try:
        parsed = parse_insight_key(row.grain, row.grain_key)
        tag_id = parsed.get("tag_id") or ""
        group = parsed.get("group_type") or ""
        if tag_id:
            return f"{group}::{tag_id}"
    except ValueError:
        pass
    return f"{row.grain_key}::{row.grain_label}"


def _tag_lookup_keys(row: Any) -> list[str]:
    keys = period_store.label_keys(row.grain_label) + period_store.label_keys(row.grain_key)
    label = row.grain_label or ""
    if " × " in label:
        keys.extend(period_store.label_keys(label.split(" × ", 1)[-1]))
    try:
        keys.extend(period_store.label_keys(parse_insight_key(row.grain, row.grain_key).get("tag_id")))
    except ValueError:
        pass
    return keys


def _period_product_and_tag_rows(
    db: Session,
    *,
    period_type: str,
    period_key: str,
    token: Optional[str],
    geo_grain: Optional[str],
    geo_key: Optional[str],
    product_name: Optional[str],
) -> tuple[list[Any], list[Any]]:
    slices = slice_grains_for_geo(geo_grain)
    product_grain = slices["product"]
    if product_name:
        # Cluster × product × tag, rolled to zone, then to all_pt when no geo is selected.
        tag_grain = slices["cube"]
        tag_identity = geo_key if geo_grain else None
    else:
        tag_grain = slices["tag"]
        tag_identity = geo_key if geo_grain and tag_grain != "tag" else None
    product_identity = geo_key if geo_grain and product_grain != "product" else None
    product_rows = [
        row
        for row in period_store.filter_group(
            period_store.list_current(
                db, grain=product_grain, period_type=period_type, period_key=period_key, status="ok",
            ),
            token,
            identity=product_identity,
        )
        if period_store.matches_product(row, product_name)
    ]
    tag_rows = [
        row
        for row in period_store.filter_group(
            period_store.list_current(
                db, grain=tag_grain, period_type=period_type, period_key=period_key, status="ok",
            ),
            token,
            identity=tag_identity,
        )
        if period_store.matches_product(row, product_name)
    ]
    if product_name and not tag_rows and not geo_grain:
        stored: list[Any] = []
        for grain in _STORED_PRODUCT_TAG_GRAINS:
            stored.extend(
                row
                for row in period_store.filter_group(
                    period_store.list_current(
                        db, grain=grain, period_type=period_type, period_key=period_key, status="ok",
                    ),
                    token,
                )
                if period_store.matches_product(row, product_name)
            )
        tag_rows = _merge_same_tag(stored)
    if product_name and not geo_grain:
        seen: set[str] = set()
        unique: list[Any] = []
        for row in tag_rows:
            key = _tag_dedupe_key(row)
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        tag_rows = unique
    return product_rows, tag_rows


def _row_tag_id(row: Any) -> Optional[str]:
    try:
        parsed = parse_insight_key(row.grain, row.grain_key)
    except (ValueError, AttributeError):
        return None
    tag_id = parsed.get("tag_id")
    return str(tag_id) if tag_id else None


def _active_tag_catalog(db: Session) -> tuple[dict[tuple[str, str], str], set[str]]:
    """Map (category, level-3 name) to tag_id. Names like Others repeat across categories."""
    try:
        rows = db.execute(
            text(
                """
                SELECT tag_id, category, tag_name
                FROM feedback_tags
                WHERE is_active IS NOT FALSE
                """
            )
        ).fetchall()
    except (OperationalError, ProgrammingError):
        return {}, set()
    catalog: dict[tuple[str, str], str] = {}
    names: dict[str, set[str]] = {}
    for tag_id, category, tag_name in rows:
        if tag_id is None or not tag_name:
            continue
        name = period_store.norm_label(str(tag_name))
        catalog[(period_store.norm_label(category), name)] = str(tag_id)
        names.setdefault(name, set()).add(str(tag_id))
    ambiguous = {name for name, ids in names.items() if len(ids) > 1}
    return catalog, ambiguous


def _row_for_level_three(
    item: dict[str, Any],
    catalog: dict[tuple[str, str], str],
    ambiguous_names: set[str],
    by_tag_id: dict[str, Any],
    by_label: dict[str, Any],
) -> Any:
    name = period_store.norm_label(item.get("feedback_tag"))
    category = period_store.norm_label(item.get("feedback_category"))
    tag_id = catalog.get((category, name))
    if tag_id and by_tag_id.get(tag_id):
        return by_tag_id[tag_id]
    if name in ambiguous_names:
        return None
    for key in period_store.label_keys(item.get("feedback_tag")):
        row = by_label.get(key)
        if row:
            return row
    return None


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
    product_name: Optional[str] = None,
) -> list[dict[str, Any]]:
    token = group_token(feedback_group)
    geo_grain, geo_key = resolve_grain(
        fme_code=fme_code, cluster=cluster, zone=zone, division=division,
    )
    slices = slice_grains_for_geo(geo_grain)
    tag_grain = slices["cube"] if product_name else slices["tag"]
    _, tag_rows = _period_product_and_tag_rows(
        db,
        period_type=period_type,
        period_key=period_key,
        token=token,
        geo_grain=geo_grain,
        geo_key=geo_key,
        product_name=product_name,
    )
    if not tag_rows and tag_grain not in {"tag", "product"} and not geo_grain and not product_name:
        tag_rows = period_store.filter_group(
            period_store.list_current(
                db, grain="tag", period_type=period_type, period_key=period_key, status="ok",
            ),
            token,
        )
    if not tag_rows:
        latest = period_store.latest_period(db, grain=tag_grain, period_type=period_type)
        if not latest and tag_grain != "tag" and not geo_grain and not product_name:
            latest = period_store.latest_period(db, grain="tag", period_type=period_type)
            tag_grain = "tag"
        if latest:
            period_type, period_key = latest
            _, tag_rows = _period_product_and_tag_rows(
                db,
                period_type=period_type,
                period_key=period_key,
                token=token,
                geo_grain=geo_grain,
                geo_key=geo_key,
                product_name=product_name,
            )
    by_label: dict[str, Any] = {}
    by_tag_id: dict[str, Any] = {}
    for row in tag_rows:
        if not period_store.is_visible_summary(row):
            continue
        tag_id = _row_tag_id(row)
        if tag_id:
            by_tag_id.setdefault(tag_id, row)
        for key in _tag_lookup_keys(row):
            by_label.setdefault(key, row)
    catalog, ambiguous_names = _active_tag_catalog(db)
    attached = []
    for tag in tags:
        item = dict(tag)
        row = _row_for_level_three(item, catalog, ambiguous_names, by_tag_id, by_label)
        summary, status = _narrative_for_tag_row(row)
        item["ai_summary"] = summary
        item["summary_status"] = status
        highlights = getattr(row, "highlights_json", None) or {}
        sentiment = highlights.get("sentiment") if isinstance(highlights, dict) else None
        item["sentiment"] = sentiment if isinstance(sentiment, str) and sentiment.strip() else None
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
        return period_store.get_current_by_label(
            db, slice_grain, product_name, period_type, period_key,
            group_token=token, identity=geo_key,
        )
    return period_store.get_current_scoped(db, "product", product_name, period_type, period_key, token)


def _merged_category_summary(db, label, period_type, period_key, token):
    """Roll level-3 theme summaries up to the level-2 tag, keeping each product heading."""
    if not label:
        return None
    try:
        tag_ids = [
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT tag_id
                    FROM feedback_tags
                    WHERE is_active = true
                      AND LOWER(TRIM(COALESCE(category, ''))) = LOWER(TRIM(:label))
                    """
                ),
                {"label": label},
            ).fetchall()
        ]
    except (OperationalError, ProgrammingError):
        return None
    tokens = [token] if token else ["PDT", "USER", "DEALER"]
    rows = []
    for tag_id in tag_ids:
        for tok in tokens:
            row = period_store.get_current(db, "tag", f"{tag_id}::{tok}", period_type, period_key)
            if period_store.is_visible_summary(row):
                rows.append(row)
    if not rows:
        return None
    findings = [
        item
        for item in merge_findings([{"highlights": row.highlights_json or {}} for row in rows])
        if str(item.get("product") or item.get("title") or "").strip()
    ]
    summary_text = format_findings(findings)
    if not summary_text:
        return None
    visits = 0
    insights = 0
    for row in rows:
        highlights = row.highlights_json or {}
        visits += int(highlights.get("site_visit_count") or row.call_count or 0)
        insights += int(row.insight_count or highlights.get("insight_count") or 0)
    return {
        "id": f"category::{label}",
        "grain": "tag",
        "grain_key": label,
        "grain_label": label,
        "parent_key": None,
        "period_type": period_type,
        "period_key": period_key,
        "period_start": None,
        "period_end": None,
        "summary_text": summary_text,
        "highlights": {"findings": findings, "site_visit_count": visits, "insight_count": insights},
        "source_kind": "rollup",
        "source_count": len(rows),
        "call_count": visits,
        "insight_count": insights,
        "status": "ok",
        "version": 1,
        "is_current": True,
        "model_name": None,
        "prompt_tokens": None,
        "output_tokens": None,
        "error_message": None,
        "generated_at": None,
    }


def _tag_summary_payload(db, feedback_tag, period_type, period_key, token, geo_grain, geo_key):
    row = _serialize_visible(
        _lookup_tag_summary(db, feedback_tag, period_type, period_key, token, geo_grain, geo_key)
    )
    if row is not None or not feedback_tag:
        return row
    return _merged_category_summary(db, feedback_tag, period_type, period_key, token)


def _lookup_tag_summary(db, feedback_tag, period_type, period_key, token, geo_grain, geo_key):
    if not feedback_tag:
        return None
    if geo_grain and geo_key:
        slice_grain = slice_grains_for_geo(geo_grain)["tag"]
        return period_store.get_current_by_label(
            db, slice_grain, feedback_tag, period_type, period_key,
            group_token=token, identity=geo_key,
        )
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
    tag = _tag_summary_payload(db, feedback_tag, period_type, period_key, token, grain, grain_key)
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
        previous_tag = _tag_summary_payload(db, feedback_tag, prev_type, prev_key, token, grain, grain_key)
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
    product_rows, tag_rows = _period_product_and_tag_rows(
        db,
        period_type=period_type,
        period_key=period_key,
        token=token,
        geo_grain=geo_grain,
        geo_key=geo_key,
        product_name=product_name,
    )
    products = [
        period_store.serialize_row(row)
        for row in product_rows
        if period_store.is_visible_summary(row)
    ]
    tags = [
        period_store.serialize_row(row)
        for row in tag_rows
        if period_store.is_visible_summary(row)
    ]
    cube_grain = slice_grains_for_geo(geo_grain)["cube"]
    product_tags = [
        period_store.serialize_row(row)
        for row in period_store.filter_group(
            period_store.list_current(
                db, grain=cube_grain, period_type=period_type, period_key=period_key, status="ok",
            ),
            token,
            identity=geo_key if geo_grain else None,
        )
        if period_store.matches_product(row, product_name) and period_store.is_visible_summary(row)
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
            "product_tags": product_tags,
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
        where_sql = report_repo.where_summarized(db, fact, where_sql)
        counts = report_repo.summary_counts(db, fact, where_sql, params)
        counts["themes"] = report_repo.theme_counts(
            db,
            feedback_group=feedback_group,
            product_name=product_name,
            feedback_category=feedback_category,
            feedback_tag=feedback_tag,
            division=division,
            zone=zone,
            cluster=cluster,
            fme_code=fme_code,
            start_date=start_date,
            end_date=end_date,
        )
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
            product_name=product_name,
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
        # Filter dropdowns come from GET /filter-options — avoid a second fact scan.
        data={**counts, "filter_options": dict(_EMPTY_FILTERS), "source": fact},
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
        where_sql = report_repo.where_summarized(db, fact, where_sql)
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
        where_sql = report_repo.where_summarized(db, fact, where_sql)
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


@router.get("/compliance")
def get_compliance(
    db: DbSession,
    division: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    fme_code: Optional[str] = Query(None),
    user_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    user_timezone: str = Query("UTC", max_length=100),
):
    """Open-conversation compliance by FME: sites visited vs recorded."""
    try:
        items = report_repo.compliance_rows(
            db,
            division=division,
            zone=zone,
            cluster=cluster,
            fme_code=fme_code,
            user_type=user_type,
            start_date=start_date,
            end_date=end_date,
            user_timezone=user_timezone,
        )
    except Exception:
        logger.exception("Failed to retrieve compliance report")
        raise APIException(status_code=500, message="Failed to retrieve compliance report", error="Internal Error")
    # Filter dropdowns come from GET /filter-options — skip a second full scan here.
    return make_response(
        success=True,
        message="Compliance report retrieved successfully",
        data={"items": items},
    )


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


_AUDIO_PLAYBACK_ROLES = frozenset({"admin", "super_admin"})


def require_audio_playback(user: dict = Depends(get_current_user)) -> dict:
    """Recording playback is limited to Admin and Super Admin."""
    if user.get("role") not in _AUDIO_PLAYBACK_ROLES:
        raise APIException(
            status_code=403,
            message="Audio playback is limited to Admin and Super Admin",
            error="Forbidden",
        )
    return user


@router.get("/audio-locator")
def get_audio_locator(
    db: DbSession,
    _: dict = Depends(require_audio_playback),
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
