"""Add sentiment_label on feedbacks (Positive / Neutral / Negative).

Revision ID: b9c2d3e4f5a6
Revises: a8c1d2e3f4a5
Create Date: 2026-09-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b9c2d3e4f5a6"
down_revision: Union[str, None] = "a8c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feedbacks",
        sa.Column("sentiment_label", sa.String(length=20), nullable=True),
    )
    op.create_index("ix_feedbacks_sentiment_label", "feedbacks", ["sentiment_label"])


def downgrade() -> None:
    op.drop_index("ix_feedbacks_sentiment_label", table_name="feedbacks")
    op.drop_column("feedbacks", "sentiment_label")
