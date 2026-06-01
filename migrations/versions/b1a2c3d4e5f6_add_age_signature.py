"""add age and signature_path to users

Revision ID: b1a2c3d4e5f6
Revises: ec1607f1340a
Create Date: 2026-05-22 14:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1a2c3d4e5f6'
down_revision = 'ec1607f1340a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('age', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('signature_path', sa.String(length=300), nullable=True))


def downgrade():
    op.drop_column('users', 'signature_path')
    op.drop_column('users', 'age')
