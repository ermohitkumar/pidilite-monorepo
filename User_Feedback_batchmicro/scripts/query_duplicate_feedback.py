"""Find (and optionally purge) duplicate feedback rows.

Uses User_Feedback_backend/.env (Cloud SQL Auth Proxy on 127.0.0.1).

    cd User_Feedback_backend
    .venv/bin/python ../User_Feedback_batchmicro/scripts/query_duplicate_feedback.py
    .venv/bin/python ../User_Feedback_batchmicro/scripts/query_duplicate_feedback.py --purge
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "User_Feedback_backend"
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

from core.config import settings  # noqa: E402

WITHIN_JOB = text("""
SELECT job_id, ai_summary, verbatim_quote, COUNT(*) AS n,
       array_agg(id::text ORDER BY created_at, id) AS ids
FROM feedbacks
GROUP BY job_id, ai_summary, verbatim_quote
HAVING COUNT(*) > 1
ORDER BY n DESC
""")

CROSS_JOB = text("""
SELECT ai_summary, verbatim_quote, COUNT(*) AS n,
       COUNT(DISTINCT job_id) AS jobs,
       array_agg(id::text ORDER BY created_at, id) AS ids
FROM feedbacks
GROUP BY ai_summary, verbatim_quote
HAVING COUNT(*) > 1 AND COUNT(DISTINCT job_id) > 1
ORDER BY n DESC
""")

COMPETITION_NO_PRODUCT = text("""
SELECT COUNT(*) AS n
FROM feedbacks f
WHERE (f.product_name IS NULL OR btrim(f.product_name) = '')
  AND (
    EXISTS (SELECT 1 FROM feedback_competitors c WHERE c.feedback_id = f.id)
    OR EXISTS (
      SELECT 1 FROM feedback_tag_link l
      JOIN feedback_tags t ON t.tag_id = l.tag_id
      WHERE l.feedback_id = f.id
        AND (t.tag_name ILIKE '%competit%' OR COALESCE(t.category, '') ILIKE '%competit%')
    )
  )
""")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete extra within-job duplicates (keeps the oldest row)",
    )
    args = parser.parse_args()

    engine = create_engine(settings.DATABASE_URL)
    with engine.begin() as conn:
        dups = conn.execute(WITHIN_JOB).mappings().all()
        print(f"Within-job duplicate groups: {len(dups)}")
        for row in dups[:25]:
            summary = (row["ai_summary"] or "")[:80]
            print(f"  n={row['n']} job={row['job_id']} summary={summary!r}")

        try:
            cross = conn.execute(CROSS_JOB).mappings().all()
            print(f"Cross-job identical summary+quote groups: {len(cross)}")
            for row in cross[:15]:
                summary = (row["ai_summary"] or "")[:80]
                print(f"  n={row['n']} jobs={row['jobs']} summary={summary!r}")
        except Exception as exc:
            print(f"Cross-job query skipped: {exc}")

        try:
            n = conn.execute(COMPETITION_NO_PRODUCT).scalar_one()
            print(f"Competition/competitor rows with empty product_name: {n}")
        except Exception as exc:
            print(f"Competition empty-product query skipped: {exc}")

        if not args.purge:
            return 0

        conn.execute(text("""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_id, ai_summary, verbatim_quote
                           ORDER BY created_at, id
                       ) AS rn
                FROM feedbacks
            )
            DELETE FROM feedback_tag_link
            WHERE feedback_id IN (SELECT id FROM ranked WHERE rn > 1)
        """))
        conn.execute(text("""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_id, ai_summary, verbatim_quote
                           ORDER BY created_at, id
                       ) AS rn
                FROM feedbacks
            )
            DELETE FROM feedback_competitors
            WHERE feedback_id IN (SELECT id FROM ranked WHERE rn > 1)
        """))
        deleted = conn.execute(text("""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_id, ai_summary, verbatim_quote
                           ORDER BY created_at, id
                       ) AS rn
                FROM feedbacks
            )
            DELETE FROM feedbacks
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """))
        print(f"Purged extra duplicate feedback rows: {deleted.rowcount}")

        empty_ids = conn.execute(text("""
            SELECT f.id
            FROM feedbacks f
            WHERE (f.product_name IS NULL OR btrim(f.product_name) = '')
              AND (
                EXISTS (SELECT 1 FROM feedback_competitors c WHERE c.feedback_id = f.id)
                OR EXISTS (
                  SELECT 1 FROM feedback_tag_link l
                  JOIN feedback_tags t ON t.tag_id = l.tag_id
                  WHERE l.feedback_id = f.id
                    AND (t.tag_name ILIKE '%competit%' OR COALESCE(t.category, '') ILIKE '%competit%')
                )
              )
        """)).fetchall()
        ids = [row[0] for row in empty_ids]
        if ids:
            conn.execute(text("DELETE FROM feedback_tag_link WHERE feedback_id = ANY(:ids)"), {"ids": ids})
            conn.execute(text("DELETE FROM feedback_competitors WHERE feedback_id = ANY(:ids)"), {"ids": ids})
            gone = conn.execute(text("DELETE FROM feedbacks WHERE id = ANY(:ids)"), {"ids": ids})
            print(f"Purged competition rows with empty product_name: {gone.rowcount}")
        else:
            print("Purged competition rows with empty product_name: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
