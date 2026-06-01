"""Add UID counter table for thread-safe UID generation

Revision ID: add_uid_counter_table
Revises: 7332ed65ba00
Create Date: 2026-05-08 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_uid_counter_table'
down_revision = '7332ed65ba00'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('uid_counters',
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('last_value', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('role')
    )


def downgrade():
    op.drop_table('uid_counters')
