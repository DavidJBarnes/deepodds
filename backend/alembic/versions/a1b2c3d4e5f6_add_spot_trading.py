"""add spot trading tables and columns

Revision ID: a1b2c3d4e5f6
Revises: f8a5c023de91
Create Date: 2026-05-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f8a5c023de91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("coinbase_api_key", sa.String(256), nullable=True))
    op.add_column("users", sa.Column("coinbase_api_secret", sa.Text(), nullable=True))

    op.add_column("bot_configs", sa.Column("spot_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("bot_configs", sa.Column("spot_mode", sa.String(8), server_default="paper", nullable=False))
    op.add_column("bot_configs", sa.Column("spot_dip_pct", sa.Float(), server_default="3.0", nullable=False))
    op.add_column("bot_configs", sa.Column("spot_take_profit_pct", sa.Float(), server_default="2.0", nullable=False))
    op.add_column("bot_configs", sa.Column("spot_stop_loss_pct", sa.Float(), server_default="5.0", nullable=False))
    op.add_column("bot_configs", sa.Column("spot_buy_amount_usd", sa.Integer(), server_default="50", nullable=False))
    op.add_column("bot_configs", sa.Column("spot_max_position_usd", sa.Integer(), server_default="500", nullable=False))
    op.add_column("bot_configs", sa.Column("spot_cooldown_minutes", sa.Integer(), server_default="60", nullable=False))

    op.create_table(
        "spot_trades",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("price_usd", sa.Float(), nullable=False),
        sa.Column("quantity_btc", sa.Float(), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("coinbase_order_id", sa.String(256), nullable=True),
        sa.Column("pnl_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "spot_positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("entry_price_usd", sa.Float(), nullable=False),
        sa.Column("quantity_btc", sa.Float(), nullable=False),
        sa.Column("cost_basis_usd", sa.Float(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="open", index=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("spot_positions")
    op.drop_table("spot_trades")
    op.drop_column("bot_configs", "spot_cooldown_minutes")
    op.drop_column("bot_configs", "spot_max_position_usd")
    op.drop_column("bot_configs", "spot_buy_amount_usd")
    op.drop_column("bot_configs", "spot_stop_loss_pct")
    op.drop_column("bot_configs", "spot_take_profit_pct")
    op.drop_column("bot_configs", "spot_dip_pct")
    op.drop_column("bot_configs", "spot_mode")
    op.drop_column("bot_configs", "spot_enabled")
    op.drop_column("users", "coinbase_api_secret")
    op.drop_column("users", "coinbase_api_key")
