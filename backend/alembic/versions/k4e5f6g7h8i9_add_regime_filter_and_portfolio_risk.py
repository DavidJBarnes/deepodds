"""add regime filter and portfolio risk columns to bot_configs

Revision ID: k4e5f6g7h8i9
Revises: j3d4e5f6g7h8
Create Date: 2026-05-22
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "k4e5f6g7h8i9"
down_revision: Union[str, None] = "j3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("settlement_arb_regime_filter", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("bot_configs", sa.Column("settlement_arb_min_fear_greed", sa.Integer(), server_default="25", nullable=False))
    op.add_column("bot_configs", sa.Column("max_portfolio_risk_cents", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("bot_configs", "max_portfolio_risk_cents")
    op.drop_column("bot_configs", "settlement_arb_min_fear_greed")
    op.drop_column("bot_configs", "settlement_arb_regime_filter")
