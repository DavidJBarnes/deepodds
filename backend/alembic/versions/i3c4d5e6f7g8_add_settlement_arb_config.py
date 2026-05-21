"""add settlement_arb_* columns to bot_configs

Revision ID: i3c4d5e6f7g8
Revises: h2b3c4d5e6f7
Create Date: 2026-05-21
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "i3c4d5e6f7g8"
down_revision: Union[str, None] = "h2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("settlement_arb_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("bot_configs", sa.Column("settlement_arb_max_minutes", sa.Integer(), server_default="60", nullable=False))
    op.add_column("bot_configs", sa.Column("settlement_arb_min_sigma", sa.Float(), server_default="1.5", nullable=False))
    op.add_column("bot_configs", sa.Column("settlement_arb_min_discount_cents", sa.Integer(), server_default="5", nullable=False))
    op.add_column("bot_configs", sa.Column("settlement_arb_max_position_cents", sa.Integer(), server_default="5000", nullable=False))


def downgrade() -> None:
    op.drop_column("bot_configs", "settlement_arb_max_position_cents")
    op.drop_column("bot_configs", "settlement_arb_min_discount_cents")
    op.drop_column("bot_configs", "settlement_arb_min_sigma")
    op.drop_column("bot_configs", "settlement_arb_max_minutes")
    op.drop_column("bot_configs", "settlement_arb_enabled")
