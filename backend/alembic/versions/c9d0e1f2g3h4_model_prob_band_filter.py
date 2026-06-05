"""add min/max model_prob band filter to crypto + climate configs

Revision ID: c9d0e1f2g3h4
Revises: bab57efbd7bd
Create Date: 2026-06-05 00:35:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9d0e1f2g3h4"
down_revision: Union[str, None] = "bab57efbd7bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("crypto_configs", "climate_configs"):
        op.add_column(
            table,
            sa.Column("min_model_prob", sa.Float(), nullable=False, server_default="0.0"),
        )
        op.add_column(
            table,
            sa.Column("max_model_prob", sa.Float(), nullable=False, server_default="0.80"),
        )


def downgrade() -> None:
    for table in ("crypto_configs", "climate_configs"):
        op.drop_column(table, "max_model_prob")
        op.drop_column(table, "min_model_prob")
