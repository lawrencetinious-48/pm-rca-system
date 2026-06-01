"""add password reset tokens table

Revision ID: ec1607f1340a
Revises: 5bfaf20b2965
Create Date: 2026-05-14 11:12:52.342475

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ec1607f1340a'
down_revision = '5bfaf20b2965'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('password_reset_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash')
    )


def downgrade():
    op.drop_table('password_reset_tokens')
