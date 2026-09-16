"""Combine stored child summaries into RFMM / Zone / Division / quarter / year / tag time rollups."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from services.period_summarize import store
from services.period_summarize.compact import child_source_lines, source_hash
from services.period_summarize.period_keys import CHILD_GRAIN


def children_for(
    db: Session,
    *,
    grain: str,
    grain_key: str,
    period_type: str,
    period_key: str,
    child_period_type: str | None = None,
    child_period_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load current child rows. Time rollups pass child_period_keys of the same grain."""
    if child_period_keys:
        rows = []
        for key in child_period_keys:
            row = store.get_current(db, grain, grain_key, child_period_type or period_type, key)
            if row:
                rows.append(row)
        return [store.serialize_row(row) for row in rows if store.is_visible_summary(row)]

    child_grain = CHILD_GRAIN.get(grain)
    if not child_grain:
        return []
    rows = store.list_children(
        db,
        child_grain=child_grain,
        parent_key=grain_key,
        period_type=period_type,
        period_key=period_key,
    )
    return [store.serialize_row(row) for row in rows if store.is_visible_summary(row)]


def coverage(children: list[dict[str, Any]], expected_keys: list[str] | None = None) -> dict[str, Any]:
    present = [child.get("grain_key") for child in children if child.get("status") == "ok"]
    missing = []
    errored = [child.get("grain_key") for child in children if child.get("status") == "error"]
    if expected_keys:
        have = {child.get("grain_key") or child.get("period_key") for child in children}
        # For time rollups expected keys are period keys stored on the child row.
        have_periods = {child.get("period_key") for child in children}
        missing = [key for key in expected_keys if key not in have and key not in have_periods]
    return {
        "child_count": len(children),
        "ok_count": len(present),
        "missing": missing,
        "errored": [key for key in errored if key],
    }


def combine_payload(children: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    lines, truncated = child_source_lines(children)
    highlights = coverage(children)
    highlights["truncated"] = truncated
    highlights["source_hash"] = source_hash(lines)
    highlights["call_count"] = sum(int(child.get("call_count") or 0) for child in children)
    highlights["insight_count"] = sum(int(child.get("insight_count") or 0) for child in children)
    themes: list[str] = []
    products: list[str] = []
    for child in children:
        extra = child.get("highlights") or {}
        themes.extend(extra.get("themes") or [])
        products.extend(extra.get("products") or [])
    highlights["themes"] = sorted({item for item in themes if item})[:12]
    highlights["products"] = sorted({item for item in products if item})[:12]
    return lines, highlights
