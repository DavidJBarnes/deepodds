"""update kalshi_configs defaults for thin markets

Revision ID: u3v4w5x6y7z8
Revises: t2u3v4w5x6y7
Create Date: 2026-05-25
"""
from alembic import op


revision = "u3v4w5x6y7z8"
down_revision = "t2u3v4w5x6y7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE kalshi_configs SET
            min_volume_24h = 0,
            min_price = 0.01,
            min_hours_to_expiry = 2,
            lookback_periods = 6
        WHERE min_volume_24h = 50
          AND min_price = 0.05
          AND min_hours_to_expiry = 4
          AND lookback_periods = 24
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE kalshi_configs SET
            min_volume_24h = 50,
            min_price = 0.05,
            min_hours_to_expiry = 4,
            lookback_periods = 24
        WHERE min_volume_24h = 0
          AND min_price = 0.01
          AND min_hours_to_expiry = 2
          AND lookback_periods = 6
    """)
