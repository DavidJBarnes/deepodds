"""add kalshi_result column to signals

Revision ID: j3d4e5f6g7h8
Revises: i3c4d5e6f7g8
Create Date: 2026-05-22
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "j3d4e5f6g7h8"
down_revision: Union[str, None] = "i3c4d5e6f7g8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("kalshi_result", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("signals", "kalshi_result")
