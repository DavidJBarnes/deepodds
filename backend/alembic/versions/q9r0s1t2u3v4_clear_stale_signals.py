"""clear stale signals from old defaults

Revision ID: q9r0s1t2u3v4
Revises: p8q9r0s1t2u3
Create Date: 2026-05-23
"""
from alembic import op

revision = "q9r0s1t2u3v4"
down_revision = "p8q9r0s1t2u3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM archived_signals")
    op.execute("DELETE FROM signals")


def downgrade() -> None:
    pass
