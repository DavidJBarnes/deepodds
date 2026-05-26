"""audit: add max_cost_per_signal, min_hold_minutes, update defaults

Revision ID: x6y7z8a9b0c1
Revises: w5x6y7z8a9b0
Create Date: 2026-05-26 18:00:00.000000+00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "x6y7z8a9b0c1"
down_revision = "w5x6y7z8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kalshi_configs", sa.Column("max_cost_per_signal", sa.Float(), nullable=False, server_default="25.0"))
    op.add_column("bot_configs", sa.Column("min_hold_minutes", sa.Integer(), nullable=False, server_default="30"))

    op.alter_column("kalshi_configs", "min_volume_24h", server_default="100")
    op.alter_column("kalshi_configs", "max_price", server_default="0.80")
    op.alter_column("kalshi_configs", "min_hours_to_expiry", server_default="1")
    op.alter_column("kalshi_configs", "min_edge", server_default="0.07")


def downgrade() -> None:
    op.alter_column("kalshi_configs", "min_edge", server_default="0.05")
    op.alter_column("kalshi_configs", "min_hours_to_expiry", server_default="2")
    op.alter_column("kalshi_configs", "max_price", server_default="0.95")
    op.alter_column("kalshi_configs", "min_volume_24h", server_default="0")

    op.drop_column("bot_configs", "min_hold_minutes")
    op.drop_column("kalshi_configs", "max_cost_per_signal")
