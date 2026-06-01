"""Add ai_suggestions table

Revision ID: a9f1c2d3b4c5
Revises: 5bfaf20b2965
Create Date: 2026-05-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9f1c2d3b4c5'
down_revision = '5bfaf20b2965'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_suggestions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('activity_id', sa.Integer(), nullable=False),
        sa.Column('suggestion_text', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_ai_suggestion_activity_id', 'ai_suggestions', ['activity_id'], unique=False)


def downgrade():
    op.drop_index('ix_ai_suggestion_activity_id', table_name='ai_suggestions')
    op.drop_table('ai_suggestions')
