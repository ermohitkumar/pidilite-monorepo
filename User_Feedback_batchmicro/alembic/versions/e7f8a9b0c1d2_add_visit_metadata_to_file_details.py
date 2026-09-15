"""Add visit keys parsed from GCS audio filenames onto file_details.

Revision ID: e7f8a9b0c1d2
Revises: 4d51d43b5636
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "4d51d43b5636"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("site_number", 50),
    ("membership_no", 50),
    ("bde_code", 50),
    ("visit_sfid", 50),
    ("cmdi_code", 110),
    ("site_id", 40),
    ("additional_event_id", 150),
)


def upgrade() -> None:
    for name, length in _COLUMNS:
        op.add_column(
            "file_details",
            sa.Column(name, sa.String(length=length), nullable=True),
        )
        op.create_index(f"ix_file_details_{name}", "file_details", [name], unique=False)


def downgrade() -> None:
    for name, _length in reversed(_COLUMNS):
        op.drop_index(f"ix_file_details_{name}", table_name="file_details")
        op.drop_column("file_details", name)
