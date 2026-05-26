"""One-off repair: undo the never-filled-as-settled-loss bug.

Background
----------
Prior versions of sync_kalshi_live treated any market_ticker that appeared in
/portfolio/settlements as something we owned. For limit orders that placed
but never filled, Kalshi reports yes_count_fp=0 / revenue=0 / cost=0 — but
our sync still used the local cost_usd as the "loss," producing settled_loss
records for trades that never happened.

This script:
1. Pulls /portfolio/settlements for each user with Kalshi keys
2. Identifies any local signal with status in (settled_win, settled_loss,
   settled_breakeven) whose corresponding Kalshi settlement has zero
   contracts on both sides
3. Marks them as cancelled with zeroed P&L

Idempotent. Safe to re-run.
"""

import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.async_util import run_async
from app.models.signal import Signal
from app.models.user import User
from app.services.kalshi_client import KalshiClient


SETTLED_STATUSES = ("settled_win", "settled_loss", "settled_breakeven")


def _zero_position(s: dict) -> bool:
    def _f(key):
        try:
            return float(s.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0
    return (
        _f("yes_count_fp") == 0
        and _f("no_count_fp") == 0
        and _f("yes_total_cost_dollars") == 0
        and _f("no_total_cost_dollars") == 0
    )


def repair():
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_size=2, max_overflow=2)
    fixed = 0
    inspected = 0

    with Session(engine) as session:
        users = session.execute(
            select(User).where(
                User.kalshi_api_key_id.isnot(None),
                User.kalshi_private_key.isnot(None),
            )
        ).scalars().all()

        for user in users:
            try:
                client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
            except Exception as e:
                print(f"skip user {user.email}: {e}")
                continue

            try:
                settlements = run_async(client.get_settlements(limit=200))
            except Exception as e:
                print(f"failed to fetch settlements for {user.email}: {e}")
                continue

            never_filled_tickers = {
                s.get("ticker") for s in settlements if _zero_position(s)
            }

            if not never_filled_tickers:
                print(f"{user.email}: no never-filled settlements")
                continue

            local = session.execute(
                select(Signal).where(
                    Signal.user_id == user.id,
                    Signal.venue == "kalshi",
                    Signal.status.in_(SETTLED_STATUSES),
                    Signal.market_ticker.in_(never_filled_tickers),
                )
            ).scalars().all()

            for sig in local:
                inspected += 1
                print(
                    f"  repairing {sig.market_ticker}: was {sig.status} "
                    f"with pnl=${sig.pnl_usd}, cost=${sig.cost_usd}"
                )
                sig.status = "cancelled"
                sig.error_message = "order_never_filled_before_settlement (repaired)"
                sig.pnl_usd = None
                sig.pnl_pct = None
                sig.exit_price = None
                fixed += 1

        if fixed:
            session.commit()

    print()
    print(f"Repaired {fixed} signals across {inspected} inspected.")
    return 0 if fixed >= 0 else 1


if __name__ == "__main__":
    sys.exit(repair())
