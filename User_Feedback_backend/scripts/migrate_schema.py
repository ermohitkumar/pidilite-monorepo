"""
Apply idempotent schema patches for columns added after initial DB provisioning.

The API also runs this on startup. To apply it by hand:
  poetry run python scripts/migrate_schema.py
"""
import os

from sqlalchemy import create_engine, text


def _database_url() -> str:
    return (
        f"postgresql+psycopg2://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
        f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
    )

_FILE_DETAILS_COLUMNS = [
    "division VARCHAR(100)",
    "zone VARCHAR(100)",
    "cluster VARCHAR(100)",
    "rbdm_cluster VARCHAR(100)",
    "town_city VARCHAR(100)",
    "tsi_territory_code VARCHAR(100)",
    "fme_code VARCHAR(100)",
    "tty_code VARCHAR(100)",
    "user_id VARCHAR(100)",
    "user_type VARCHAR(100)",
    "data_source VARCHAR(100) DEFAULT 'Voice Conversations'",
]

_USER_COLUMNS = [
    "allowed_resources JSONB NOT NULL DEFAULT '[]'::jsonb",
]

_FEEDBACK_COLUMNS = [
    "theme VARCHAR(200)",
    "others_info TEXT",
]


def _add_columns(conn, table: str, columns: list[str]) -> None:
    for column in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}"))
        print(f"OK: {table}.{column.split()[0]}")


_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS roles (
    role_id VARCHAR(36) PRIMARY KEY,
    slug VARCHAR(50) NOT NULL UNIQUE,
    label VARCHAR(80) NOT NULL,
    description TEXT,
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
)
"""

def _drop_tag_name_unique(conn) -> None:
    """The new taxonomy repeats the name Others once per category."""
    rows = conn.execute(text("""
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.conrelid = 'feedback_tags'::regclass
          AND c.contype = 'u'
          AND a.attname = 'tag_name'
          AND cardinality(c.conkey) = 1
    """)).fetchall()
    for (name,) in rows:
        conn.execute(text(f'ALTER TABLE feedback_tags DROP CONSTRAINT IF EXISTS "{name}"'))
        print(f"OK: dropped unique constraint {name}")
    indexes = conn.execute(text("""
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'feedback_tags'
          AND indexdef ILIKE 'CREATE UNIQUE INDEX%'
          AND indexdef ILIKE '%(tag_name)%'
    """)).fetchall()
    for (name,) in indexes:
        conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        print(f"OK: dropped unique index {name}")


def apply_schema(engine) -> None:
    """Add columns and tables that create_all will not alter in place.

    SQLite test databases are built from the models. These patches target
    the Postgres instance, which does not rewrite existing tables.
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        _add_columns(conn, "file_details", _FILE_DETAILS_COLUMNS)
        _add_columns(conn, "users", _USER_COLUMNS)
        _add_columns(conn, "feedbacks", _FEEDBACK_COLUMNS)
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_feedbacks_theme ON feedbacks (theme)"
        ))
        print("OK: ix_feedbacks_theme")
        conn.execute(text(_ROLES_TABLE))
        if conn.execute(text("SELECT to_regclass('public.feedback_tags')")).scalar():
            _drop_tag_name_unique(conn)
        print("OK: roles")


def main() -> None:
    apply_schema(create_engine(_database_url()))
    print("Schema migration complete.")


if __name__ == "__main__":
    main()
