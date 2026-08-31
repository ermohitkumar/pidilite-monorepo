"""make tag_id primary key

Revision ID: 4d51d43b5636
Revises: d1a2b3c4d5e6
Create Date: 2026-08-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '4d51d43b5636'
down_revision = 'd1a2b3c4d5e6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Drop the foreign key constraint on feedback_tag_link
    op.drop_constraint('feedback_tag_link_tag_id_fkey', 'feedback_tag_link', type_='foreignkey')
    
    # 2. Drop the existing UUID primary key constraint from feedback_tags
    op.drop_constraint('feedback_tags_pkey', 'feedback_tags', type_='primary')
    
    # 3. Drop the UUID 'id' column from feedback_tags
    op.drop_column('feedback_tags', 'id')
    
    # 4. Make tag_id the primary key of feedback_tags
    op.create_primary_key('feedback_tags_pkey', 'feedback_tags', ['tag_id'])
    
    # 5. Drop the old UUID tag_id column from feedback_tag_link
    op.drop_column('feedback_tag_link', 'tag_id')
    
    # 6. Re-add tag_id as an Integer in feedback_tag_link
    op.add_column('feedback_tag_link', sa.Column('tag_id', sa.Integer(), nullable=False))
    
    # 7. Recreate the foreign key and primary key for feedback_tag_link
    op.create_foreign_key('feedback_tag_link_tag_id_fkey', 'feedback_tag_link', 'feedback_tags', ['tag_id'], ['tag_id'], ondelete='CASCADE')
    op.create_primary_key('feedback_tag_link_pkey', 'feedback_tag_link', ['feedback_id', 'tag_id'])


def downgrade() -> None:
    # We won't fully support downgrade for this one due to UUID data loss, but we can try to revert the schema
    op.drop_constraint('feedback_tag_link_pkey', 'feedback_tag_link', type_='primary')
    op.drop_constraint('feedback_tag_link_tag_id_fkey', 'feedback_tag_link', type_='foreignkey')
    op.drop_column('feedback_tag_link', 'tag_id')
    op.add_column('feedback_tag_link', sa.Column('tag_id', postgresql.UUID(as_uuid=False), nullable=False))
    
    op.drop_constraint('feedback_tags_pkey', 'feedback_tags', type_='primary')
    op.add_column('feedback_tags', sa.Column('id', postgresql.UUID(as_uuid=False), nullable=False))
    op.create_primary_key('feedback_tags_pkey', 'feedback_tags', ['id'])
    
    op.create_foreign_key('feedback_tag_link_tag_id_fkey', 'feedback_tag_link', 'feedback_tags', ['tag_id'], ['id'], ondelete='CASCADE')
    op.create_primary_key('feedback_tag_link_pkey', 'feedback_tag_link', ['feedback_id', 'tag_id'])
