"""scanner: market_snapshots, scanner_heartbeat, model_blobs tables

Revision ID: b0c1d2e3f4g5
Revises: z8a9b0c1d2e3
Create Date: 2026-06-03 22:00:00.000000+00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "b0c1d2e3f4g5"
down_revision = ("z8a9b0c1d2e3", "b8c9d0e1f2g3")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("series", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("ask_price", sa.Double(), nullable=False),
        sa.Column("ask_size", sa.Double(), nullable=True),
        sa.Column("bid_price", sa.Double(), nullable=True),
        sa.Column("mid_price", sa.Double(), nullable=True),
        sa.Column("spread_pct", sa.Double(), nullable=True),
        sa.Column("volume_24h", sa.Double(), nullable=True),
        sa.Column("hours_to_expiry", sa.Float(), nullable=True),
        sa.Column("expiry_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("floor_strike", sa.Double(), nullable=True),
        sa.Column("cap_strike", sa.Double(), nullable=True),
        sa.Column("strike_type", sa.Text(), server_default="between"),
        sa.Column("underlying_price", sa.Double(), nullable=True),
        sa.Column("realized_vol", sa.Double(), nullable=True),
        sa.Column("model_prob", sa.Double(), nullable=True),
        sa.Column("edge", sa.Double(), nullable=True),
        sa.Column("filter_reason", sa.Text(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "price_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("ticker"),
    )
    op.create_index("ix_snapshots_venue", "market_snapshots", ["venue"])
    op.create_index(
        "ix_snapshots_scored",
        "market_snapshots",
        ["venue", "edge"],
        postgresql_where=sa.text("edge IS NOT NULL AND filter_reason IS NULL"),
    )
    op.create_index(
        "ix_snapshots_unscored",
        "market_snapshots",
        ["venue", "discovered_at"],
        postgresql_where=sa.text("edge IS NULL"),
    )

    op.create_table(
        "scanner_heartbeat",
        sa.Column("id", sa.Integer(), primary_key=True, default=1),
        sa.Column(
            "last_beat",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="warming_up"),
        sa.Column("error", sa.Text(), nullable=True),
    )

    op.create_table(
        "model_blobs",
        sa.Column("venue", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("model_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("model_blobs")
    op.drop_table("scanner_heartbeat")
    op.drop_index("ix_snapshots_unscored", table_name="market_snapshots")
    op.drop_index("ix_snapshots_scored", table_name="market_snapshots")
    op.drop_index("ix_snapshots_venue", table_name="market_snapshots")
    op.drop_table("market_snapshots")
