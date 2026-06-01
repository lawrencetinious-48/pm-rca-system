"""Add bootstrap_state table for transactional first-user safety

Revision ID: a1b2c3d4e5f6
Revises: ec1607f1340a
Create Date: 2026-05-14 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'ec1607f1340a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bootstrap_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bootstrap_complete', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('first_developer_id', sa.Integer(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['first_developer_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('bootstrap_state')
