"""add pair_configs table for per-pair overrides

Revision ID: t2u3v4w5x6y7
Revises: s1t2u3v4w5x6
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "t2u3v4w5x6y7"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pair_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("venue", sa.String(16), nullable=False),
        sa.Column("pair", sa.String(64), nullable=False),
        sa.Column("entry_z_score", sa.Float(), nullable=True),
        sa.Column("exit_z_score", sa.Float(), nullable=True),
        sa.Column("position_size_usd", sa.Float(), nullable=True),
        sa.Column("contracts_per_signal", sa.Integer(), nullable=True),
        sa.Column("stop_loss_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "venue", "pair", name="uq_pair_config_user_venue_pair"),
    )
    op.create_index("ix_pair_configs_user_id", "pair_configs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_pair_configs_user_id")
    op.drop_table("pair_configs")
