"""fix column renames that silently failed

Revision ID: o7p8q9r0s1t2
Revises: n6o7p8q9r0s1
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa

revision = "o7p8q9r0s1t2"
down_revision = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    cols = [r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
    ))]
    if "coinbase_api_key" in cols:
        conn.execute(sa.text("ALTER TABLE users RENAME COLUMN coinbase_api_key TO robinhood_api_key"))
    if "coinbase_private_key" in cols:
        conn.execute(sa.text("ALTER TABLE users RENAME COLUMN coinbase_private_key TO robinhood_private_key"))

    sig_cols = [r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='signals'"
    ))]
    if "coinbase_order_id" in sig_cols:
        conn.execute(sa.text("ALTER TABLE signals RENAME COLUMN coinbase_order_id TO exchange_order_id"))

    arch_cols = [r[0] for r in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='archived_signals'"
    ))]
    if "coinbase_order_id" in arch_cols:
        conn.execute(sa.text("ALTER TABLE archived_signals RENAME COLUMN coinbase_order_id TO exchange_order_id"))


def downgrade() -> None:
    pass
