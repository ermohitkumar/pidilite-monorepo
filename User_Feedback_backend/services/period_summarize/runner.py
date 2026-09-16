"""Ordered period-summary job: mixed geo, nationwide, cube/slices, then time rollups."""
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
    is_last_month_of_quarter,
    is_last_month_of_year,
    mixed_key,
    quarter_key_from_month,
    scoped_key,
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
) -> dict[str, Any]:
    highlights = dict(highlights)
    highlights.setdefault("source_hash", source_hash(lines))
    call_count = int(highlights.get("call_count") or 0)
    insight_count = int(highlights.get("insight_count") or 0)

    if not lines:
        return {"grain": grain, "grain_key": grain_key, "status": "empty", "skipped": True}
    if len(grain_key) > MAX_KEY_LEN:
        logger.error("period summary key too long grain=%s key=%s", grain, grain_key[:80])
        return {"grain": grain, "grain_key": grain_key[:MAX_KEY_LEN], "status": "error", "skipped": True}

    current = store.get_current(db, grain, grain_key, period_type, period_key)
    if (
        current
        and not force
        and (current.highlights_json or {}).get("source_hash") == highlights.get("source_hash")
    ):
        return {"grain": grain, "grain_key": grain_key, "status": current.status, "skipped": True}

    if budget is not None and not budget.allow():
        logger.warning("period summary cell cap reached grain=%s key=%s", grain, grain_key)
        return {"grain": grain, "grain_key": grain_key, "status": "capped", "skipped": True}

    try:
        narrative = summarize(lines, grain=grain, grain_label=grain_label)
        status = "ok"
        error_message = None
    except LLMError as exc:
        logger.exception("period summary failed grain=%s key=%s: %s", grain, grain_key, exc)
        narrative = _empty_result(f"Summary failed: {exc.message}")
        status = "error"
        error_message = exc.message
    except Exception as exc:
        logger.exception("period summary failed grain=%s key=%s", grain, grain_key)
        narrative = _empty_result(str(exc))
        status = "error"
        error_message = str(exc)

    tokens = narrative.get("_tokens") or {}
    highlights["themes"] = narrative.get("themes") or []
    highlights["products"] = narrative.get("products") or highlights.get("products") or []
    highlights["risks"] = narrative.get("risks") or []
    highlights["truncated"] = bool(narrative.get("_truncated") or highlights.get("truncated"))
    summary_text = str(narrative.get("summary") or "").strip()
    if status == "ok" and (not summary_text or summary_text.lower().startswith("no insights")):
        return {"grain": grain, "grain_key": grain_key, "status": "empty", "skipped": True}

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
            source_count=len(lines),
            call_count=call_count,
            insight_count=insight_count,
            status=status,
            model_name=settings.GEMINI_MODEL,
            prompt_tokens=int(tokens.get("input") or 0),
            output_tokens=int(tokens.get("output") or 0),
            error_message=error_message,
            force=force,
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
) -> dict[str, Any]:
    try:
        rows = gather(db, start=start, end=end, grain=grain, grain_key=grain_key)
    except Exception as exc:
        logger.exception("period gather failed grain=%s key=%s", grain, grain_key)
        return {"grain": grain, "grain_key": grain_key, "status": "error", "skipped": False, "error": str(exc)}
    lines, highlights = lines_from_insights(rows)
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
) -> dict[str, Any]:
    try:
        children = combine.children_for(
            db,
            grain=grain,
            grain_key=grain_key,
            period_type=period_type,
            period_key=period_key,
            child_period_type=child_period_type,
            child_period_keys=child_period_keys,
        )
    except Exception as exc:
        logger.exception("period children failed grain=%s key=%s", grain, grain_key)
        return {"grain": grain, "grain_key": grain_key, "status": "error", "skipped": False, "error": str(exc)}
    lines, highlights = combine.combine_payload(children)
    if child_period_keys:
        highlights.update(combine.coverage(children, expected_keys=child_period_keys))
    grain_label = _label_for_child_grain(grain, grain_key, children)
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
    for cell in cells:
        bde = cell.get("bde_key")
        if not bde:
            continue
        tag_id = cell.get("tag_id")
        tag_name = cell.get("tag_name") or tag_id
        product = cell.get("product_name")
        rfmm = cell.get("rfmm_key")
        if tag_id:
            tag_key = scoped_key(bde, token, tag_id) if token else scoped_key(bde, tag_id)
            if tag_key not in tag_seen:
                tag_seen.add(tag_key)
                results.append(
                    _summarize_from_insights(
                        db,
                        grain="bde_t",
                        grain_key=tag_key,
                        grain_label=str(tag_name or tag_id),
                        parent_key=with_geo(rfmm, tag_key) if rfmm else None,
                        period_key=period_key,
                        start=start,
                        end=end,
                        force=force,
                        gather=gather,
                        summarize=summarize,
                        budget=budget,
                    )
                )
        if product:
            product_key = scoped_key(bde, token, product) if token else scoped_key(bde, product)
            if product_key not in product_seen:
                product_seen.add(product_key)
                results.append(
                    _summarize_from_insights(
                        db,
                        grain="bde_p",
                        grain_key=product_key,
                        grain_label=product,
                        parent_key=with_geo(rfmm, product_key) if rfmm else None,
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
            cube_key = scoped_key(bde, token, product, tag_id) if token else scoped_key(bde, product, tag_id)
            if cube_key not in cube_seen:
                cube_seen.add(cube_key)
                results.append(
                    _summarize_from_insights(
                        db,
                        grain="bde_pt",
                        grain_key=cube_key,
                        grain_label=f"{product} × {tag_name}",
                        parent_key=with_geo(rfmm, cube_key) if rfmm else None,
                        period_key=period_key,
                        start=start,
                        end=end,
                        force=force,
                        gather=gather,
                        summarize=summarize,
                        budget=budget,
                    )
                )
    for child_grain, parent_grain in (
        ("bde_t", "rfmm_t"),
        ("rfmm_t", "zone_t"),
        ("zone_t", "div_t"),
        ("bde_p", "rfmm_p"),
        ("rfmm_p", "zone_p"),
        ("zone_p", "div_p"),
        ("bde_pt", "rfmm_pt"),
        ("rfmm_pt", "zone_pt"),
        ("zone_pt", "div_pt"),
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
    try:
        groups = _call_list(list_groups, db, start, end) or [None]
    except Exception:
        logger.exception("list_groups failed for %s", period_key)
        groups = [None]
    if not groups:
        groups = [None]

    for group in groups:
        token = group_token(group) if group else None
        try:
            nodes = _call_list(list_nodes, db, start, end, group)
        except Exception:
            logger.exception("list_nodes failed group=%s", group)
            nodes = []
        try:
            products = _call_list(list_products, db, start, end, group)
        except Exception:
            logger.exception("list_products failed group=%s", group)
            products = []
        try:
            tags = _call_list(list_tags, db, start, end, group)
        except Exception:
            logger.exception("list_tags failed group=%s", group)
            tags = []
        try:
            cells = _call_list(list_cube, db, start, end, group)
        except Exception:
            logger.exception("list_cube failed group=%s", group)
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
            _run_nationwide(
                db,
                token=token,
                products=products,
                tags=tags,
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
