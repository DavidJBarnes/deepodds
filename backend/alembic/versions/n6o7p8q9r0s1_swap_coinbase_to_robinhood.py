"""swap coinbase to robinhood

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa

revision = "n6o7p8q9r0s1"
down_revision = "m5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = [r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
    ))]

    if "coinbase_api_key" in cols:
        op.execute("ALTER TABLE users RENAME COLUMN coinbase_api_key TO robinhood_api_key")
    elif "robinhood_api_key" not in cols:
        op.add_column("users", sa.Column("robinhood_api_key", sa.String(256), nullable=True))

    if "coinbase_private_key" in cols:
        op.execute("ALTER TABLE users RENAME COLUMN coinbase_private_key TO robinhood_private_key")
    elif "robinhood_private_key" not in cols:
        op.add_column("users", sa.Column("robinhood_private_key", sa.Text, nullable=True))

    sig_cols = [r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='signals'"
    ))]
    if "coinbase_order_id" in sig_cols:
        op.execute("ALTER TABLE signals RENAME COLUMN coinbase_order_id TO exchange_order_id")
    elif "exchange_order_id" not in sig_cols:
        op.add_column("signals", sa.Column("exchange_order_id", sa.String(256), nullable=True))

    arch_cols = [r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='archived_signals'"
    ))]
    if "coinbase_order_id" in arch_cols:
        op.execute("ALTER TABLE archived_signals RENAME COLUMN coinbase_order_id TO exchange_order_id")
    elif "exchange_order_id" not in arch_cols:
        op.add_column("archived_signals", sa.Column("exchange_order_id", sa.String(256), nullable=True))


def downgrade() -> None:
    op.execute("ALTER TABLE users RENAME COLUMN robinhood_api_key TO coinbase_api_key")
    op.execute("ALTER TABLE users RENAME COLUMN robinhood_private_key TO coinbase_private_key")
    op.execute("ALTER TABLE signals RENAME COLUMN exchange_order_id TO coinbase_order_id")
    op.execute("ALTER TABLE archived_signals RENAME COLUMN exchange_order_id TO coinbase_order_id")
