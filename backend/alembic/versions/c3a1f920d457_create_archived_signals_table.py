"""create archived_signals table

Revision ID: c3a1f920d457
Revises: a7c3e1f89b02
Create Date: 2026-05-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "c3a1f920d457"
down_revision: Union[str, None] = "a7c3e1f89b02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "archived_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("original_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("opportunity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ticker", sa.String(64), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("limit_price_cents", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("signal_type", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("model_prob", sa.Float(), nullable=True),
        sa.Column("model_fair_cents", sa.Float(), nullable=True),
        sa.Column("model_edge_cents", sa.Float(), nullable=True),
        sa.Column("edge_tier", sa.String(16), nullable=True),
        sa.Column("implied_vol", sa.Float(), nullable=True),
        sa.Column("market_yes_price_cents", sa.Float(), nullable=True),
        sa.Column("spot_price", sa.Float(), nullable=True),
        sa.Column("strike_price", sa.Float(), nullable=True),
        sa.Column("cap_strike", sa.Float(), nullable=True),
        sa.Column("kalshi_order_id", sa.String(256), nullable=True),
        sa.Column("fill_price_cents", sa.Integer(), nullable=True),
        sa.Column("fill_quantity", sa.Integer(), nullable=True),
        sa.Column("exit_price_cents", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_side", sa.String(8), nullable=True),
        sa.Column("pnl_cents", sa.Integer(), nullable=True),
        sa.Column("close_time", sa.String(64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("run_id", sa.String(64), nullable=False, index=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("archived_signals")
