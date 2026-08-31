"""
Apply idempotent schema patches for columns added after initial DB provisioning.

Run via Cloud Run job:
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


def _add_columns(table: str, columns: list[str]) -> None:
    engine = create_engine(_database_url())
    with engine.begin() as conn:
        for column in columns:
            stmt = text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}")
            conn.execute(stmt)
            print(f"OK: {table}.{column.split()[0]}")


def main() -> None:
    _add_columns("file_details", _FILE_DETAILS_COLUMNS)
    _add_columns("users", _USER_COLUMNS)
    print("Schema migration complete.")


if __name__ == "__main__":
    main()
