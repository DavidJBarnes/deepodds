"""One-shot: re-settle already-settled paper signals against Kalshi's outcome.

Background: paper-mode settlement used to fall back to the model's own
forecast when the Open-Meteo archive lagged, silently turning the
forecast into "ground truth" and inflating paper win rate. The new
settle_expired_*_paper functions read Kalshi instead, but already-settled
rows still carry the false outcomes.

This script walks every paper signal with status in ('settled_win',
'settled_loss', 'settled_breakeven'), looks up the current Kalshi
settlement, and rewrites exit_price / pnl_usd / pnl_pct / status if
they disagree. Rows whose Kalshi market hasn't actually settled yet are
left untouched (they'll be picked up on the next loop once Kalshi
settles them).

Run from inside the deepodds-api container:
    docker exec deepodds-api python scripts/resettle_paper_signals.py [--apply]

Defaults to dry-run. Pass --apply to write changes.
"""
import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.signal import Signal
from app.services.kalshi_utils import kalshi_yes_settlement

sync_engine = create_engine(settings.DATABASE_URL_SYNC)

SETTLED = ("settled_win", "settled_loss", "settled_breakeven")


def resettle(apply_changes: bool) -> None:
    flipped = 0
    confirmed = 0
    skipped_no_kalshi = 0
    skipped_no_ticker = 0
    skipped_non_binary = 0
    rows_seen = 0

    with Session(sync_engine) as session:
        rows = session.execute(
            select(Signal).where(
                Signal.signal_type == "paper",
                Signal.status.in_(SETTLED),
            ).order_by(Signal.resolved_at)
        ).scalars().all()

        for sig in rows:
            rows_seen += 1
            if not sig.market_ticker:
                skipped_no_ticker += 1
                continue

            # Only re-settle rows whose exit_price snapped to a binary
            # outcome — those are the ones the buggy settle path produced.
            # Take-profit / stop-loss exits at intermediate prices already
            # represent a real recorded exit and should stay untouched.
            if sig.exit_price not in (0.0, 1.0):
                skipped_non_binary += 1
                continue

            yes_won = kalshi_yes_settlement(sig.market_ticker)
            if yes_won is None:
                skipped_no_kalshi += 1
                continue

            true_exit = 1.0 if yes_won else 0.0
            true_status = "settled_win" if yes_won else "settled_loss"

            # Outcome already matches Kalshi — leave the row alone (preserve
            # whatever pnl was originally computed, including any historical
            # fee adjustments).
            current_exit = sig.exit_price if sig.exit_price is not None else -1.0
            if abs(current_exit - true_exit) < 1e-9:
                confirmed += 1
                continue

            old_status = sig.status
            old_pnl = sig.pnl_usd
            fill_price = sig.fill_price or 0
            qty = sig.fill_quantity or sig.quantity or 0
            new_pnl = (true_exit - fill_price) * qty
            kalshi_label = "YES" if yes_won else "NO"

            print(
                f"FLIP {sig.market_ticker}: "
                f"{old_status} ${old_pnl} -> {true_status} ${new_pnl:.2f} "
                f"(Kalshi={kalshi_label})"
            )

            if apply_changes:
                sig.exit_price = true_exit
                sig.pnl_usd = round(new_pnl, 4)
                sig.pnl_pct = (
                    round((true_exit - fill_price) / fill_price * 100, 2)
                    if fill_price > 0 else 0.0
                )
                sig.status = true_status
                sig.resolved_at = datetime.now(timezone.utc)

            flipped += 1

        if apply_changes:
            session.commit()

    mode = "APPLIED" if apply_changes else "DRY-RUN"
    print(
        f"\n[{mode}] seen={rows_seen} confirmed={confirmed} "
        f"flipped={flipped} skipped_unsettled={skipped_no_kalshi} "
        f"skipped_no_ticker={skipped_no_ticker} skipped_non_binary={skipped_non_binary}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes to the DB.")
    args = parser.parse_args()
    resettle(args.apply)
