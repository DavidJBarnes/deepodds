"""drop_crypto_columns

Revision ID: b346378a74ea
Revises: z8a9b0c1d2e3
Create Date: 2026-05-26 18:16:28.676170

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b346378a74ea"
down_revision: Union[str, None] = "z8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop bot_configs table (model was deleted; table still exists in DB)
    op.drop_index("ix_bot_configs_user_id", table_name="bot_configs")
    op.drop_table("bot_configs")

    # Rename coinbase_order_id -> exchange_order_id (preserves data)
    op.alter_column("signals", "coinbase_order_id", new_column_name="exchange_order_id")
    op.alter_column(
        "archived_signals", "coinbase_order_id", new_column_name="exchange_order_id"
    )

    # Drop unused crypto columns from signals
    op.drop_column("signals", "z_score")
    op.drop_column("signals", "exit_z_score")
    op.drop_column("signals", "vwap")

    # Drop unused crypto columns from archived_signals
    op.drop_column("archived_signals", "z_score")
    op.drop_column("archived_signals", "exit_z_score")
    op.drop_column("archived_signals", "vwap")

    # Drop unused crypto columns from pair_configs
    op.drop_column("pair_configs", "entry_z_score")
    op.drop_column("pair_configs", "exit_z_score")
    op.drop_column("pair_configs", "position_size_usd")

    # Drop unused crypto columns from users
    op.drop_column("users", "coinbase_api_key")
    op.drop_column("users", "coinbase_private_key")


def downgrade() -> None:
    # Restore users columns
    op.add_column(
        "users",
        sa.Column("coinbase_private_key", sa.TEXT(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("coinbase_api_key", sa.VARCHAR(length=256), nullable=True),
    )

    # Restore pair_configs columns
    op.add_column(
        "pair_configs",
        sa.Column(
            "position_size_usd", sa.DOUBLE_PRECISION(precision=53), nullable=True
        ),
    )
    op.add_column(
        "pair_configs",
        sa.Column(
            "entry_z_score", sa.DOUBLE_PRECISION(precision=53), nullable=True
        ),
    )
    op.add_column(
        "pair_configs",
        sa.Column(
            "exit_z_score", sa.DOUBLE_PRECISION(precision=53), nullable=True
        ),
    )

    # Restore signals columns
    op.add_column(
        "signals",
        sa.Column("vwap", sa.DOUBLE_PRECISION(precision=53), nullable=True),
    )
    op.add_column(
        "signals",
        sa.Column(
            "exit_z_score", sa.DOUBLE_PRECISION(precision=53), nullable=True
        ),
    )
    op.add_column(
        "signals",
        sa.Column("z_score", sa.DOUBLE_PRECISION(precision=53), nullable=True),
    )
    op.alter_column("signals", "exchange_order_id", new_column_name="coinbase_order_id")

    # Restore archived_signals columns
    op.add_column(
        "archived_signals",
        sa.Column("vwap", sa.DOUBLE_PRECISION(precision=53), nullable=True),
    )
    op.add_column(
        "archived_signals",
        sa.Column(
            "exit_z_score", sa.DOUBLE_PRECISION(precision=53), nullable=True
        ),
    )
    op.add_column(
        "archived_signals",
        sa.Column(
            "z_score", sa.DOUBLE_PRECISION(precision=53), nullable=True
        ),
    )
    op.alter_column(
        "archived_signals", "exchange_order_id", new_column_name="coinbase_order_id"
    )

    # Restore bot_configs table
    op.create_table(
        "bot_configs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "mode",
            sa.VARCHAR(length=8),
            server_default=sa.text("'paper'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.BOOLEAN(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "pairs",
            sa.VARCHAR(length=128),
            server_default=sa.text("'BTC-USD,ETH-USD'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "lookback_periods",
            sa.INTEGER(),
            server_default=sa.text("16"),
            nullable=False,
        ),
        sa.Column(
            "entry_z_score",
            sa.DOUBLE_PRECISION(precision=53),
            server_default=sa.text("'-2'::double precision"),
            nullable=False,
        ),
        sa.Column(
            "exit_z_score",
            sa.DOUBLE_PRECISION(precision=53),
            server_default=sa.text("'0'::double precision"),
            nullable=False,
        ),
        sa.Column(
            "position_size_usd",
            sa.DOUBLE_PRECISION(precision=53),
            server_default=sa.text("'25'::double precision"),
            nullable=False,
        ),
        sa.Column(
            "max_open_positions",
            sa.INTEGER(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "stop_loss_pct",
            sa.DOUBLE_PRECISION(precision=53),
            server_default=sa.text("'3'::double precision"),
            nullable=False,
        ),
        sa.Column(
            "daily_loss_limit_usd",
            sa.DOUBLE_PRECISION(precision=53),
            server_default=sa.text("'50'::double precision"),
            nullable=False,
        ),
        sa.Column(
            "max_signals_per_hour",
            sa.INTEGER(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "min_hold_minutes",
            sa.INTEGER(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bot_configs_user_id", "bot_configs", ["user_id"], unique=True)
