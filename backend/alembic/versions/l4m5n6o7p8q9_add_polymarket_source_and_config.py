"""add polymarket source column and config fields

Revision ID: l4m5n6o7p8q9
Revises: k4e5f6g7h8i9
Create Date: 2026-05-22
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "l4m5n6o7p8q9"
down_revision: Union[str, None] = "k4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("source", sa.String(16), server_default="kalshi", nullable=False))
    op.add_column("bot_configs", sa.Column("polymarket_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("bot_configs", sa.Column("polymarket_min_edge_cents", sa.Float(), server_default="3", nullable=False))
    op.add_column("bot_configs", sa.Column("polymarket_max_exposure_cents", sa.Integer(), server_default="5000", nullable=False))
    op.add_column("bot_configs", sa.Column("polymarket_min_liquidity", sa.Float(), server_default="100", nullable=False))


def downgrade() -> None:
    op.drop_column("bot_configs", "polymarket_min_liquidity")
    op.drop_column("bot_configs", "polymarket_max_exposure_cents")
    op.drop_column("bot_configs", "polymarket_min_edge_cents")
    op.drop_column("bot_configs", "polymarket_enabled")
    op.drop_column("opportunities", "source")
