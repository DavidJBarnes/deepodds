"""add model_train_history table

Revision ID: a9b0c1d2e3f4
Revises: e1a2b3c4d5f6
Create Date: 2026-05-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_train_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("model_type", sa.String(length=20), nullable=False),
        sa.Column("crypto_ok", sa.Boolean(), nullable=True),
        sa.Column("climate_ok", sa.Boolean(), nullable=True),
        sa.Column("crypto_size_kb", sa.Float(), nullable=True),
        sa.Column("climate_size_kb", sa.Float(), nullable=True),
        sa.Column("total_size_kb", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_train_history_user_id"),
        "model_train_history",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_train_history_user_id"), table_name="model_train_history")
    op.drop_table("model_train_history")
