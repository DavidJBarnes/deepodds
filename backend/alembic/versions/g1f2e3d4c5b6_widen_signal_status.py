"""widen signals.status to varchar(48) for new rejection taxonomy

PR #168 added new status values:
- rejected_insufficient_funds (27 chars)
- rejected_rate_limit         (19 chars)
- expired_unfilled            (16 chars — fits but at the limit)

The column was VARCHAR(16) which truncates the longer values. The
constraint violation was being swallowed by SQLAlchemy session
machinery, leaving signals stuck in 'placed' state.

Revision ID: g1f2e3d4c5b6
Revises: f6e7d8c9b0a1
Create Date: 2026-06-05 18:15:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "g1f2e3d4c5b6"
down_revision: Union[str, None] = "f6e7d8c9b0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "signals", "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=48),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "signals", "status",
        existing_type=sa.String(length=48),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
