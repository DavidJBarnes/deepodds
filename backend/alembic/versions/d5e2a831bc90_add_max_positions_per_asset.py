"""add max_positions_per_asset to bot_configs

Revision ID: d5e2a831bc90
Revises: c3a1f920d457
Create Date: 2026-05-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5e2a831bc90"
down_revision: Union[str, None] = "c3a1f920d457"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("max_positions_per_asset", sa.Integer(), nullable=False, server_default="3"))

def downgrade() -> None:
    op.drop_column("bot_configs", "max_positions_per_asset")
