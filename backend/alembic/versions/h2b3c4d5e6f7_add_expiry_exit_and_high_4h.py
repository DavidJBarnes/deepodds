"""add expiry_exit_minutes to bot_configs

Revision ID: h2b3c4d5e6f7
Revises: g1a2b3c4d5e6
Create Date: 2026-05-21
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "h2b3c4d5e6f7"
down_revision: Union[str, None] = "g1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("expiry_exit_minutes", sa.Integer(), server_default="15", nullable=False))


def downgrade() -> None:
    op.drop_column("bot_configs", "expiry_exit_minutes")
