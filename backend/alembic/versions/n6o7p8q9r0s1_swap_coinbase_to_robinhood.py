"""swap coinbase to robinhood

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-05-22
"""
from alembic import op

revision = "n6o7p8q9r0s1"
down_revision = "m5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column renames skipped — Python models use mapped_column("coinbase_*")
    # to map robinhood_* attrs to the existing coinbase_* DB columns.
    pass


def downgrade() -> None:
    pass
