"""add kalshi support

Revision ID: r0s1t2u3v4w5
Revises: q9r0s1t2u3v4
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "r0s1t2u3v4w5"
down_revision = "q9r0s1t2u3v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kalshi_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True, index=True, nullable=False),
        sa.Column("mode", sa.String(8), server_default="paper", nullable=False),
        sa.Column("enabled", sa.Boolean, server_default="false", nullable=False),
        sa.Column("series_tickers", sa.String(256), server_default="KXBTC,KXETH", nullable=False),
        sa.Column("min_volume_24h", sa.Integer, server_default="100", nullable=False),
        sa.Column("min_price", sa.Float, server_default="0.15", nullable=False),
        sa.Column("max_price", sa.Float, server_default="0.85", nullable=False),
        sa.Column("min_hours_to_expiry", sa.Integer, server_default="4", nullable=False),
        sa.Column("candle_interval", sa.Integer, server_default="1", nullable=False),
        sa.Column("lookback_periods", sa.Integer, server_default="60", nullable=False),
        sa.Column("entry_z_score", sa.Float, server_default="-2.5", nullable=False),
        sa.Column("exit_z_score", sa.Float, server_default="-0.3", nullable=False),
        sa.Column("contracts_per_signal", sa.Integer, server_default="50", nullable=False),
        sa.Column("max_open_positions", sa.Integer, server_default="5", nullable=False),
        sa.Column("stop_loss_pct", sa.Float, server_default="15.0", nullable=False),
        sa.Column("daily_loss_limit_usd", sa.Float, server_default="25.0", nullable=False),
        sa.Column("max_signals_per_hour", sa.Integer, server_default="3", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.add_column("users", sa.Column("kalshi_api_key_id", sa.String(256), nullable=True))
    op.add_column("users", sa.Column("kalshi_private_key", sa.Text, nullable=True))

    op.add_column("signals", sa.Column("venue", sa.String(16), server_default="crypto", nullable=False))
    op.add_column("signals", sa.Column("market_ticker", sa.String(64), nullable=True))
    op.add_column("signals", sa.Column("event_ticker", sa.String(64), nullable=True))
    op.add_column("signals", sa.Column("expiry_time", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_signals_venue", "signals", ["venue"])

    op.add_column("archived_signals", sa.Column("venue", sa.String(16), server_default="crypto", nullable=False))
    op.add_column("archived_signals", sa.Column("market_ticker", sa.String(64), nullable=True))
    op.add_column("archived_signals", sa.Column("event_ticker", sa.String(64), nullable=True))
    op.add_column("archived_signals", sa.Column("expiry_time", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("archived_signals", "expiry_time")
    op.drop_column("archived_signals", "event_ticker")
    op.drop_column("archived_signals", "market_ticker")
    op.drop_column("archived_signals", "venue")
    op.drop_index("ix_signals_venue", "signals")
    op.drop_column("signals", "expiry_time")
    op.drop_column("signals", "event_ticker")
    op.drop_column("signals", "market_ticker")
    op.drop_column("signals", "venue")
    op.drop_column("users", "kalshi_private_key")
    op.drop_column("users", "kalshi_api_key_id")
    op.drop_table("kalshi_configs")
