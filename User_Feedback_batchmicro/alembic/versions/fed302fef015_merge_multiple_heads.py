"""Merge multiple heads

Revision ID: fed302fef015
Revises: 9c9c9826e966, 9f8c9c30335f
Create Date: 2026-07-27 14:55:46.104538

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fed302fef015'
down_revision: Union[str, None] = ('9c9c9826e966', '9f8c9c30335f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
