"""Add period_summaries for BDE/RFMM/zone/division/product/tag rollups.

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "period_summaries",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("grain", sa.String(length=20), nullable=False),
        sa.Column("grain_key", sa.String(length=200), nullable=False),
        sa.Column("grain_label", sa.String(length=200), nullable=True),
        sa.Column("parent_key", sa.String(length=200), nullable=True),
        sa.Column("period_type", sa.String(length=20), nullable=False),
        sa.Column("period_key", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("highlights_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_kind", sa.String(length=40), nullable=False, server_default="insights"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "grain", "grain_key", "period_type", "period_key", "version",
            name="uq_period_summaries_version",
        ),
    )
    op.create_index("ix_period_summaries_grain", "period_summaries", ["grain"])
    op.create_index("ix_period_summaries_grain_key", "period_summaries", ["grain_key"])
    op.create_index("ix_period_summaries_parent_key", "period_summaries", ["parent_key"])
    op.create_index("ix_period_summaries_period_type", "period_summaries", ["period_type"])
    op.create_index("ix_period_summaries_period_key", "period_summaries", ["period_key"])
    op.create_index("ix_period_summaries_status", "period_summaries", ["status"])
    op.create_index("ix_period_summaries_is_current", "period_summaries", ["is_current"])
    op.create_index(
        "ix_period_summaries_current",
        "period_summaries",
        ["grain", "grain_key", "period_type", "period_key", "is_current"],
    )


def downgrade() -> None:
    op.drop_index("ix_period_summaries_current", table_name="period_summaries")
    op.drop_index("ix_period_summaries_is_current", table_name="period_summaries")
    op.drop_index("ix_period_summaries_status", table_name="period_summaries")
    op.drop_index("ix_period_summaries_period_key", table_name="period_summaries")
    op.drop_index("ix_period_summaries_period_type", table_name="period_summaries")
    op.drop_index("ix_period_summaries_parent_key", table_name="period_summaries")
    op.drop_index("ix_period_summaries_grain_key", table_name="period_summaries")
    op.drop_index("ix_period_summaries_grain", table_name="period_summaries")
    op.drop_table("period_summaries")
