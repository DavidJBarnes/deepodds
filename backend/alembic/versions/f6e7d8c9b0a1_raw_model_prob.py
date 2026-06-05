"""add raw_model_prob to signals + market_snapshots

The XGBoost output (pre-Platt) is preserved alongside the
Platt-calibrated value so future Platt refits don't degenerate by
fitting on already-calibrated data. The existing model_prob column
continues to hold the calibrated value used for edge calc and signal
gating; raw_model_prob is used only by the calibration training query.

Backfill: rows created before the first prod Platt fit
(2026-06-05 15:33 UTC) have raw values stored on model_prob (Platt
didn't exist yet); copy those into raw_model_prob so the next fit has
its full training set. Rows after that cutoff get NULL raw_model_prob
— they'll be populated going forward by predict_climate_probability.

Revision ID: f6e7d8c9b0a1
Revises: e5d6c7b8a9f0
Create Date: 2026-06-05 17:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6e7d8c9b0a1"
down_revision: Union[str, None] = "e5d6c7b8a9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLATT_FIRST_FIT = "2026-06-05 15:33:00+00:00"


def upgrade() -> None:
    op.add_column("signals", sa.Column("raw_model_prob", sa.Double(), nullable=True))
    op.add_column("market_snapshots", sa.Column("raw_model_prob", sa.Double(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE signals SET raw_model_prob = model_prob "
            "WHERE model_prob IS NOT NULL AND created_at < :cutoff"
        ).bindparams(cutoff=PLATT_FIRST_FIT)
    )
    op.execute(
        sa.text(
            "UPDATE market_snapshots SET raw_model_prob = model_prob "
            "WHERE model_prob IS NOT NULL AND scored_at < :cutoff"
        ).bindparams(cutoff=PLATT_FIRST_FIT)
    )


def downgrade() -> None:
    op.drop_column("market_snapshots", "raw_model_prob")
    op.drop_column("signals", "raw_model_prob")
