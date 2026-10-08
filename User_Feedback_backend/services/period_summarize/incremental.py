"""Incremental period-summary helpers: day cutoff, tracking, insight partition."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def as_of_date(now: Optional[datetime] = None) -> date:
    """Calendar day in Asia/Kolkata — daily runs freeze only completed local days."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(IST).date()


def row_call_date(row: dict[str, Any]) -> Optional[date]:
    value = row.get("call_date")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def insight_id(row: dict[str, Any]) -> Optional[str]:
    value = row.get("insight_id")
    if value is None:
        value = row.get("id")
    if value is None:
        return None
    return str(value)


def parse_covered_through(raw: Any) -> Optional[date]:
    if not raw:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def partition_insights(
    rows: list[dict[str, Any]],
    *,
    covered_through: Optional[date],
    as_of: date,
    force: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows into new closed-day insights, open-day, and empty."""
    new_rows: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    empty_rows: list[dict[str, Any]] = []
    for row in rows:
        call_day = row_call_date(row)
        has_text = bool(str(row.get("ai_summary") or "").strip())
        if call_day is None:
            empty_rows.append(row)
            continue
        # Daily incremental freezes incomplete local days. Force rebuilds (ops /
        # full-month) must include the open day or in-progress months stay empty.
        if not force and call_day >= as_of:
            open_rows.append(row)
            continue
        if not has_text:
            empty_rows.append(row)
            continue
        if force or covered_through is None or call_day > covered_through:
            new_rows.append(row)
    return new_rows, open_rows, empty_rows


def tracking_for_insights(
    *,
    previous_ids: list[str],
    new_rows: list[dict[str, Any]],
    open_rows: list[dict[str, Any]],
    empty_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    covered_through: Optional[date],
    as_of: date,
    checked_at: datetime,
    summary_updated_at: Optional[str],
) -> dict[str, Any]:
    considered = list(
        dict.fromkeys([*previous_ids, *(insight_id(row) for row in new_rows if insight_id(row))])
    )
    considered_set = set(considered)
    excluded: list[dict[str, str]] = []
    for row in open_rows:
        row_id = insight_id(row)
        if row_id:
            excluded.append({"id": row_id, "reason": "open_day"})
    for row in empty_rows:
        row_id = insight_id(row)
        if row_id:
            excluded.append({"id": row_id, "reason": "empty"})
    for row in all_rows:
        row_id = insight_id(row)
        if not row_id or row_id in considered_set:
            continue
        call_day = row_call_date(row)
        if call_day is not None and call_day >= as_of:
            continue
        if not str(row.get("ai_summary") or "").strip():
            continue
        if any(item["id"] == row_id for item in excluded):
            continue
        excluded.append({"id": row_id, "reason": "not_yet_run"})

    latest = covered_through
    for row in new_rows:
        call_day = row_call_date(row)
        if call_day and (latest is None or call_day > latest):
            latest = call_day
    return {
        "covered_through": latest.isoformat() if latest else None,
        "considered_insight_ids": considered,
        "excluded_insights": excluded,
        "tracking_checked_at": checked_at.isoformat(),
        "summary_updated_at": summary_updated_at,
        "as_of": as_of.isoformat(),
    }


def covered_through_from_rows(rows: list[dict[str, Any]]) -> Optional[date]:
    latest: Optional[date] = None
    for row in rows:
        call_day = row_call_date(row)
        if call_day and (latest is None or call_day > latest):
            latest = call_day
    return latest
