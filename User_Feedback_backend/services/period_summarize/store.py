"""Persist and read versioned period_summaries rows."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from db.models import PeriodSummary
from services.period_summarize.period_keys import (
    display_key,
    key_group_token,
    matches_group,
    scoped_key,
)

_DASHES = str.maketrans({
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u00a0": " ",
    "\u202f": " ",
})
_SPACE_RE = re.compile(r"\s+")


def norm_label(value: Optional[str]) -> str:
    """Compare tag/product labels ignoring dashes, NBSP, and extra spaces."""
    text = _SPACE_RE.sub(" ", (value or "").translate(_DASHES)).strip().lower()
    return text


def label_keys(value: Optional[str]) -> list[str]:
    needle = norm_label(value)
    if not needle:
        return []
    keys = [needle]
    if " - " in needle:
        suffix = needle.rsplit(" - ", 1)[-1].strip()
        if suffix and suffix not in keys:
            keys.append(suffix)
    return keys


def serialize_row(row: Optional[PeriodSummary]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    highlights = row.highlights_json or {}
    return {
        "id": row.id,
        "grain": row.grain,
        "grain_key": row.grain_key,
        "grain_label": row.grain_label or row.grain_key,
        "parent_key": row.parent_key,
        "period_type": row.period_type,
        "period_key": row.period_key,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "summary_text": row.summary_text,
        "highlights": highlights,
        "source_kind": row.source_kind,
        "source_count": row.source_count,
        "call_count": row.call_count,
        "insight_count": row.insight_count,
        "status": row.status,
        "version": row.version,
        "is_current": row.is_current,
        "model_name": row.model_name,
        "prompt_tokens": row.prompt_tokens,
        "output_tokens": row.output_tokens,
        "error_message": row.error_message,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


def get_current(
    db: Session,
    grain: str,
    grain_key: str,
    period_type: str,
    period_key: str,
) -> Optional[PeriodSummary]:
    return (
        db.query(PeriodSummary)
        .filter(
            PeriodSummary.grain == grain,
            PeriodSummary.grain_key == grain_key,
            PeriodSummary.period_type == period_type,
            PeriodSummary.period_key == period_key,
            PeriodSummary.is_current.is_(True),
        )
        .one_or_none()
    )


def list_current(
    db: Session,
    *,
    grain: str,
    period_type: str,
    period_key: str,
    parent_key: Optional[str] = None,
    grain_key: Optional[str] = None,
    status: Optional[str] = None,
) -> list[PeriodSummary]:
    query = db.query(PeriodSummary).filter(
        PeriodSummary.grain == grain,
        PeriodSummary.period_type == period_type,
        PeriodSummary.period_key == period_key,
        PeriodSummary.is_current.is_(True),
    )
    if parent_key:
        query = query.filter(PeriodSummary.parent_key == parent_key)
    if grain_key:
        query = query.filter(PeriodSummary.grain_key == grain_key)
    if status:
        query = query.filter(PeriodSummary.status == status)
    return query.order_by(PeriodSummary.grain_key.asc()).all()


def matches_identity(row: PeriodSummary, identity: Optional[str], group_token: Optional[str] = None) -> bool:
    if identity and display_key(row.grain_key) != identity and (row.grain_key or "") != identity:
        return False
    return matches_group(row.grain_key, group_token)


def filter_group(
    rows: list[PeriodSummary],
    group_token: Optional[str] = None,
    *,
    identity: Optional[str] = None,
    parent_identity: Optional[str] = None,
) -> list[PeriodSummary]:
    matched: list[PeriodSummary] = []
    unscoped: list[PeriodSummary] = []
    for row in rows:
        if identity and display_key(row.grain_key) != identity and row.grain_key != identity:
            continue
        if parent_identity:
            parent = row.parent_key or ""
            if display_key(parent) != parent_identity and parent != parent_identity:
                continue
        found = key_group_token(row.grain_key)
        if not group_token:
            matched.append(row)
            continue
        if found == group_token:
            matched.append(row)
        elif found is None:
            unscoped.append(row)
    return matched or unscoped


def display_values(rows: list[PeriodSummary]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        if not is_visible_summary(row):
            continue
        value = display_key(row.grain_key) or row.grain_key
        if value and value not in seen:
            seen.append(value)
    return seen


def get_current_scoped(
    db: Session,
    grain: str,
    identity: str,
    period_type: str,
    period_key: str,
    group_token: Optional[str] = None,
) -> Optional[PeriodSummary]:
    candidates: list[str] = []
    if group_token:
        candidates.append(scoped_key(identity, group_token))
    candidates.append(identity)
    for key in candidates:
        row = get_current(db, grain, key, period_type, period_key)
        if row:
            return row
    for row in list_current(db, grain=grain, period_type=period_type, period_key=period_key):
        if matches_identity(row, identity, group_token):
            return row
    return None


def get_current_by_label(
    db: Session,
    grain: str,
    grain_label: str,
    period_type: str,
    period_key: str,
    group_token: Optional[str] = None,
    identity: Optional[str] = None,
) -> Optional[PeriodSummary]:
    needles = set(label_keys(grain_label))
    if not needles:
        return None
    scoped: Optional[PeriodSummary] = None
    unscoped: Optional[PeriodSummary] = None
    for row in list_current(db, grain=grain, period_type=period_type, period_key=period_key):
        if identity and display_key(row.grain_key) != identity and row.grain_key != identity:
            continue
        found = key_group_token(row.grain_key)
        if group_token and found not in {None, group_token}:
            continue
        haystack = set(label_keys(row.grain_label)) | set(label_keys(row.grain_key)) | set(label_keys(display_key(row.grain_key)))
        if not (needles & haystack):
            continue
        if group_token and found == group_token:
            scoped = scoped or row
        elif found is None:
            unscoped = unscoped or row
        elif not group_token:
            return row
    return scoped or unscoped


def is_visible_summary(row: Optional[PeriodSummary]) -> bool:
    """Hide empty / placeholder narratives from APIs and the UI."""
    if row is None or row.status != "ok":
        return False
    text = (row.summary_text or "").strip()
    if not text:
        return False
    return not text.lower().startswith("no insights")


def latest_period(db: Session, grain: str, period_type: str = "month") -> Optional[tuple[str, str]]:
    """Most recent period_key that has a current row for this grain."""
    row = (
        db.query(PeriodSummary.period_type, PeriodSummary.period_key)
        .filter(
            PeriodSummary.grain == grain,
            PeriodSummary.period_type == period_type,
            PeriodSummary.is_current.is_(True),
            PeriodSummary.status == "ok",
        )
        .order_by(PeriodSummary.period_key.desc())
        .first()
    )
    if not row:
        return None
    return str(row[0]), str(row[1])


def list_children(
    db: Session,
    *,
    child_grain: str,
    parent_key: str,
    period_type: str,
    period_key: str,
) -> list[PeriodSummary]:
    return list_current(
        db,
        grain=child_grain,
        period_type=period_type,
        period_key=period_key,
        parent_key=parent_key,
    )


def persist(
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
    summary_text: Optional[str],
    highlights: dict[str, Any],
    source_kind: str,
    source_count: int,
    call_count: int,
    insight_count: int,
    status: str,
    model_name: Optional[str],
    prompt_tokens: int,
    output_tokens: int,
    error_message: Optional[str] = None,
    force: bool = False,
    now: Optional[datetime] = None,
) -> tuple[PeriodSummary, bool]:
    """Insert a new version. Returns (row, skipped). Previous current rows are kept."""
    generated_at = now or datetime.now(timezone.utc)
    current = get_current(db, grain, grain_key, period_type, period_key)
    source_hash = (highlights or {}).get("source_hash")
    if (
        current
        and not force
        and current.status == status
        and (current.highlights_json or {}).get("source_hash") == source_hash
        and source_hash
    ):
        return current, True

    version = 1
    if current:
        current.is_current = False
        current.superseded_at = generated_at
        version = int(current.version or 1) + 1

    row = PeriodSummary(
        id=str(uuid4()),
        grain=grain,
        grain_key=grain_key,
        grain_label=grain_label or grain_key,
        parent_key=parent_key,
        period_type=period_type,
        period_key=period_key,
        period_start=period_start,
        period_end=period_end,
        summary_text=summary_text,
        highlights_json=highlights or {},
        source_kind=source_kind,
        source_count=source_count,
        call_count=call_count,
        insight_count=insight_count,
        status=status,
        version=version,
        is_current=True,
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        error_message=error_message,
        generated_at=generated_at,
    )
    db.add(row)
    db.flush()
    return row, False
