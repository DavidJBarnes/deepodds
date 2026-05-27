"""adjust default values: min_edge=0.05, take_profit=0.20, min_volume=500

Revision ID: 6c469c3a197a
Revises: 662eae6b3376
Create Date: 2026-05-27 12:18:37.461534

"""
from typing import Sequence, Union

from alembic import op


revision: str = '6c469c3a197a'
down_revision: Union[str, None] = '662eae6b3376'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE kalshi_configs SET min_edge = 0.05 WHERE min_edge = 0.08"
    )
    op.execute(
        "UPDATE kalshi_configs SET take_profit_pct = 0.20 WHERE take_profit_pct = 0.0"
    )
    op.execute(
        "UPDATE kalshi_configs SET min_volume_24h = 500 WHERE min_volume_24h = 100"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE kalshi_configs SET min_edge = 0.08 WHERE min_edge = 0.05"
    )
    op.execute(
        "UPDATE kalshi_configs SET take_profit_pct = 0.0 WHERE take_profit_pct = 0.20"
    )
    op.execute(
        "UPDATE kalshi_configs SET min_volume_24h = 100 WHERE min_volume_24h = 500"
    )
