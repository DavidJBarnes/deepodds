"""kalshi: add max_positions_per_event

Revision ID: y7z8a9b0c1d2
Revises: x6y7z8a9b0c1
Create Date: 2026-05-26 19:00:00.000000+00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "y7z8a9b0c1d2"
down_revision = "x6y7z8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kalshi_configs",
        sa.Column("max_positions_per_event", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("kalshi_configs", "max_positions_per_event")
