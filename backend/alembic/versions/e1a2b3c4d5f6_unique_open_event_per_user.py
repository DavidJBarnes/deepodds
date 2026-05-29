"""unique partial index: at most one open signal per (user, event)

Revision ID: e1a2b3c4d5f6
Revises: d9e8f1a2b3c4
Create Date: 2026-05-29 11:30:00.000000

Prevents the race where two scheduler loops briefly overlap during a
reload and each creates a signal for the same event before either commits.
The partial index only covers rows whose status indicates the position is
still open (signaled / placed / filled), so settled / cancelled rows
don't block new entries for the same event later.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, None] = "d9e8f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_signals_open_per_event
        ON signals (user_id, event_ticker)
        WHERE status IN ('signaled', 'placed', 'filled')
          AND event_ticker IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_signals_open_per_event")
