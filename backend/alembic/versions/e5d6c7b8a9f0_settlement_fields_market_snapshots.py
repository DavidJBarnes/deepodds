"""add status/result/last_price to market_snapshots

Lets the scanner exit loop read settlement state from MarketSnapshot
instead of making per-ticker Kalshi API calls (which were 4xx-ing in
production for every open position every 15s).

Revision ID: e5d6c7b8a9f0
Revises: c9d0e1f2g3h4
Create Date: 2026-06-05 16:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5d6c7b8a9f0"
down_revision: Union[str, None] = "c9d0e1f2g3h4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("market_snapshots", sa.Column("status", sa.Text(), nullable=True))
    op.add_column("market_snapshots", sa.Column("result", sa.Text(), nullable=True))
    op.add_column("market_snapshots", sa.Column("last_price", sa.Double(), nullable=True))


def downgrade() -> None:
    op.drop_column("market_snapshots", "last_price")
    op.drop_column("market_snapshots", "result")
    op.drop_column("market_snapshots", "status")
