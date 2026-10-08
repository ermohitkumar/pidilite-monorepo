"""Backfill insight sentiment and rewrite current period-summary rollups."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified

from db.models import PeriodSummary
from db.session import SessionLocal
from services.period_summarize import combine
from services.period_summarize.compact import (
    combine_child_rollups,
    format_findings,
    gather_insights,
    infer_sentiment,
    normalize_sentiment,
    rollup_from_rows,
)
from services.period_summarize.period_keys import (
    CHILD_GRAIN,
    INSIGHT_GRAINS,
    bounds_for,
    child_month_keys,
    child_quarter_keys,
)


def _grain_depth(grain: str) -> int:
    depth = 0
    current = grain
    seen: set[str] = set()
    while current in CHILD_GRAIN and current not in seen:
        seen.add(current)
        current = CHILD_GRAIN[current]
        depth += 1
    return depth


def ensure_feedback_sentiment_column(db) -> None:
    db.execute(text(
        "ALTER TABLE feedbacks ADD COLUMN IF NOT EXISTS sentiment_label VARCHAR(20)"
    ))
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_feedbacks_sentiment_label "
        "ON feedbacks (sentiment_label)"
    ))
    db.commit()


def backfill_insight_sentiments(db) -> dict[str, int]:
    ensure_feedback_sentiment_column(db)
    rows = db.execute(text(
        "SELECT id, ai_summary, verbatim_quote, sentiment_label FROM feedbacks"
    )).mappings().all()
    updated = 0
    skipped = 0
    for row in rows:
        current = normalize_sentiment(row["sentiment_label"])
        label = current or infer_sentiment(
            f"{row.get('ai_summary') or ''} {row.get('verbatim_quote') or ''}"
        )
        if current == label:
            skipped += 1
            continue
        db.execute(
            text("UPDATE feedbacks SET sentiment_label = :label WHERE id = :id"),
            {"label": label, "id": row["id"]},
        )
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped, "total": len(rows)}


def _period_bounds(row: PeriodSummary):
    if row.period_start and row.period_end:
        return row.period_start, row.period_end
    return bounds_for(row.period_type, row.period_key)


def _rollup_for_row(db, row: PeriodSummary) -> tuple[list[dict], dict]:
    highlights = dict(row.highlights_json or {})
    start, end = _period_bounds(row)
    extra = None
    if row.grain in INSIGHT_GRAINS:
        insights = gather_insights(
            db,
            start=start,
            end=end,
            grain=row.grain,
            grain_key=row.grain_key,
        )
        extra = rollup_from_rows(insights)
    else:
        children = combine.children_for(
            db,
            grain=row.grain,
            grain_key=row.grain_key,
            period_type=row.period_type,
            period_key=row.period_key,
        )
        if row.period_type == "quarter":
            children = children or combine.children_for(
                db,
                grain=row.grain,
                grain_key=row.grain_key,
                period_type=row.period_type,
                period_key=row.period_key,
                child_period_type="month",
                child_period_keys=child_month_keys(row.period_key),
            )
        elif row.period_type == "year":
            children = children or combine.children_for(
                db,
                grain=row.grain,
                grain_key=row.grain_key,
                period_type=row.period_type,
                period_key=row.period_key,
                child_period_type="quarter",
                child_period_keys=child_quarter_keys(row.period_key),
            )
        if children:
            extra = combine_child_rollups(children)
    if extra:
        highlights.update(extra)
        return list(extra.get("findings") or []), highlights
    return list(highlights.get("findings") or []), highlights


def rewrite_current_product_tag_summaries(db) -> dict[str, int]:
    period_rank = {"month": 0, "quarter": 1, "year": 2}
    rows = (
        db.query(PeriodSummary)
        .filter(
            PeriodSummary.is_current.is_(True),
            PeriodSummary.status == "ok",
        )
        .all()
    )
    rows.sort(
        key=lambda row: (
            0 if row.grain in INSIGHT_GRAINS else 1,
            _grain_depth(row.grain),
            period_rank.get(row.period_type, 9),
            str(row.grain),
        )
    )
    updated = 0
    skipped = 0
    with_sentiment = 0
    for row in rows:
        try:
            findings, highlights = _rollup_for_row(db, row)
        except Exception:
            skipped += 1
            continue
        text = format_findings(findings)
        if text:
            row.summary_text = text
            highlights["findings"] = findings
        row.highlights_json = highlights
        flag_modified(row, "highlights_json")
        updated += 1
        if highlights.get("sentiment"):
            with_sentiment += 1
        db.flush()
    db.commit()
    return {
        "updated": updated,
        "skipped": skipped,
        "total": len(rows),
        "with_sentiment": with_sentiment,
    }


if __name__ == "__main__":
    db = SessionLocal()
    try:
        insights = backfill_insight_sentiments(db)
        print({"insights": insights}, flush=True)
        print(rewrite_current_product_tag_summaries(db), flush=True)
    finally:
        db.close()
