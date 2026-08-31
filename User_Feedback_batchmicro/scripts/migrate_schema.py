"""
Apply idempotent schema patches for Cloud SQL (shared with backend migrate job).

Run via Cloud Run job `pidilite-pipeline-migrate`:
  poetry run python scripts/migrate_schema.py
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text


def _database_url() -> str:
    return (
        f"postgresql+psycopg2://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
        f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
    )


def _add_columns(conn, table: str, columns: list[str]) -> None:
    for column in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}"))
        print(f"OK: {table}.{column.split()[0]}")


def _col_udt(conn, table: str, column: str) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT udt_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row[0] if row else None


def _align_products_with_local_model(conn) -> None:
    """
    Local db.models.Product:
      id INTEGER PK SERIAL, product_name, short_code, description, is_active

    Cloud may still be on the older UUID id + category varchar layout.
    """
    # Ensure description exists
    conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS description TEXT"))
    print("OK: products.description")

    # Drop leftover brand/category FK columns if present
    for col in ("brand_id", "category_id"):
        if _col_udt(conn, "products", col):
            fks = conn.execute(
                text(
                    """
                    SELECT tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_schema = 'public'
                      AND tc.table_name = 'products'
                      AND tc.constraint_type = 'FOREIGN KEY'
                      AND kcu.column_name = :c
                    """
                ),
                {"c": col},
            ).fetchall()
            for (name,) in fks:
                conn.execute(text(f'ALTER TABLE products DROP CONSTRAINT IF EXISTS "{name}"'))
            conn.execute(text(f"ALTER TABLE products DROP COLUMN IF EXISTS {col}"))
            print(f"OK: dropped products.{col}")

    # Convert UUID id → INTEGER SERIAL (alembic 2fe470ce7506), only if still uuid
    products_id_type = _col_udt(conn, "products", "id")
    if products_id_type == "uuid":
        print("ALIGN: products.id uuid → integer SERIAL")
        # Drop FKs pointing at products.id
        fks = conn.execute(
            text(
                """
                SELECT tc.table_name, tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND ccu.table_name = 'products'
                  AND ccu.column_name = 'id'
                """
            )
        ).fetchall()
        for table_name, constraint_name in fks:
            conn.execute(
                text(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{constraint_name}"')
            )
            print(f"OK: dropped FK {constraint_name} on {table_name}")

        # feedbacks.product_id may still be uuid — drop then recreate as integer
        if _col_udt(conn, "feedbacks", "product_id"):
            conn.execute(text("ALTER TABLE feedbacks DROP COLUMN IF EXISTS product_id"))
            print("OK: dropped feedbacks.product_id (uuid)")

        conn.execute(text("ALTER TABLE products DROP COLUMN id CASCADE"))
        conn.execute(text("ALTER TABLE products ADD COLUMN id SERIAL PRIMARY KEY"))
        print("OK: products.id SERIAL")

        conn.execute(
            text(
                "ALTER TABLE feedbacks ADD COLUMN product_id INTEGER "
                "REFERENCES products(id)"
            )
        )
        print("OK: feedbacks.product_id INTEGER FK")
    else:
        print(f"OK: products.id already {products_id_type}")
        # Ensure feedbacks.product_id is integer if products.id is integer
        fb_type = _col_udt(conn, "feedbacks", "product_id")
        if fb_type == "uuid":
            conn.execute(text("ALTER TABLE feedbacks DROP CONSTRAINT IF EXISTS feedbacks_product_id_fkey"))
            conn.execute(text("ALTER TABLE feedbacks DROP COLUMN IF EXISTS product_id"))
            conn.execute(
                text(
                    "ALTER TABLE feedbacks ADD COLUMN product_id INTEGER "
                    "REFERENCES products(id)"
                )
            )
            print("OK: feedbacks.product_id uuid → integer")
        elif fb_type is None:
            conn.execute(
                text(
                    "ALTER TABLE feedbacks ADD COLUMN product_id INTEGER "
                    "REFERENCES products(id)"
                )
            )
            print("OK: feedbacks.product_id added")

    # Legacy varchar category is fine to keep nullable; local model ignores it
    if _col_udt(conn, "products", "category"):
        conn.execute(text("ALTER TABLE products ALTER COLUMN category DROP NOT NULL"))
        print("OK: products.category nullable (legacy)")


def _drop_feedback_categories(conn) -> None:
    """Remove legacy feedback_categories (alembic 4f9ea1944e26) — not in local models."""
    exists = conn.execute(
        text(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = 'feedback_categories'
            )
            """
        )
    ).scalar()
    if not exists:
        print("OK: feedback_categories already absent")
        return

    # Drop FKs pointing at feedback_categories, then leftover category_id columns
    fks = conn.execute(
        text(
            """
            SELECT tc.table_name, tc.constraint_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name = 'feedback_categories'
            """
        )
    ).fetchall()
    for table_name, constraint_name, column_name in fks:
        conn.execute(
            text(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{constraint_name}"')
        )
        print(f"OK: dropped FK {constraint_name}")
        if column_name == "category_id" and _col_udt(conn, table_name, "category_id"):
            conn.execute(text(f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS category_id'))
            print(f"OK: dropped {table_name}.category_id")

    # In case FK already gone but columns remain
    for table_name in ("feedbacks", "feedback_tags"):
        if _col_udt(conn, table_name, "category_id"):
            conn.execute(text(f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS category_id'))
            print(f"OK: dropped {table_name}.category_id")

    conn.execute(text("DROP TABLE IF EXISTS feedback_categories CASCADE"))
    print("OK: dropped feedback_categories")


def main() -> None:
    engine = create_engine(_database_url())
    with engine.begin() as conn:
        # feature/AI — feedback tag taxonomy metadata
        _add_columns(
            conn,
            "feedback_tags",
            [
                "sub_tag_name VARCHAR(200)",
                "description TEXT",
                "group_type VARCHAR(100)",
                "category VARCHAR(100)",
            ],
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_feedback_tags_tag_name "
                "ON feedback_tags (tag_name)"
            )
        )
        print("OK: ux_feedback_tags_tag_name")

        # Align products with local Product model (uuid→int, description, drop brand FKs)
        _align_products_with_local_model(conn)

        # Drop legacy feedback_categories (+ category_id FKs on feedbacks / feedback_tags)
        _drop_feedback_categories(conn)

        # feature/test-debug — empty transcript / skip reason + insights audit JSON
        _add_columns(
            conn,
            "processed_file",
            [
                "empty_reason TEXT",
                "insights_raw_json JSONB",
                "gcs_transcript_uri TEXT",
                "raw_transcript_text TEXT",
                "translated_text TEXT",
                "processed_at TIMESTAMPTZ",
            ],
        )

        # feedbacks — columns used by insights pipeline
        _add_columns(
            conn,
            "feedbacks",
            [
                "product_name VARCHAR(200)",
                "product_id INTEGER",
                "group_type VARCHAR(100)",
                "category_type VARCHAR(100)",
                "verbatim_quote TEXT",
                "ai_summary TEXT",
                "start_index INTEGER",
                "end_index INTEGER",
                "contractor_profile VARCHAR(200)",
                "speaker_name VARCHAR(200)",
            ],
        )

        # Junction + competitor tables (insights M2M / competitor extraction)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS feedback_tag_link (
                    feedback_id UUID NOT NULL REFERENCES feedbacks(id) ON DELETE CASCADE,
                    tag_id UUID NOT NULL REFERENCES feedback_tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (feedback_id, tag_id)
                )
                """
            )
        )
        print("OK: feedback_tag_link")
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS feedback_competitors (
                    id UUID PRIMARY KEY,
                    feedback_id UUID NOT NULL REFERENCES feedbacks(id) ON DELETE CASCADE,
                    competitor_name VARCHAR(200) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
        )
        print("OK: feedback_competitors")
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_feedback_competitors_feedback_id "
                "ON feedback_competitors (feedback_id)"
            )
        )
        print("OK: ix_feedback_competitors_feedback_id")

        # file_details — match local FileDetails model (audio + dashboard metadata)
        _add_columns(
            conn,
            "file_details",
            [
                "call_date TIMESTAMPTZ",
                "audio_duration_seconds INTEGER",
                "language_code VARCHAR(20)",
                "state VARCHAR(100)",
                "division VARCHAR(100)",
                "zone VARCHAR(100)",
                "cluster VARCHAR(100)",
                "rfmm_cluster VARCHAR(100)",
                "rbdm_cluster VARCHAR(100)",  # legacy alias; prefer rfmm_cluster
                "town_city VARCHAR(100)",
                "tsi_territory_code VARCHAR(100)",
                "fme_code VARCHAR(100)",
                "tty_code VARCHAR(100)",
                "user_id_metadata VARCHAR(100)",
                "user_type VARCHAR(100)",
                "data_source VARCHAR(100)",
            ],
        )
        for idx_col in (
            "call_date",
            "language_code",
            "state",
            "division",
            "zone",
            "cluster",
            "rfmm_cluster",
            "rbdm_cluster",
            "town_city",
            "tsi_territory_code",
            "fme_code",
            "tty_code",
            "user_id_metadata",
            "user_type",
            "data_source",
        ):
            # Skip index create if column absent (e.g. after rename)
            if _col_udt(conn, "file_details", idx_col) is None:
                continue
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_file_details_{idx_col} "
                    f"ON file_details ({idx_col})"
                )
            )
        # Prefer rfmm_cluster (local model); rename legacy rbdm_cluster when needed
        if _col_udt(conn, "file_details", "rfmm_cluster") is None and _col_udt(
            conn, "file_details", "rbdm_cluster"
        ):
            conn.execute(text("ALTER TABLE file_details RENAME COLUMN rbdm_cluster TO rfmm_cluster"))
            print("OK: renamed file_details.rbdm_cluster -> rfmm_cluster")
        print("OK: file_details indexes")

        # Failed job audit table
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS failed_jobs (
                    id UUID PRIMARY KEY,
                    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    file_name VARCHAR(255),
                    error_message TEXT NOT NULL,
                    pipeline_stage VARCHAR(50) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
        )
        print("OK: failed_jobs")

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_failed_jobs_job_id ON failed_jobs (job_id)"
            )
        )
        print("OK: ix_failed_jobs_job_id")

    print("Schema migration complete.")


if __name__ == "__main__":
    main()
