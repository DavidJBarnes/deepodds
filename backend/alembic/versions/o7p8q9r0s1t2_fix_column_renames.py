"""fix column renames that silently failed

Revision ID: o7p8q9r0s1t2
Revises: n6o7p8q9r0s1
Create Date: 2026-05-22
"""
from alembic import op

revision = "o7p8q9r0s1t2"
down_revision = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column renames skipped — Python models use mapped_column("coinbase_*")
    # to map robinhood_* attrs to the existing coinbase_* DB columns.
    pass


def downgrade() -> None:
    pass
