"""add trailing stop and fee tracking columns

Revision ID: g1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-21
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("max_unrealized_cents", sa.Integer(), nullable=True))
    op.add_column("spot_positions", sa.Column("peak_pnl_pct", sa.Float(), nullable=True))
    op.add_column("spot_trades", sa.Column("fee_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("spot_trades", "fee_usd")
    op.drop_column("spot_positions", "peak_pnl_pct")
    op.drop_column("signals", "max_unrealized_cents")
