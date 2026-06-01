"""add model versioning columns to model_train_history

Revision ID: b8c9d0e1f2g3
Revises: a9b0c1d2e3f4
Create Date: 2026-06-01 18:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8c9d0e1f2g3"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_train_history",
        sa.Column("crypto_model_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "model_train_history",
        sa.Column("climate_model_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "model_train_history",
        sa.Column(
            "crypto_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "model_train_history",
        sa.Column(
            "climate_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Only one row may be active per venue.
    op.create_index(
        "uq_model_train_history_crypto_active",
        "model_train_history",
        ["crypto_active"],
        unique=True,
        postgresql_where=sa.text("crypto_active IS TRUE"),
    )
    op.create_index(
        "uq_model_train_history_climate_active",
        "model_train_history",
        ["climate_active"],
        unique=True,
        postgresql_where=sa.text("climate_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_train_history_climate_active", table_name="model_train_history")
    op.drop_index("uq_model_train_history_crypto_active", table_name="model_train_history")
    op.drop_column("model_train_history", "climate_active")
    op.drop_column("model_train_history", "crypto_active")
    op.drop_column("model_train_history", "climate_model_path")
    op.drop_column("model_train_history", "crypto_model_path")
