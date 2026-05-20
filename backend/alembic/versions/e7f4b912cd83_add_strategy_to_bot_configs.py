"""add strategy to bot_configs

Revision ID: e7f4b912cd83
Revises: d5e2a831bc90
Create Date: 2026-05-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7f4b912cd83"
down_revision: Union[str, None] = "d5e2a831bc90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("strategy", sa.String(16), nullable=False, server_default="model"))


def downgrade() -> None:
    op.drop_column("bot_configs", "strategy")
