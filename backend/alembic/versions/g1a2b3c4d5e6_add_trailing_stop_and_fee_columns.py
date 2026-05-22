"""add trailing stop column to signals

Revision ID: g1a2b3c4d5e6
Revises: f8a5c023de91
Create Date: 2026-05-21
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, None] = "f8a5c023de91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("max_unrealized_cents", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("signals", "max_unrealized_cents")
