"""add live_market_prob to signals

Revision ID: a1b2c3d4e5f6
Revises: 6c469c3a197a
Create Date: 2026-05-27 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '6c469c3a197a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('signals', sa.Column('live_market_prob', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('signals', 'live_market_prob')
