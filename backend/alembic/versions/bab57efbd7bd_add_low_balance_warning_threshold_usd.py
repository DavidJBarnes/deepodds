"""add low_balance_warning_threshold_usd to crypto_configs and climate_configs

Revision ID: bab57efbd7bd
Revises: b0c1d2e3f4g5
Create Date: 2026-06-04 17:29:40.216396

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bab57efbd7bd'
down_revision: Union[str, None] = 'b0c1d2e3f4g5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'climate_configs',
        sa.Column('low_balance_warning_threshold_usd', sa.Float(), nullable=False, server_default='20.0'),
    )
    op.add_column(
        'crypto_configs',
        sa.Column('low_balance_warning_threshold_usd', sa.Float(), nullable=False, server_default='20.0'),
    )


def downgrade() -> None:
    op.drop_column('crypto_configs', 'low_balance_warning_threshold_usd')
    op.drop_column('climate_configs', 'low_balance_warning_threshold_usd')
