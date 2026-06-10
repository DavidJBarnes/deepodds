"""drop crypto_configs table and flip signals.venue default to climate

Crypto trading was removed (no structural edge: realized-vol fair value vs a
liquid, forward-vol-priced market on identical public data). The product
keeps only the Kalshi climate path.

- Drops the crypto_configs table.
- Flips signals.venue server_default from 'kalshi_crypto' to 'kalshi_climate'.
  Existing rows are left untouched (historical crypto signals keep their venue
  so P&L/history stay accurate).
- model_train_history.crypto_* columns are intentionally retained — historical
  training rows reference them.

Revision ID: h2g3f4e5d6c7
Revises: g1f2e3d4c5b6
Create Date: 2026-06-10 09:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "h2g3f4e5d6c7"
down_revision: Union[str, None] = "g1f2e3d4c5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "signals", "venue",
        existing_type=sa.String(length=16),
        server_default="kalshi_climate",
        existing_nullable=False,
    )
    op.drop_table("crypto_configs")


def downgrade() -> None:
    op.alter_column(
        "signals", "venue",
        existing_type=sa.String(length=16),
        server_default="kalshi_crypto",
        existing_nullable=False,
    )
    op.create_table(
        "crypto_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False, unique=True, index=True),
        sa.Column("mode", sa.String(length=8), nullable=False, server_default="paper"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("series_tickers", sa.String(length=256), nullable=False,
                  server_default="KXBTC,KXETH"),
        sa.Column("min_volume_24h", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("min_price", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("max_price", sa.Float(), nullable=False, server_default="0.80"),
        sa.Column("min_hours_to_expiry", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("min_edge", sa.Float(), nullable=False, server_default="0.08"),
        sa.Column("exit_edge", sa.Float(), nullable=False, server_default="-0.02"),
        sa.Column("min_model_prob", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("max_model_prob", sa.Float(), nullable=False, server_default="0.80"),
        sa.Column("contracts_per_signal", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("max_cost_per_signal", sa.Float(), nullable=False, server_default="25.0"),
        sa.Column("max_open_positions", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_positions_per_event", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stop_loss_pct", sa.Float(), nullable=False, server_default="15.0"),
        sa.Column("take_profit_pct", sa.Float(), nullable=False, server_default="25.0"),
        sa.Column("daily_loss_limit_usd", sa.Float(), nullable=False, server_default="25.0"),
        sa.Column("max_signals_per_hour", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("min_hold_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("low_balance_warning_threshold_usd", sa.Float(), nullable=False,
                  server_default="20.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
