#!/usr/bin/env python3
"""Cloud Run / Cloud SQL helper for test01 re-runs.

Cloud SQL is private-IP only; run this inside pidilite-pipeline-svc's VPC
(same image, secrets, and connector).

  ACTION=status poetry run python scripts/gcp_sql_test01.py
  ACTION=delete poetry run python scripts/gcp_sql_test01.py
  ACTION=status PREFIX=test01-20260818-hhmmss poetry run python scripts/gcp_sql_test01.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from db.session import SessionLocal  # noqa: E402

# Default: every historical test01 prefix. Override with PREFIX=...
DEFAULT_LIKE = "%test01%"


def _like() -> str:
    prefix = (os.getenv("PREFIX") or "").strip()
    if prefix:
        return f"%{prefix}%"
    return os.getenv("URI_LIKE") or DEFAULT_LIKE


def _rows(db, like: str):
    return db.execute(
        text(
            """
            SELECT j.id,
                   j.status::text AS status,
                   j.gcs_input_uri,
                   fd.file_name,
                   fd.file_size_bytes,
                   fd.audio_duration_seconds,
                   length(coalesce(pf.raw_transcript_text, '')) AS raw_chars,
                   length(coalesce(pf.translated_text, '')) AS translated_chars,
                   (SELECT count(*) FROM feedbacks f WHERE f.job_id = j.id) AS feedback_count,
                   left(coalesce(pf.translated_text, ''), 160) AS translated_preview,
                   j.error_message
            FROM jobs j
            LEFT JOIN file_details fd ON fd.job_id = j.id
            LEFT JOIN processed_file pf ON pf.job_id = j.id
            WHERE j.gcs_input_uri LIKE :like
            ORDER BY j.created_at DESC
            """
        ),
        {"like": like},
    ).mappings().all()


def status(db, like: str) -> dict:
    rows = [dict(r) for r in _rows(db, like)]
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    pending_other = db.execute(
        text(
            """
            SELECT count(*) FROM jobs
            WHERE status = 'PENDING' AND gcs_input_uri NOT LIKE :like
            """
        ),
        {"like": like},
    ).scalar()
    return {
        "like": like,
        "count": len(rows),
        "by_status": by_status,
        "pending_other": int(pending_other or 0),
        "jobs": rows,
    }


def delete(db, like: str) -> dict:
    before = status(db, like)
    result = db.execute(
        text("DELETE FROM jobs WHERE gcs_input_uri LIKE :like"),
        {"like": like},
    )
    db.commit()
    orphan_batches = db.execute(
        text(
            """
            DELETE FROM batches b
            WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.batch_id = b.id)
            RETURNING id, batch_number
            """
        )
    ).fetchall()
    db.commit()
    return {
        "deleted_jobs": result.rowcount,
        "orphan_batches_removed": [
            {"id": r[0], "batch_number": r[1]} for r in orphan_batches
        ],
        "before": {"count": before["count"], "by_status": before["by_status"]},
    }


def summary(db, like: str) -> dict:
    """Compact status for polling scripts (no transcript previews)."""
    full = status(db, like)
    jobs = [
        {
            "id": r["id"],
            "status": r["status"],
            "file_name": r["file_name"],
            "feedback_count": r["feedback_count"],
            "error_message": r["error_message"],
        }
        for r in full["jobs"]
    ]
    return {
        "like": full["like"],
        "count": full["count"],
        "by_status": full["by_status"],
        "pending_other": full["pending_other"],
        "feedback_total": sum(int(j["feedback_count"] or 0) for j in jobs),
        "jobs": jobs,
    }


def main() -> int:
    action = (os.getenv("ACTION") or "status").strip().lower()
    like = _like()
    db = SessionLocal()
    try:
        if action == "delete":
            payload = delete(db, like)
        elif action == "summary":
            payload = summary(db, like)
        else:
            payload = status(db, like)
        print("SQL_OPS_JSON=" + json.dumps(payload, default=str, separators=(",", ":")))
        if action != "summary":
            print(json.dumps(payload, default=str, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
