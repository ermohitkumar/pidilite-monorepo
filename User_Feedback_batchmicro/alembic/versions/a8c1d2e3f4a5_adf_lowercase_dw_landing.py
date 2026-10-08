"""Recreate DW landing tables as lowercase unquoted names for ADF/Npgsql.

Revision ID: a8c1d2e3f4a5
Revises: f1a2b3c4d5e6
Create Date: 2026-09-21
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = "a8c1d2e3f4a5"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "scripts" / "sql" / "dw_adf_lowercase_landing.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS vw_filter_options;
        DROP VIEW IF EXISTS vw_filter_hierarchy;
        DROP TABLE IF EXISTS factadditionalevent;
        DROP TABLE IF EXISTS factevent;
        DROP TABLE IF EXISTS factsitedetail;
        DROP TABLE IF EXISTS dimmember;
        DROP TABLE IF EXISTS dimhierarchy;
        DROP TABLE IF EXISTS vw_dimmaterial;
        """
    )
