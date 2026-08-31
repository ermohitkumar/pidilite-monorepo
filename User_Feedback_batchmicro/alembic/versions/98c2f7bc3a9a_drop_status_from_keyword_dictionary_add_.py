"""drop_status_from_keyword_dictionary_add_unique_canonical_term

Revision ID: 98c2f7bc3a9a
Revises: 98321b6da470
Create Date: 2026-06-17 15:05:32.209471

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98c2f7bc3a9a'
down_revision: Union[str, None] = '98321b6da470'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the status column from keyword_dictionary
    op.drop_column('keyword_dictionary', 'status')

    # Drop the now-unused keywordstatus enum type
    op.execute("DROP TYPE IF EXISTS keywordstatus")

    # Add unique constraint on canonical_term to prevent duplicate entries
    op.create_unique_constraint(
        'uq_keyword_dictionary_canonical_term',
        'keyword_dictionary',
        ['canonical_term'],
    )


def downgrade() -> None:
    # Remove the unique constraint on canonical_term
    op.drop_constraint(
        'uq_keyword_dictionary_canonical_term',
        'keyword_dictionary',
        type_='unique',
    )

    # Re-create the keywordstatus enum type
    keywordstatus = sa.Enum(
        'ACTIVE', 'PUBLISHED', 'DRAFT', 'ARCHIVED',
        name='keywordstatus',
    )
    keywordstatus.create(op.get_bind(), checkfirst=True)

    # Re-add the status column
    op.add_column(
        'keyword_dictionary',
        sa.Column('status', keywordstatus, nullable=True),
    )
