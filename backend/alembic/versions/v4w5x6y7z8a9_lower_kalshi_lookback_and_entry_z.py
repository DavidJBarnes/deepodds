"""lower kalshi lookback to 3 and entry_z to -1.5 for thin markets

Revision ID: v4w5x6y7z8a9
Revises: u3v4w5x6y7z8
Create Date: 2026-05-25
"""
from alembic import op


revision = "v4w5x6y7z8a9"
down_revision = "u3v4w5x6y7z8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE kalshi_configs SET
            lookback_periods = 3,
            entry_z_score = -1.5
        WHERE lookback_periods = 6
          AND entry_z_score = -2.0
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE kalshi_configs SET
            lookback_periods = 6,
            entry_z_score = -2.0
        WHERE lookback_periods = 3
          AND entry_z_score = -1.5
    """)
