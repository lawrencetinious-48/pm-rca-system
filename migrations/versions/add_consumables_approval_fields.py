"""Add approval and review fields to consumables

Revision ID: add_consumables_approval_fields
Revises: 
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_consumables_approval_fields'
down_revision = ('6bf60953b28f', 'add_uid_counter_table')
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('consumables', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_approved', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('approved_by', sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('treatment_given', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('review_notes', sa.Text(), nullable=True))
        batch_op.create_index('ix_consumable_approved_at', ['approved_at'], unique=False)
        batch_op.create_index('ix_consumable_is_approved', ['is_approved'], unique=False)


def downgrade():
    with op.batch_alter_table('consumables', schema=None) as batch_op:
        batch_op.drop_index('ix_consumable_is_approved')
        batch_op.drop_index('ix_consumable_approved_at')
        batch_op.drop_column('review_notes')
        batch_op.drop_column('treatment_given')
        batch_op.drop_column('approved_at')
        batch_op.drop_column('approved_by')
        batch_op.drop_column('is_approved')
