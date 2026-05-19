"""add cap_strike to opportunities and signals

Revision ID: a7c3e1f89b02
Revises: 43db626fce17
Create Date: 2026-05-19 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c3e1f89b02"
down_revision: Union[str, None] = "43db626fce17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("cap_strike", sa.Float(), nullable=True))
    op.add_column("signals", sa.Column("cap_strike", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("signals", "cap_strike")
    op.drop_column("opportunities", "cap_strike")
