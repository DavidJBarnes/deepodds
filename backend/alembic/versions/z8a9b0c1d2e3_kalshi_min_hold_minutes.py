"""kalshi: add min_hold_minutes to guard edge_lost exits

Revision ID: z8a9b0c1d2e3
Revises: y7z8a9b0c1d2
Create Date: 2026-05-26 22:00:00.000000+00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "z8a9b0c1d2e3"
down_revision = "y7z8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kalshi_configs",
        sa.Column("min_hold_minutes", sa.Integer(), nullable=False, server_default="15"),
    )


def downgrade() -> None:
    op.drop_column("kalshi_configs", "min_hold_minutes")
