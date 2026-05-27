"""add take_profit_pct to kalshi_configs

Revision ID: c4d5e6f7g8h9
Revises: b346378a74ea
Create Date: 2026-05-26 19:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7g8h9"
down_revision: Union[str, None] = "b346378a74ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "kalshi_configs",
        sa.Column("take_profit_pct", sa.Float(), server_default="0.0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("kalshi_configs", "take_profit_pct")
