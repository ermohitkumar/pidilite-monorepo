"""add_start_end_index_to_feedbacks

Revision ID: a3f1b2c4d5e6
Revises: 98c2f7bc3a9a
Create Date: 2026-07-17 13:54:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f1b2c4d5e6'
down_revision: Union[str, None] = '98c2f7bc3a9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('feedbacks', sa.Column('start_index', sa.Integer(), nullable=True))
    op.add_column('feedbacks', sa.Column('end_index', sa.Integer(), nullable=True))
    # Make verbatim_quote nullable (was NOT NULL before, now computed from indices)
    op.alter_column('feedbacks', 'verbatim_quote', existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column('feedbacks', 'verbatim_quote', existing_type=sa.Text(), nullable=False)
    op.drop_column('feedbacks', 'end_index')
    op.drop_column('feedbacks', 'start_index')
