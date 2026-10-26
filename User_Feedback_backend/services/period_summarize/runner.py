"""Ordered period-summary job.

The leaf is a cluster × product × level-3 tag summary. Product and tag
summaries are aggregated from that leaf, then rolled cluster → zone → all.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from core.config import settings
from services.period_summarize import combine, compact, store
from services.period_summarize.compact import lines_from_insights, source_hash
from services.period_summarize.llm import LLMError, summarize_lines
from services.period_summarize.period_keys import (
    MAX_MONTH_CELLS,
    TIME_ROLLUP_GRAINS,
    bounds_for,
    child_month_keys,
    child_quarter_keys,
    current_month_key,
    display_key,
    group_token,
    GROUP_TOKENS,
    is_last_month_of_quarter,
    is_last_month_of_year,
    mixed_key,
    quarter_key_from_month,
    scoped_key,
    split_key,
    utc_today,
    with_geo,
    year_key_from_month,
)

logger = logging.getLogger(__name__)

SummarizeFn = Callable[..., dict[str, Any]]
GatherFn = Callable[..., list[dict[str, Any]]]
ListNodesFn = Callable[..., list[dict[str, Optional[str]]]]
ListProductsFn = Callable[..., list[str]]
ListTagsFn = Callable[..., list[dict[str, str]]]
ListGroupsFn = Callable[..., list[str]]
ListCubeFn = Callable[..., list[dict[str, Optional[str]]]]
MAX_KEY_LEN = 200
_PARENT_FIELD = {
    "bde": "rfmm_key",
    "rfmm": "zone_key",
    "zone": "division_key",
    "bde_pt": "rfmm_key",
    "rfmm_pt": "zone_key",
    "zone_pt": "division_key",
    "bde_p": "rfmm_key",
    "rfmm_p": "zone_key",
    "zone_p": "division_key",
    "bde_t": "rfmm_key",
    "rfmm_t": "zone_key",
    "zone_t": "division_key",
}
_GEO_FIELD = {
    "bde": "bde_key",
    "rfmm": "rfmm_key",
    "zone": "zone_key",
    "division": "division_key",
    "bde_pt": "bde_key",
    "rfmm_pt": "rfmm_key",
    "zone_pt": "zone_key",
    "div_pt": "division_key",
    "bde_p": "bde_key",
    "rfmm_p": "rfmm_key",
    "zone_p": "zone_key",
    "div_p": "division_key",
    "bde_t": "bde_key",
    "rfmm_t": "rfmm_key",
    "zone_t": "zone_key",
    "div_t": "division_key",
}


class CellBudget:
    def __init__(self, max_cells: int = MAX_MONTH_CELLS):
        self.max_cells = max_cells
        self.used = 0
        self.capped = False

    def allow(self) -> bool:
        if self.used >= self.max_cells:
            self.capped = True
            return False
        self.used += 1
        return True


def _empty_result(reason: str) -> dict[str, Any]:
    return {
        "summary": reason,
        "themes": [],
        "products": [],
        "risks": [],
        "_tokens": {"input": 0, "output": 0},
        "_truncated": False,
    }


def _call_list(fn: Callable, db: Session, start: date, end: date, group_type: Optional[str] = None):
    try:
        return fn(db, start, end, group_type=group_type)
    except TypeError:
        return fn(db, start, end)


def _parent_identity(grain: str, node: dict[str, Optional[str]]) -> Optional[str]:
    field = _PARENT_FIELD.get(grain)
    if not field:
        return None
    return node.get(field)


def _nodes_for_grain(nodes: list[dict[str, Optional[str]]], grain: str) -> list[dict[str, Optional[str]]]:
    key_field = _GEO_FIELD.get(grain) or {
        "bde": "bde_key",
        "rfmm": "rfmm_key",
        "zone": "zone_key",
        "division": "division_key",
    }.get(grain)
    if not key_field:
        return []
    seen: set[str] = set()
    out: list[dict[str, Optional[str]]] = []
    for node in nodes:
        key = node.get(key_field)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(node)
    return out


def _lookup_parent_geo(grain: str, geo_identity: str, nodes: list[dict[str, Optional[str]]]) -> Optional[str]:
    field = _GEO_FIELD.get(grain)
    parent_field = _PARENT_FIELD.get(grain)
    if not field or not parent_field:
        return None
    for node in nodes:
        if node.get(field) == geo_identity:
            return node.get(parent_field)
    return None


def _write_node(
    db: Session,
    *,
    grain: str,
    grain_key: str,
    grain_label: Optional[str],
    parent_key: Optional[str],
    period_type: str,
    period_key: str,
    period_start: date,
    period_end: date,
    lines: list[str],
    highlights: dict[str, Any],
    source_kind: str,
    force: bool,
    summarize: SummarizeFn,
    budget: Optional[CellBudget] = None,
    previous_summary: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    highlights = dict(highlights)
    highlights.setdefault(
        "source_hash",
        source_hash(lines if not previous_summary else [previous_summary, *lines]),
    )
    call_count = int(highlights.get("call_count") or 0)
    insight_count = int(highlights.get("insight_count") or 0)
    checked_at = now or datetime.now(timezone.utc)

    if not lines and not previous_summary:
        return {"grain": grain, "grain_key": grain_key, "status": "empty", "skipped": True}
    if len(grain_key) > MAX_KEY_LEN:
        logger.error("period summary key too long grain=%s key=%s", grain, grain_key[:80])
        return {"grain": grain, "grain_key": grain_key[:MAX_KEY_LEN], "status": "error", "skipped": True}

    current = store.get_current(db, grain, grain_key, period_type, period_key)
    if current and not force and not lines and previous_summary:
        tracking = {
            "covered_through": (current.highlights_json or {}).get("covered_through"),
            "considered_insight_ids": (current.highlights_json or {}).get("considered_insight_ids") or [],
            "excluded_insights": highlights.get("excluded_insights")
            or (current.highlights_json or {}).get("excluded_insights")
            or [],
            "considered_child_ids": highlights.get("considered_child_ids")
            or (current.highlights_json or {}).get("considered_child_ids")
            or [],
            "excluded_child_ids": highlights.get("excluded_child_ids")
            or (current.highlights_json or {}).get("excluded_child_ids")
            or [],
            "summary_updated_at": (current.highlights_json or {}).get("summary_updated_at")
            or (current.generated_at.isoformat() if current.generated_at else None),
            "as_of": highlights.get("as_of"),
        }
        store.touch_tracking(db, current, tracking=tracking, now=checked_at)
        db.commit()
        return {"grain": grain, "grain_key": grain_key, "status": current.status, "skipped": True}

    if (
        current
        and not force
        and not previous_summary
        and (current.highlights_json or {}).get("source_hash") == highlights.get("source_hash")
    ):
        store.touch_tracking(
            db,
            current,
            tracking={
                "excluded_insights": highlights.get("excluded_insights") or [],
                "considered_insight_ids": (current.highlights_json or {}).get("considered_insight_ids") or [],
                "covered_through": (current.highlights_json or {}).get("covered_through"),
                "summary_updated_at": (current.highlights_json or {}).get("summary_updated_at")
                or (current.generated_at.isoformat() if current.generated_at else None),
                "as_of": highlights.get("as_of"),
            },
            now=checked_at,
        )
        db.commit()
        return {"grain": grain, "grain_key": grain_key, "status": current.status, "skipped": True}

    if budget is not None and not budget.allow():
        logger.warning("period summary cell cap reached grain=%s key=%s", grain, grain_key)
        return {"grain": grain, "grain_key": grain_key, "status": "capped", "skipped": True}

    # Compact findings already carry the UI narrative. Skip Vertex when we are not
    # incrementally merging into a previous LLM summary — avoids blanking the UI
    # when GCP_PROJECT_ID / Vertex is unavailable.
    needs_llm = bool(previous_summary and lines) or not highlights.get("findings")
    if not needs_llm:
        narrative = _empty_result("")
        status = "ok"
        error_message = None
    else:
        try:
            try:
                narrative = summarize(
                    lines,
                    grain=grain,
                    grain_label=grain_label,
                    previous_summary=previous_summary if previous_summary and lines else None,
                )
            except TypeError:
                narrative = summarize(lines, grain=grain, grain_label=grain_label)
            status = "ok"
            error_message = None
        except LLMError as exc:
            logger.exception("period summary failed grain=%s key=%s: %s", grain, grain_key, exc)
            if highlights.get("findings"):
                narrative = _empty_result("")
                status = "ok"
                error_message = None
                logger.warning(
                    "LLM failed but compact findings kept grain=%s key=%s",
                    grain,
                    grain_key,
                )
            else:
                narrative = _empty_result(f"Summary failed: {exc.message}")
                status = "error"
                error_message = exc.message
        except Exception as exc:
            logger.exception("period summary failed grain=%s key=%s", grain, grain_key)
            if highlights.get("findings"):
                narrative = _empty_result("")
                status = "ok"
                error_message = None
            else:
                narrative = _empty_result(str(exc))
                status = "error"
                error_message = str(exc)

    tokens = narrative.get("_tokens") or {}
    highlights["risks"] = narrative.get("risks") or []
    highlights["truncated"] = bool(narrative.get("_truncated") or highlights.get("truncated"))
    highlights.setdefault("site_visit_count", call_count)
    highlights.setdefault("user_issue_count", 0)
    highlights.setdefault("topics", [])
    if narrative.get("findings") and not highlights.get("findings"):
        highlights["findings"] = narrative.get("findings")
    summary_text = compact.format_findings(highlights.get("findings") or []) or compact.topic_sentences(
        highlights.get("topics") or []
    ) or str(narrative.get("summary") or "").strip()
    if status == "ok" and (not summary_text or summary_text.lower().startswith("no insights")):
        return {"grain": grain, "grain_key": grain_key, "status": "empty", "skipped": True}

    highlights["summary_updated_at"] = checked_at.isoformat()
    highlights["tracking_checked_at"] = checked_at.isoformat()

    try:
        row, skipped = store.persist(
            db,
            grain=grain,
            grain_key=grain_key,
            grain_label=grain_label,
            parent_key=parent_key,
            period_type=period_type,
            period_key=period_key,
            period_start=period_start,
            period_end=period_end,
            summary_text=summary_text,
            highlights=highlights,
            source_kind=source_kind,
            source_count=len(lines) if lines else int(highlights.get("source_count") or 0),
            call_count=call_count,
            insight_count=insight_count,
            status=status,
            model_name=settings.GEMINI_MODEL,
            prompt_tokens=int(tokens.get("input") or 0),
            output_tokens=int(tokens.get("output") or 0),
            error_message=error_message,
            force=force,
            now=checked_at,
        )
        db.commit()
        return {"grain": grain, "grain_key": grain_key, "status": row.status, "skipped": skipped}
    except Exception as exc:
        logger.exception("period summary persist failed grain=%s key=%s", grain, grain_key)
        try:
            db.rollback()
        except Exception:
            logger.exception("period summary rollback failed")
        return {"grain": grain, "grain_key": grain_key, "status": "error", "skipped": False, "error": str(exc)}


def _summarize_from_insights(
    db: Session,
    *,
    grain: str,
    grain_key: str,
    parent_key: Optional[str],
    period_key: str,
    start: date,
    end: date,
    force: bool,
    gather: GatherFn,
    summarize: SummarizeFn,
    grain_label: Optional[str] = None,
    budget: Optional[CellBudget] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    from services.period_summarize import incremental as inc

    checked_at = now or datetime.now(timezone.utc)
    as_of = inc.as_of_date(checked_at)
    try:
        rows = gather(db, start=start, end=end, grain=grain, grain_key=grain_key)
    except Exception as exc:
        logger.exception("period gather failed grain=%s key=%s", grain, grain_key)
        return {"grain": grain, "grain_key": grain_key, "status": "error", "skipped": False, "error": str(exc)}

    current = store.get_current(db, grain, grain_key, "month", period_key)
    previous_ids = list((current.highlights_json or {}).get("considered_insight_ids") or []) if current else []
    covered_through = (
        inc.parse_covered_through((current.highlights_json or {}).get("covered_through")) if current else None
    )
    if force:
        covered_through = None
        previous_ids = []

    new_rows, open_rows, empty_rows = inc.partition_insights(
        rows,
        covered_through=covered_through,
        as_of=as_of,
        force=force,
    )
    source_rows = new_rows
    if current and not force and not source_rows:
        previous_summary = current.summary_text
        lines: list[str] = []
        highlights = dict(current.highlights_json or {})
    else:
        previous_summary = current.summary_text if (current and not force and source_rows) else None
        lines, highlights = lines_from_insights(source_rows) if source_rows else ([], {"call_count": 0, "insight_count": 0})

    tracking = inc.tracking_for_insights(
        previous_ids=[] if force or not current else previous_ids,
        new_rows=source_rows,
        open_rows=open_rows,
        empty_rows=empty_rows,
        all_rows=rows,
        covered_through=None if force else covered_through,
        as_of=as_of,
        checked_at=checked_at,
        summary_updated_at=(
            None
            if (force or source_rows or not current)
            else (
                (current.highlights_json or {}).get("summary_updated_at")
                or (current.generated_at.isoformat() if current.generated_at else None)
            )
        ),
    )
    if force or not current:
        tracking["considered_insight_ids"] = [
            row_id for row_id in (inc.insight_id(row) for row in source_rows) if row_id
        ]
        latest = inc.covered_through_from_rows(source_rows)
        tracking["covered_through"] = latest.isoformat() if latest else None
    elif source_rows:
        latest = covered_through
        for row in source_rows:
            call_day = inc.row_call_date(row)
            if call_day and (latest is None or call_day > latest):
                latest = call_day
        tracking["covered_through"] = latest.isoformat() if latest else None
        tracking["considered_insight_ids"] = list(
            dict.fromkeys([*previous_ids, *(inc.insight_id(row) for row in source_rows if inc.insight_id(row))])
        )

    highlights.update(tracking)
    if source_rows:
        hash_lines = [*( [current.summary_text] if current and not force and current.summary_text else [] ), *lines]
        highlights["source_hash"] = source_hash(hash_lines)

    return _write_node(
        db,
        grain=grain,
        grain_key=grain_key,
        grain_label=grain_label or display_key(grain_key) or grain_key,
        parent_key=parent_key,
        period_type="month",
        period_key=period_key,
        period_start=start,
        period_end=end,
        lines=lines,
        highlights=highlights,
        source_kind="insights",
        force=force,
        summarize=summarize,
        budget=budget,
        previous_summary=previous_summary,
        now=checked_at,
    )


def _label_for_child_grain(grain: str, grain_key: str, children: list[dict[str, Any]]) -> str:
    child_label = next((child.get("grain_label") for child in children if child.get("grain_label")), None)
    if grain in {"tag", "product"} or grain.endswith("_t") or grain.endswith("_p") or grain.endswith("_pt"):
        return str(child_label or display_key(grain_key) or grain_key)
    return display_key(grain_key) or grain_key


def _summarize_from_children(
    db: Session,
    *,
    grain: str,
    grain_key: str,
    parent_key: Optional[str],
    period_type: str,
    period_key: str,
    start: date,
    end: date,
    force: bool,
    summarize: SummarizeFn,
    child_period_type: str | None = None,
    child_period_keys: list[str] | None = None,
    budget: Optional[CellBudget] = None,
    now: Optional[datetime] = None,
    children_override: Optional[list[dict[str, Any]]] = None,
    grain_label: Optional[str] = None,
) -> dict[str, Any]:
    from services.period_summarize import incremental as inc

    checked_at = now or datetime.now(timezone.utc)
    try:
        children = (
            children_override
            if children_override is not None
            else combine.children_for(
                db,
                grain=grain,
                grain_key=grain_key,
                period_type=period_type,
                period_key=period_key,
                child_period_type=child_period_type,
                child_period_keys=child_period_keys,
            )
        )
    except Exception as exc:
        logger.exception("period children failed grain=%s key=%s", grain, grain_key)
        return {"grain": grain, "grain_key": grain_key, "status": "error", "skipped": False, "error": str(exc)}

    if children_override is not None and not children:
        return {"grain": grain, "grain_key": grain_key, "status": "skipped", "skipped": True}

    current = store.get_current(db, grain, grain_key, period_type, period_key)
    previous_child_ids = list((current.highlights_json or {}).get("considered_child_ids") or []) if current else []
    previous_set = set(previous_child_ids)

    changed_children: list[dict[str, Any]] = []
    for child in children:
        child_id = str(child.get("id") or "")
        if force or not current or not child_id or child_id not in previous_set:
            changed_children.append(child)
            continue
        child_generated = str(child.get("generated_at") or "")
        parent_updated = str((current.highlights_json or {}).get("summary_updated_at") or "")
        if child_generated and parent_updated and child_generated > parent_updated:
            changed_children.append(child)

    if current and not force and not changed_children:
        highlights = dict(current.highlights_json or {})
        highlights["considered_child_ids"] = previous_child_ids
        highlights["excluded_child_ids"] = []
        highlights["summary_updated_at"] = (
            (current.highlights_json or {}).get("summary_updated_at")
            or (current.generated_at.isoformat() if current.generated_at else None)
        )
        highlights["as_of"] = inc.as_of_date(checked_at).isoformat()
        return _write_node(
            db,
            grain=grain,
            grain_key=grain_key,
            grain_label=grain_label or current.grain_label or display_key(grain_key) or grain_key,
            parent_key=parent_key,
            period_type=period_type,
            period_key=period_key,
            period_start=start,
            period_end=end,
            lines=[],
            highlights=highlights,
            source_kind="child_summaries",
            force=force,
            summarize=summarize,
            budget=budget,
            previous_summary=current.summary_text,
            now=checked_at,
        )

    source_children = children if (force or not current) else changed_children
    lines, highlights = combine.combine_payload(source_children)
    if child_period_keys:
        highlights.update(combine.coverage(children, expected_keys=child_period_keys))
    considered_ids = list(
        dict.fromkeys(
            [
                *([] if force or not current else previous_child_ids),
                *[str(child.get("id")) for child in source_children if child.get("id")],
            ]
        )
    )
    highlights["considered_child_ids"] = considered_ids
    highlights["excluded_child_ids"] = [
        {"id": str(child.get("id")), "reason": "not_yet_run"}
        for child in children
        if child.get("id") and str(child.get("id")) not in set(considered_ids)
    ]
    highlights["as_of"] = inc.as_of_date(checked_at).isoformat()
    grain_label = grain_label or _label_for_child_grain(grain, grain_key, children)
    previous_summary = current.summary_text if (current and not force and changed_children) else None
    return _write_node(
        db,
        grain=grain,
        grain_key=grain_key,
        grain_label=grain_label,
        parent_key=parent_key,
        period_type=period_type,
        period_key=period_key,
        period_start=start,
        period_end=end,
        lines=lines,
        highlights=highlights,
        source_kind="child_summaries",
        force=force,
        summarize=summarize,
        budget=budget,
        previous_summary=previous_summary,
        now=checked_at,
    )



def _rollup_family(
    db: Session,
    *,
    child_grain: str,
    parent_grain: str,
    nodes: list[dict[str, Optional[str]]],
    period_key: str,
    start: date,
    end: date,
    force: bool,
    summarize: SummarizeFn,
    budget: CellBudget,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        children = store.list_current(db, grain=child_grain, period_type="month", period_key=period_key)
    except Exception:
        logger.exception("list children failed grain=%s", child_grain)
        return results
    for child in children:
        parent = child.parent_key
        if not parent or parent in seen:
            continue
        seen.add(parent)
        geo = display_key(parent)
        if parent_grain in {"zone_t", "zone_p", "zone_pt"}:
            parent_of_parent = _nation_key(parent_grain, parent)
        else:
            grand_geo = _lookup_parent_geo(parent_grain, geo, nodes)
            parent_of_parent = with_geo(grand_geo, parent) if grand_geo else None
        results.append(
            _summarize_from_children(
                db,
                grain=parent_grain,
                grain_key=parent,
                parent_key=parent_of_parent,
                period_type="month",
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                summarize=summarize,
                budget=budget,
            )
        )
    return results


def _run_mixed_geo(
    db: Session,
    *,
    nodes: list[dict[str, Optional[str]]],
    token: Optional[str],
    period_key: str,
    start: date,
    end: date,
    force: bool,
    gather: GatherFn,
    summarize: SummarizeFn,
    budget: CellBudget,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node in _nodes_for_grain(nodes, "bde"):
        geo = str(node["bde_key"])
        results.append(
            _summarize_from_insights(
                db,
                grain="bde",
                grain_key=mixed_key(geo, token),
                grain_label=geo,
                parent_key=mixed_key(str(node["rfmm_key"]), token) if node.get("rfmm_key") else None,
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                gather=gather,
                summarize=summarize,
                budget=budget,
            )
        )
    for grain in ("rfmm", "zone", "division"):
        for node in _nodes_for_grain(nodes, grain):
            geo = str(node[_GEO_FIELD[grain]])
            parent_geo = _parent_identity(grain, node)
            results.append(
                _summarize_from_children(
                    db,
                    grain=grain,
                    grain_key=mixed_key(geo, token),
                    parent_key=mixed_key(parent_geo, token) if parent_geo else None,
                    period_type="month",
                    period_key=period_key,
                    start=start,
                    end=end,
                    force=force,
                    summarize=summarize,
                    budget=budget,
                )
            )
    return results


def _run_nationwide(
    db: Session,
    *,
    token: Optional[str],
    products: list[str],
    tags: list[dict[str, str]],
    period_key: str,
    start: date,
    end: date,
    force: bool,
    gather: GatherFn,
    summarize: SummarizeFn,
    budget: CellBudget,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for product_name in products:
        results.append(
            _summarize_from_insights(
                db,
                grain="product",
                grain_key=scoped_key(product_name, token) if token else product_name,
                grain_label=product_name,
                parent_key=None,
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                gather=gather,
                summarize=summarize,
                budget=budget,
            )
        )
    for tag in tags:
        tag_id = str(tag["grain_key"])
        label = tag.get("grain_label") or tag_id
        results.append(
            _summarize_from_insights(
                db,
                grain="tag",
                grain_key=scoped_key(tag_id, token) if token else tag_id,
                grain_label=label,
                parent_key=None,
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                gather=gather,
                summarize=summarize,
                budget=budget,
            )
        )
    return results


def _nation_key(zone_grain: str, zone_key: str) -> Optional[str]:
    """Zone slice key → the all-level key that slice rolls up into."""
    parts = split_key(zone_key)
    if len(parts) < 2:
        return None
    token = parts[1] if parts[1] in GROUP_TOKENS else None
    if zone_grain == "zone_t":
        tag_id = parts[-1]
        return scoped_key(tag_id, token) if token else tag_id
    if zone_grain == "zone_p":
        product = "::".join(parts[2:]) if token else "::".join(parts[1:])
        if not product:
            return None
        return scoped_key(product, token) if token else product
    if zone_grain == "zone_pt":
        if token:
            if len(parts) < 4:
                return None
            product = "::".join(parts[2:-1])
            tag_id = parts[-1]
            return scoped_key("ALL", token, product, tag_id)
        if len(parts) < 3:
            return None
        product = "::".join(parts[1:-1])
        tag_id = parts[-1]
        return scoped_key("ALL", product, tag_id)
    return None


def _stored_children(
    db: Session,
    *,
    grain: str,
    grain_keys: list[str],
    period_key: str,
) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for grain_key in grain_keys:
        row = store.get_current(db, grain, grain_key, "month", period_key)
        if not store.is_visible_summary(row):
            continue
        payload = store.serialize_row(row)
        if payload:
            children.append(payload)
    return children


def _aggregate_slices(
    db: Session,
    *,
    grain: str,
    slices: dict[str, dict[str, Any]],
    source_grain: str,
    period_key: str,
    start: date,
    end: date,
    force: bool,
    summarize: SummarizeFn,
    budget: CellBudget,
    parent_for,
) -> list[dict[str, Any]]:
    """Build one summary per product or level-3 tag from stored cube rows."""
    results: list[dict[str, Any]] = []
    for grain_key, spec in slices.items():
        children = _stored_children(
            db, grain=source_grain, grain_keys=list(spec["children"]), period_key=period_key,
        )
        if not children:
            continue
        results.append(
            _summarize_from_children(
                db,
                grain=grain,
                grain_key=grain_key,
                parent_key=parent_for(grain_key, spec),
                period_type="month",
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                summarize=summarize,
                budget=budget,
                children_override=children,
                grain_label=str(spec.get("label") or grain_key),
            )
        )
    return results


def _run_cube_and_slices(
    db: Session,
    *,
    nodes: list[dict[str, Optional[str]]],
    token: Optional[str],
    cells: list[dict[str, Optional[str]]],
    period_key: str,
    start: date,
    end: date,
    force: bool,
    gather: GatherFn,
    summarize: SummarizeFn,
    budget: CellBudget,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cube_seen: set[str] = set()
    product_seen: set[str] = set()
    tag_seen: set[str] = set()
    product_slices: dict[str, dict[str, Any]] = {}
    tag_slices: dict[str, dict[str, Any]] = {}
    for cell in cells:
        # Presented summaries start at the cluster, from the audios in that cluster.
        rfmm = cell.get("rfmm_key")
        if not rfmm:
            continue
        tag_id = cell.get("tag_id")
        tag_name = cell.get("tag_name") or tag_id
        product = cell.get("product_name")
        zone = cell.get("zone_key")
        if product and tag_id:
            # Product and tag narratives are aggregated from this cube after the loop.
            pass
        elif tag_id:
            tag_key = scoped_key(rfmm, token, tag_id) if token else scoped_key(rfmm, tag_id)
            if tag_key not in tag_seen:
                tag_seen.add(tag_key)
                results.append(
                    _summarize_from_insights(
                        db,
                        grain="rfmm_t",
                        grain_key=tag_key,
                        grain_label=str(tag_name or tag_id),
                        parent_key=with_geo(zone, tag_key) if zone else None,
                        period_key=period_key,
                        start=start,
                        end=end,
                        force=force,
                        gather=gather,
                        summarize=summarize,
                        budget=budget,
                    )
                )
        elif product:
            product_key = scoped_key(rfmm, token, product) if token else scoped_key(rfmm, product)
            if product_key not in product_seen:
                product_seen.add(product_key)
                results.append(
                    _summarize_from_insights(
                        db,
                        grain="rfmm_p",
                        grain_key=product_key,
                        grain_label=product,
                        parent_key=with_geo(zone, product_key) if zone else None,
                        period_key=period_key,
                        start=start,
                        end=end,
                        force=force,
                        gather=gather,
                        summarize=summarize,
                        budget=budget,
                    )
                )
        if product and tag_id:
            cube_key = scoped_key(rfmm, token, product, tag_id) if token else scoped_key(rfmm, product, tag_id)
            if cube_key not in cube_seen:
                cube_seen.add(cube_key)
                results.append(
                    _summarize_from_insights(
                        db,
                        grain="rfmm_pt",
                        grain_key=cube_key,
                        grain_label=f"{product} × {tag_name}",
                        parent_key=with_geo(zone, cube_key) if zone else None,
                        period_key=period_key,
                        start=start,
                        end=end,
                        force=force,
                        gather=gather,
                        summarize=summarize,
                        budget=budget,
                    )
                )
                product_key = scoped_key(rfmm, token, product) if token else scoped_key(rfmm, product)
                tag_key = scoped_key(rfmm, token, tag_id) if token else scoped_key(rfmm, tag_id)
                product_spec = product_slices.setdefault(
                    product_key, {"label": product, "zone": zone, "children": []},
                )
                if cube_key not in product_spec["children"]:
                    product_spec["children"].append(cube_key)
                tag_spec = tag_slices.setdefault(
                    tag_key, {"label": str(tag_name or tag_id), "zone": zone, "children": []},
                )
                if cube_key not in tag_spec["children"]:
                    tag_spec["children"].append(cube_key)
    results.extend(
        _aggregate_slices(
            db,
            grain="rfmm_p",
            slices=product_slices,
            source_grain="rfmm_pt",
            period_key=period_key,
            start=start,
            end=end,
            force=force,
            summarize=summarize,
            budget=budget,
            parent_for=lambda grain_key, spec: with_geo(spec.get("zone"), grain_key) if spec.get("zone") else None,
        )
    )
    results.extend(
        _aggregate_slices(
            db,
            grain="rfmm_t",
            slices=tag_slices,
            source_grain="rfmm_pt",
            period_key=period_key,
            start=start,
            end=end,
            force=force,
            summarize=summarize,
            budget=budget,
            parent_for=lambda grain_key, spec: with_geo(spec.get("zone"), grain_key) if spec.get("zone") else None,
        )
    )
    for child_grain, parent_grain in (
        ("rfmm_t", "zone_t"),
        ("zone_t", "tag"),
        ("rfmm_p", "zone_p"),
        ("zone_p", "product"),
        ("rfmm_pt", "zone_pt"),
        ("zone_pt", "all_pt"),
    ):
        results.extend(
            _rollup_family(
                db,
                child_grain=child_grain,
                parent_grain=parent_grain,
                nodes=nodes,
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                summarize=summarize,
                budget=budget,
            )
        )
    results.extend(
        _run_unclustered_slices(
            db,
            token=token,
            cells=cells,
            period_key=period_key,
            start=start,
            end=end,
            force=force,
            gather=gather,
            summarize=summarize,
            budget=budget,
            already=results,
        )
    )
    return results


def _run_unclustered_slices(
    db: Session,
    *,
    token: Optional[str],
    cells: list[dict[str, Optional[str]]],
    period_key: str,
    start: date,
    end: date,
    force: bool,
    gather: GatherFn,
    summarize: SummarizeFn,
    budget: CellBudget,
    already: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Audios with no RFMM cluster still get an all-level product × tag summary."""
    written = {(item.get("grain"), item.get("grain_key")) for item in already}
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    product_slices: dict[str, dict[str, Any]] = {}
    tag_slices: dict[str, dict[str, Any]] = {}

    def write(grain: str, grain_key: str, grain_label: str) -> None:
        marker = (grain, grain_key)
        if marker in written or marker in seen:
            return
        seen.add(marker)
        results.append(
            _summarize_from_insights(
                db,
                grain=grain,
                grain_key=grain_key,
                grain_label=grain_label,
                parent_key=None,
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                gather=gather,
                summarize=summarize,
                budget=budget,
            )
        )

    for cell in cells:
        if cell.get("rfmm_key"):
            continue
        tag_id = cell.get("tag_id")
        tag_name = str(cell.get("tag_name") or tag_id or "")
        product = cell.get("product_name")
        if product and tag_id:
            cube_key = (
                scoped_key("ALL", token, product, str(tag_id))
                if token
                else scoped_key("ALL", product, str(tag_id))
            )
            write("all_pt", cube_key, f"{product} × {tag_name}")
            product_key = scoped_key(product, token) if token else product
            tag_key = scoped_key(str(tag_id), token) if token else str(tag_id)
            if ("product", product_key) not in written:
                spec = product_slices.setdefault(product_key, {"label": product, "children": []})
                if cube_key not in spec["children"]:
                    spec["children"].append(cube_key)
            if ("tag", tag_key) not in written:
                spec = tag_slices.setdefault(tag_key, {"label": tag_name or str(tag_id), "children": []})
                if cube_key not in spec["children"]:
                    spec["children"].append(cube_key)
            continue
        if tag_id:
            key = scoped_key(str(tag_id), token) if token else str(tag_id)
            write("tag", key, tag_name or str(tag_id))
        elif product:
            key = scoped_key(product, token) if token else product
            write("product", key, product)
    results.extend(
        _aggregate_slices(
            db,
            grain="product",
            slices=product_slices,
            source_grain="all_pt",
            period_key=period_key,
            start=start,
            end=end,
            force=force,
            summarize=summarize,
            budget=budget,
            parent_for=lambda _grain_key, _spec: None,
        )
    )
    results.extend(
        _aggregate_slices(
            db,
            grain="tag",
            slices=tag_slices,
            source_grain="all_pt",
            period_key=period_key,
            start=start,
            end=end,
            force=force,
            summarize=summarize,
            budget=budget,
            parent_for=lambda _grain_key, _spec: None,
        )
    )
    return results


def run_month(
    db: Session,
    period_key: str,
    *,
    force: bool = False,
    summarize: SummarizeFn = summarize_lines,
    gather: GatherFn = compact.gather_insights,
    list_nodes: ListNodesFn = compact.list_hierarchy_nodes,
    list_products: ListProductsFn = compact.list_product_keys,
    list_tags: ListTagsFn = compact.list_tag_keys,
    list_groups: ListGroupsFn = compact.list_groups,
    list_cube: ListCubeFn = compact.list_cube_keys,
    max_cells: int = MAX_MONTH_CELLS,
) -> list[dict[str, Any]]:
    start, end = bounds_for("month", period_key)
    budget = CellBudget(max_cells)
    results: list[dict[str, Any]] = []
    logger.info(
        "period summary run %s concurrent=%s per_minute=%s min_interval=%.2fs cells=%s",
        period_key,
        settings.PERIOD_SUMMARY_MAX_CONCURRENT,
        settings.PERIOD_SUMMARY_MAX_PER_MINUTE,
        settings.PERIOD_SUMMARY_MIN_INTERVAL_SECONDS,
        max_cells,
    )
    try:
        groups = _call_list(list_groups, db, start, end) or [None]
    except Exception:
        logger.exception("list_groups failed for %s", period_key)
        db.rollback()
        groups = [None]
    if not groups:
        groups = [None]

    for group in groups:
        token = group_token(group) if group else None
        try:
            nodes = _call_list(list_nodes, db, start, end, group)
        except Exception:
            logger.exception("list_nodes failed group=%s", group)
            db.rollback()
            nodes = []
        try:
            cells = _call_list(list_cube, db, start, end, group)
        except Exception:
            logger.exception("list_cube failed group=%s", group)
            db.rollback()
            cells = []
        results.extend(
            _run_mixed_geo(
                db,
                nodes=nodes,
                token=token,
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                gather=gather,
                summarize=summarize,
                budget=budget,
            )
        )
        results.extend(
            _run_cube_and_slices(
                db,
                nodes=nodes,
                token=token,
                cells=cells,
                period_key=period_key,
                start=start,
                end=end,
                force=force,
                gather=gather,
                summarize=summarize,
                budget=budget,
            )
        )
    try:
        db.commit()
    except Exception:
        logger.exception("period month commit failed")
        db.rollback()
    return results


def _unique_keys(db: Session, grain: str, period_type: str, period_keys: list[str]) -> list[tuple[str, Optional[str]]]:
    seen: set[tuple[str, Optional[str]]] = set()
    out: list[tuple[str, Optional[str]]] = []
    for key in period_keys:
        try:
            rows = store.list_current(db, grain=grain, period_type=period_type, period_key=key)
        except Exception:
            logger.exception("list_current failed grain=%s period=%s", grain, key)
            continue
        for row in rows:
            item = (row.grain_key, row.parent_key)
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
    return out


def roll_quarter(db: Session, quarter_key: str, *, force: bool, summarize: SummarizeFn) -> list[dict[str, Any]]:
    start, end = bounds_for("quarter", quarter_key)
    month_keys = child_month_keys(quarter_key)
    results: list[dict[str, Any]] = []
    budget = CellBudget(MAX_MONTH_CELLS)
    for grain in TIME_ROLLUP_GRAINS:
        for grain_key, parent_key in _unique_keys(db, grain, "month", month_keys):
            results.append(
                _summarize_from_children(
                    db,
                    grain=grain,
                    grain_key=grain_key,
                    parent_key=parent_key,
                    period_type="quarter",
                    period_key=quarter_key,
                    start=start,
                    end=end,
                    force=force,
                    summarize=summarize,
                    child_period_type="month",
                    child_period_keys=month_keys,
                    budget=budget,
                )
            )
    try:
        db.commit()
    except Exception:
        logger.exception("quarter commit failed")
        db.rollback()
    return results


def roll_year(db: Session, year_key: str, *, force: bool, summarize: SummarizeFn) -> list[dict[str, Any]]:
    start, end = bounds_for("year", year_key)
    quarter_keys = child_quarter_keys(year_key)
    results: list[dict[str, Any]] = []
    budget = CellBudget(MAX_MONTH_CELLS)
    for grain in TIME_ROLLUP_GRAINS:
        for grain_key, parent_key in _unique_keys(db, grain, "quarter", quarter_keys):
            results.append(
                _summarize_from_children(
                    db,
                    grain=grain,
                    grain_key=grain_key,
                    parent_key=parent_key,
                    period_type="year",
                    period_key=year_key,
                    start=start,
                    end=end,
                    force=force,
                    summarize=summarize,
                    child_period_type="quarter",
                    child_period_keys=quarter_keys,
                    budget=budget,
                )
            )
    try:
        db.commit()
    except Exception:
        logger.exception("year commit failed")
        db.rollback()
    return results


def run(
    db: Session,
    *,
    period_type: Optional[str] = None,
    period_key: Optional[str] = None,
    force: bool = False,
    now: Optional[datetime] = None,
    summarize: SummarizeFn = summarize_lines,
    gather: GatherFn = compact.gather_insights,
    list_nodes: ListNodesFn = compact.list_hierarchy_nodes,
    list_products: ListProductsFn = compact.list_product_keys,
    list_tags: ListTagsFn = compact.list_tag_keys,
    list_groups: ListGroupsFn = compact.list_groups,
    list_cube: ListCubeFn = compact.list_cube_keys,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    closed: list[str] = []

    def _month(key: str) -> None:
        results.extend(
            run_month(
                db,
                key,
                force=force,
                summarize=summarize,
                gather=gather,
                list_nodes=list_nodes,
                list_products=list_products,
                list_tags=list_tags,
                list_groups=list_groups,
                list_cube=list_cube,
            )
        )
        if is_last_month_of_quarter(key):
            q_key = quarter_key_from_month(key)
            results.extend(roll_quarter(db, q_key, force=force, summarize=summarize))
            closed.append(q_key)
        if is_last_month_of_year(key):
            y_key = year_key_from_month(key)
            results.extend(roll_year(db, y_key, force=force, summarize=summarize))
            closed.append(y_key)

    if period_type == "quarter" and period_key:
        results.extend(roll_quarter(db, period_key, force=force, summarize=summarize))
    elif period_type == "year" and period_key:
        results.extend(roll_year(db, period_key, force=force, summarize=summarize))
    elif period_type == "month" and period_key:
        _month(period_key)
    else:
        month_key = period_key or current_month_key(current)
        _month(month_key)
        today = utc_today(current)
        if today.day <= 2:
            from services.period_summarize.period_keys import previous_month_key

            prev = previous_month_key(month_key)
            _month(prev)

    skipped = sum(1 for item in results if item.get("skipped"))
    errors = sum(1 for item in results if item.get("status") == "error")
    capped = sum(1 for item in results if item.get("status") == "capped")
    return {
        "nodes": len(results),
        "skipped": skipped,
        "errors": errors,
        "capped": capped,
        "closed_periods": closed,
        "results": results,
    }
