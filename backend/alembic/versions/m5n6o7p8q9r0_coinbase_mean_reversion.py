"""replace kalshi/polymarket with coinbase mean reversion

Revision ID: m5n6o7p8q9r0
Revises: k4e5f6g7h8i9
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "m5n6o7p8q9r0"
down_revision = "k4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop signals first (has FK to opportunities), then opportunities and spot tables
    op.drop_table("signals")
    op.drop_table("opportunities")
    op.execute("DROP TABLE IF EXISTS spot_positions CASCADE")
    op.execute("DROP TABLE IF EXISTS spot_trades CASCADE")

    op.create_table(
        "signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("pair", sa.String(16), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("signal_type", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="signaled", index=True),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("z_score", sa.Float, nullable=True),
        sa.Column("vwap", sa.Float, nullable=True),
        sa.Column("coinbase_order_id", sa.String(256), nullable=True),
        sa.Column("fill_price", sa.Float, nullable=True),
        sa.Column("fill_quantity", sa.Float, nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("exit_z_score", sa.Float, nullable=True),
        sa.Column("pnl_usd", sa.Float, nullable=True),
        sa.Column("pnl_pct", sa.Float, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Archived signals: drop and recreate ---
    op.drop_table("archived_signals")
    op.create_table(
        "archived_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("original_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("pair", sa.String(16), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("signal_type", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("z_score", sa.Float, nullable=True),
        sa.Column("vwap", sa.Float, nullable=True),
        sa.Column("coinbase_order_id", sa.String(256), nullable=True),
        sa.Column("fill_price", sa.Float, nullable=True),
        sa.Column("fill_quantity", sa.Float, nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("exit_z_score", sa.Float, nullable=True),
        sa.Column("pnl_usd", sa.Float, nullable=True),
        sa.Column("pnl_pct", sa.Float, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("run_id", sa.String(64), nullable=False, index=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Bot configs: drop and recreate ---
    op.drop_table("bot_configs")
    op.create_table(
        "bot_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, unique=True, index=True),
        sa.Column("mode", sa.String(8), nullable=False, server_default="paper"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("pairs", sa.String(128), nullable=False, server_default="BTC-USD,ETH-USD"),
        sa.Column("lookback_periods", sa.Integer, nullable=False, server_default="16"),
        sa.Column("entry_z_score", sa.Float, nullable=False, server_default="-2.0"),
        sa.Column("exit_z_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("position_size_usd", sa.Float, nullable=False, server_default="25.0"),
        sa.Column("max_open_positions", sa.Integer, nullable=False, server_default="3"),
        sa.Column("stop_loss_pct", sa.Float, nullable=False, server_default="3.0"),
        sa.Column("daily_loss_limit_usd", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("max_signals_per_hour", sa.Integer, nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Users: swap Kalshi keys for Coinbase keys (idempotent) ---
    conn = op.get_bind()
    cols = [r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
    ))]
    if "kalshi_api_key_id" in cols:
        op.drop_column("users", "kalshi_api_key_id")
    if "kalshi_api_private_key" in cols:
        op.drop_column("users", "kalshi_api_private_key")
    if "coinbase_api_key" not in cols:
        op.add_column("users", sa.Column("coinbase_api_key", sa.String(256), nullable=True))
    if "coinbase_private_key" not in cols:
        op.add_column("users", sa.Column("coinbase_private_key", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "coinbase_private_key")
    op.drop_column("users", "coinbase_api_key")
    op.add_column("users", sa.Column("kalshi_api_key_id", sa.String(256), nullable=True))
    op.add_column("users", sa.Column("kalshi_api_private_key", sa.Text, nullable=True))
    # Not recreating old table schemas in downgrade — use git to restore
