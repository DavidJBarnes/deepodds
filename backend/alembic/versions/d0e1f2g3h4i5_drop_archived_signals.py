"""drop archived_signals table

Revision ID: d0e1f2g3h4i5
Revises: c4d5e6f7g8h9
Create Date: 2026-05-26 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2g3h4i5"
down_revision: Union[str, None] = "c4d5e6f7g8h9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("archived_signals")


def downgrade() -> None:
    op.create_table(
        "archived_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("original_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("venue", sa.String(16), server_default="crypto", nullable=False),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("model_prob", sa.Float(), nullable=True),
        sa.Column("market_prob", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("floor_strike", sa.Float(), nullable=True),
        sa.Column("cap_strike", sa.Float(), nullable=True),
        sa.Column("strike_type", sa.String(16), nullable=True),
        sa.Column("underlying_price", sa.Float(), nullable=True),
        sa.Column("realized_vol", sa.Float(), nullable=True),
        sa.Column("exchange_order_id", sa.String(64), nullable=True),
        sa.Column("fill_price", sa.Float(), nullable=True),
        sa.Column("fill_quantity", sa.Float(), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("pnl_usd", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("market_ticker", sa.String(64), nullable=True),
        sa.Column("event_ticker", sa.String(64), nullable=True),
        sa.Column("expiry_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
