"""add tag_id to feedback_tags and drop tag_name unique constraint

Revision ID: d1a2b3c4d5e6
Revises: 2164d47fca79
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1a2b3c4d5e6'
down_revision = '2164d47fca79'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('feedback_tags', sa.Column('tag_id', sa.Integer(), nullable=True))
    op.create_unique_constraint('uq_feedback_tags_tag_id', 'feedback_tags', ['tag_id'])
    # Drop unique constraint on tag_name (taxonomy has duplicate names like 'Product', 'Carnival')
    op.drop_constraint('feedback_tags_tag_name_key', 'feedback_tags', type_='unique')


def downgrade() -> None:
    op.create_unique_constraint('feedback_tags_tag_name_key', 'feedback_tags', ['tag_name'])
    op.drop_constraint('uq_feedback_tags_tag_id', 'feedback_tags', type_='unique')
    op.drop_column('feedback_tags', 'tag_id')
