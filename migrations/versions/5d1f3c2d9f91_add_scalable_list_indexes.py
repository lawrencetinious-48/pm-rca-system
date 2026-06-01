"""add scalable list indexes

Revision ID: 5d1f3c2d9f91
Revises: 7332ed65ba00
Create Date: 2026-03-30 15:10:00.000000

"""
from alembic import op
import sqlite3
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "5d1f3c2d9f91"
down_revision = "7332ed65ba00"
branch_labels = None
depends_on = None


def _index_exists(table_name, index_name):
    """Check if an index already exists in the SQLite database."""
    try:
        connection = op.get_context().bind
        query = text(
            f"SELECT name FROM sqlite_master WHERE type='index' AND name='{index_name}' AND tbl_name='{table_name}'"
        )
        result = connection.execute(query).fetchone()
        return result is not None
    except Exception:
        return False


def upgrade():
    with op.batch_alter_table("consumables", schema=None) as batch_op:
        if not _index_exists("consumables", "ix_consumable_created_at"):
            batch_op.create_index("ix_consumable_created_at", ["created_at"], unique=False)

    with op.batch_alter_table("activities", schema=None) as batch_op:
        if not _index_exists("activities", "ix_activity_created_at"):
            batch_op.create_index("ix_activity_created_at", ["created_at"], unique=False)
        if not _index_exists("activities", "ix_activity_risk_score"):
            batch_op.create_index("ix_activity_risk_score", ["risk_score"], unique=False)
        if not _index_exists("activities", "ix_activity_sla_deadline"):
            batch_op.create_index("ix_activity_sla_deadline", ["sla_deadline"], unique=False)
        if not _index_exists("activities", "ix_activity_type_created_at"):
            batch_op.create_index("ix_activity_type_created_at", ["activity_type", "created_at"], unique=False)

    with op.batch_alter_table("users", schema=None) as batch_op:
        if not _index_exists("users", "ix_user_created_at"):
            batch_op.create_index("ix_user_created_at", ["created_at"], unique=False)


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_user_created_at")

    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.drop_index("ix_activity_type_created_at")
        batch_op.drop_index("ix_activity_sla_deadline")
        batch_op.drop_index("ix_activity_risk_score")
        batch_op.drop_index("ix_activity_created_at")

    with op.batch_alter_table("consumables", schema=None) as batch_op:
        batch_op.drop_index("ix_consumable_created_at")
