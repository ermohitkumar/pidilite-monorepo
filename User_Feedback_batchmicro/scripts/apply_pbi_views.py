#!/usr/bin/env python3
"""
Seed bi_feedback_taxonomy from scripts/data/feedback_taxonomy.json and apply
Power BI SQL views (scripts/sql/pbi_views.sql) to a Postgres database.

Default target: local docker DB `pidilite_gcp`.

Usage:
  # Via docker exec (recommended for local compose DB)
  python scripts/apply_pbi_views.py --docker-container user_feedback_batchmicro-db-1 --db pidilite_gcp

  # Via direct psycopg2 URL
  python scripts/apply_pbi_views.py --dsn postgresql://postgres:newpassword@127.0.0.1:5432/pidilite_gcp
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "scripts" / "data" / "feedback_taxonomy.json"
SQL_PATH = ROOT / "scripts" / "sql" / "pbi_views.sql"


def _load_taxonomy_rows() -> list[tuple]:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    rows = []
    for entry in data.get("taxonomy", []):
        rows.append(
            (
                int(entry["tag_id"]),
                entry.get("feedback_group") or "",
                entry.get("feedback_category") or "",
                entry.get("feedback_tag") or "",
                entry.get("feedback_sub_tag"),
                entry.get("description"),
            )
        )
    return rows


def _sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _build_seed_sql(rows: list[tuple]) -> str:
    lines = [
        "BEGIN;",
        "CREATE TABLE IF NOT EXISTS bi_feedback_taxonomy (",
        "    tag_id INTEGER PRIMARY KEY,",
        "    feedback_group VARCHAR(100) NOT NULL,",
        "    feedback_category VARCHAR(100) NOT NULL,",
        "    feedback_tag VARCHAR(300) NOT NULL,",
        "    feedback_sub_tag TEXT,",
        "    description TEXT",
        ");",
        "TRUNCATE bi_feedback_taxonomy;",
    ]
    for tag_id, group, category, tag, sub_tag, desc in rows:
        lines.append(
            "INSERT INTO bi_feedback_taxonomy "
            "(tag_id, feedback_group, feedback_category, feedback_tag, feedback_sub_tag, description) "
            f"VALUES ({tag_id}, {_sql_literal(group)}, {_sql_literal(category)}, "
            f"{_sql_literal(tag)}, {_sql_literal(sub_tag)}, {_sql_literal(desc)});"
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def _run_psql_docker(container: str, db: str, user: str, sql: str) -> None:
    proc = subprocess.run(
        ["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"psql failed (exit {proc.returncode})")
    if proc.stdout.strip():
        print(proc.stdout)


def _run_psycopg(dsn: str, sql: str) -> None:
    import psycopg2

    with psycopg2.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)


def _feedback_tags_pk_column_docker(container: str, db: str, user: str) -> str:
    """Return 'id' (local/ORM) or 'tag_id' (Cloud SQL taxonomy PK)."""
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-U",
            user,
            "-d",
            db,
            "-tAc",
            "SELECT CASE WHEN EXISTS ("
            "  SELECT 1 FROM information_schema.columns "
            "  WHERE table_schema='public' AND table_name='feedback_tags' AND column_name='id'"
            ") THEN 'id' ELSE 'tag_id' END;",
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"schema probe failed (exit {proc.returncode})")
    return (proc.stdout or "id").strip() or "id"


def _feedback_tags_pk_column_dsn(dsn: str) -> str:
    import psycopg2

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.columns "
                "  WHERE table_schema='public' AND table_name='feedback_tags' AND column_name='id'"
                ")"
            )
            return "id" if cur.fetchone()[0] else "tag_id"


def _adapt_views_sql(views_sql: str, tags_pk: str) -> str:
    """Join feedback_tags on id (ORM) or tag_id (Cloud SQL)."""
    if tags_pk == "id":
        return views_sql
    if "ON t.id = l.tag_id" not in views_sql:
        raise SystemExit("pbi_views.sql missing expected join: ON t.id = l.tag_id")
    return views_sql.replace("ON t.id = l.tag_id", "ON t.tag_id = l.tag_id")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Power BI views to Postgres")
    parser.add_argument("--docker-container", default="user_feedback_batchmicro-db-1")
    parser.add_argument("--db", default="pidilite_gcp")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--dsn", default=None, help="Optional direct Postgres DSN (skips docker)")
    args = parser.parse_args()

    if not TAXONOMY_PATH.exists():
        print(f"Missing taxonomy file: {TAXONOMY_PATH}")
        return 1
    if not SQL_PATH.exists():
        print(f"Missing SQL file: {SQL_PATH}")
        return 1

    rows = _load_taxonomy_rows()
    seed_sql = _build_seed_sql(rows)
    raw_views_sql = SQL_PATH.read_text(encoding="utf-8")

    if args.dsn:
        tags_pk = _feedback_tags_pk_column_dsn(args.dsn)
    else:
        tags_pk = _feedback_tags_pk_column_docker(args.docker_container, args.db, args.user)
    views_sql = _adapt_views_sql(raw_views_sql, tags_pk)

    print(f"Seeding {len(rows)} taxonomy rows…")
    print(f"feedback_tags PK column: {tags_pk}")
    print(f"Applying {SQL_PATH.relative_to(ROOT)}…")

    if args.dsn:
        _run_psycopg(args.dsn, seed_sql)
        _run_psycopg(args.dsn, views_sql)
    else:
        _run_psql_docker(args.docker_container, args.db, args.user, seed_sql)
        _run_psql_docker(args.docker_container, args.db, args.user, views_sql)

    # Quick verify
    verify = """
    SELECT 'bi_feedback_taxonomy' AS obj, count(*)::text AS n FROM bi_feedback_taxonomy
    UNION ALL
    SELECT 'vw_pbi_feedback_fact', count(*)::text FROM vw_pbi_feedback_fact
    UNION ALL
    SELECT 'vw_pbi_tag_counts', count(*)::text FROM vw_pbi_tag_counts
    UNION ALL
    SELECT 'vw_pbi_taxonomy_coverage', count(*)::text FROM vw_pbi_taxonomy_coverage;
    """
    print("Verify:")
    if args.dsn:
        import psycopg2

        with psycopg2.connect(args.dsn) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(verify)
                for row in cur.fetchall():
                    print(f"  {row[0]}: {row[1]}")
    else:
        _run_psql_docker(args.docker_container, args.db, args.user, verify)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
