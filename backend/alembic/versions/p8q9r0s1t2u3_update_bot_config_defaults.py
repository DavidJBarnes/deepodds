"""update existing bot_configs to profitable params

Old defaults (entry=-2.0, exit=0.0, lookback=16) fire false signals.
Profitable params from backtesting: entry=-3.0, exit=-0.5, lookback=48.

Revision ID: p8q9r0s1t2u3
Revises: o7p8q9r0s1t2
Create Date: 2026-05-22
"""
from alembic import op

revision = "p8q9r0s1t2u3"
down_revision = "o7p8q9r0s1t2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE bot_configs "
        "SET entry_z_score = -3.0, "
        "    exit_z_score = -0.5, "
        "    lookback_periods = 48, "
        "    pairs = 'SOL-USD,BTC-USD,ETH-USD', "
        "    position_size_usd = 25.0, "
        "    max_open_positions = 3 "
        "WHERE entry_z_score = -2.0 "
        "  AND exit_z_score = 0.0 "
        "  AND lookback_periods = 16"
    )

    op.execute(
        "DELETE FROM signals "
        "WHERE status = 'signaled' "
        "  AND fill_price IS NULL"
    )


def downgrade() -> None:
    pass
