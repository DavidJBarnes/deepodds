"""tune kalshi config defaults for hourly candles

Revision ID: s1t2u3v4w5x6
Revises: r0s1t2u3v4w5
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "s1t2u3v4w5x6"
down_revision = "r0s1t2u3v4w5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE kalshi_configs
        SET candle_interval = 60,
            lookback_periods = 24,
            entry_z_score = -2.0,
            min_volume_24h = 500
        WHERE candle_interval = 1
          AND lookback_periods = 60
          AND entry_z_score = -2.5
          AND min_volume_24h = 100
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE kalshi_configs
        SET candle_interval = 1,
            lookback_periods = 60,
            entry_z_score = -2.5,
            min_volume_24h = 100
        WHERE candle_interval = 60
          AND lookback_periods = 24
          AND entry_z_score = -2.0
          AND min_volume_24h = 500
    """)
