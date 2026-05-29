"""rename kalshi_configs -> crypto_configs and venue values

Revision ID: d9e8f1a2b3c4
Revises: c8873adeb3e4
Create Date: 2026-05-29 09:00:00.000000

Renames:
- table kalshi_configs -> crypto_configs
- index ix_kalshi_configs_user_id -> ix_crypto_configs_user_id
- signals.venue value 'kalshi' -> 'kalshi_crypto'
- signals.venue value 'climate' -> 'kalshi_climate'
- signals.venue server_default 'kalshi' -> 'kalshi_crypto'
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e8f1a2b3c4"
down_revision: Union[str, None] = "c8873adeb3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("kalshi_configs", "crypto_configs")
    op.execute("ALTER INDEX ix_kalshi_configs_user_id RENAME TO ix_crypto_configs_user_id")

    op.execute("UPDATE signals SET venue = 'kalshi_crypto' WHERE venue = 'kalshi'")
    op.execute("UPDATE signals SET venue = 'kalshi_climate' WHERE venue = 'climate'")

    op.alter_column(
        "signals",
        "venue",
        existing_type=sa.String(length=16),
        server_default="kalshi_crypto",
        existing_server_default="kalshi",
    )


def downgrade() -> None:
    op.alter_column(
        "signals",
        "venue",
        existing_type=sa.String(length=16),
        server_default="kalshi",
        existing_server_default="kalshi_crypto",
    )

    op.execute("UPDATE signals SET venue = 'climate' WHERE venue = 'kalshi_climate'")
    op.execute("UPDATE signals SET venue = 'kalshi' WHERE venue = 'kalshi_crypto'")

    op.execute("ALTER INDEX ix_crypto_configs_user_id RENAME TO ix_kalshi_configs_user_id")
    op.rename_table("crypto_configs", "kalshi_configs")
