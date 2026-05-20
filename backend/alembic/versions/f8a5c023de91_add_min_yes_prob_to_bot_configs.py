"""add min_yes_prob to bot_configs

Revision ID: f8a5c023de91
Revises: e7f4b912cd83
Create Date: 2026-05-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "f8a5c023de91"
down_revision: Union[str, None] = "e7f4b912cd83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("min_yes_prob", sa.Integer(), nullable=False, server_default="20"))


def downgrade() -> None:
    op.drop_column("bot_configs", "min_yes_prob")
