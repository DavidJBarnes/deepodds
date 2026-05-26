"""kalshi: replace mean-reversion with probability fair-value model

Revision ID: w5x6y7z8a9b0
Revises: v4w5x6y7z8a9
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa


revision = "w5x6y7z8a9b0"
down_revision = "v4w5x6y7z8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- kalshi_configs: swap z-score params for probability params ---
    op.drop_column("kalshi_configs", "candle_interval")
    op.drop_column("kalshi_configs", "lookback_periods")
    op.drop_column("kalshi_configs", "entry_z_score")
    op.drop_column("kalshi_configs", "exit_z_score")

    op.add_column("kalshi_configs", sa.Column("min_edge", sa.Float(), server_default="0.05", nullable=False))
    op.add_column("kalshi_configs", sa.Column("vol_lookback_hours", sa.Integer(), server_default="24", nullable=False))
    op.add_column("kalshi_configs", sa.Column("vol_interval", sa.String(4), server_default="15m", nullable=False))
    op.add_column("kalshi_configs", sa.Column("exit_edge", sa.Float(), server_default="-0.02", nullable=False))

    # --- signals: add probability fields ---
    for table in ("signals", "archived_signals"):
        op.add_column(table, sa.Column("model_prob", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("market_prob", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("edge", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("floor_strike", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("cap_strike", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("strike_type", sa.String(16), nullable=True))
        op.add_column(table, sa.Column("underlying_price", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("realized_vol", sa.Float(), nullable=True))

    # --- pair_configs: add edge overrides ---
    op.add_column("pair_configs", sa.Column("min_edge", sa.Float(), nullable=True))
    op.add_column("pair_configs", sa.Column("exit_edge", sa.Float(), nullable=True))

    # --- cancel open Kalshi signals to avoid mixing strategies ---
    op.execute("""
        UPDATE signals SET
            status = 'cancelled',
            error_message = 'strategy_refactor'
        WHERE venue = 'kalshi'
          AND status IN ('signaled', 'placed', 'filled')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE signals SET
            status = 'filled',
            error_message = NULL
        WHERE venue = 'kalshi'
          AND status = 'cancelled'
          AND error_message = 'strategy_refactor'
    """)

    op.drop_column("pair_configs", "exit_edge")
    op.drop_column("pair_configs", "min_edge")

    for table in ("signals", "archived_signals"):
        op.drop_column(table, "realized_vol")
        op.drop_column(table, "underlying_price")
        op.drop_column(table, "strike_type")
        op.drop_column(table, "cap_strike")
        op.drop_column(table, "floor_strike")
        op.drop_column(table, "edge")
        op.drop_column(table, "market_prob")
        op.drop_column(table, "model_prob")

    op.drop_column("kalshi_configs", "exit_edge")
    op.drop_column("kalshi_configs", "vol_interval")
    op.drop_column("kalshi_configs", "vol_lookback_hours")
    op.drop_column("kalshi_configs", "min_edge")

    op.add_column("kalshi_configs", sa.Column("exit_z_score", sa.Float(), server_default="-0.3", nullable=False))
    op.add_column("kalshi_configs", sa.Column("entry_z_score", sa.Float(), server_default="-1.5", nullable=False))
    op.add_column("kalshi_configs", sa.Column("lookback_periods", sa.Integer(), server_default="3", nullable=False))
    op.add_column("kalshi_configs", sa.Column("candle_interval", sa.Integer(), server_default="60", nullable=False))
