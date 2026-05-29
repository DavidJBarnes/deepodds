"""Reconcile Kalshi-side state with local Signal records.

Live Kalshi orders go through these external states:

    placed -> filled -> settled (yes/no/void)

Our scanner only knows up to "placed". This module polls Kalshi's portfolio
endpoints to advance signals through "filled" and the terminal "settled_*"
statuses. Without this loop, signals get stuck at "placed" and dashboard
P&L diverges from reality.

Safety invariants:
- Only modify signals with status in ("placed", "filled"). Never touch
  signals that are already terminal (settled_*, cancelled).
- Never create new signals — settlements for tickers we don't track are
  logged and ignored (could be manual trades on Kalshi).
- Errors per signal don't abort the whole loop.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.signal import Signal
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

_PENDING_STATUSES = ("placed", "filled", "closing")
_TERMINAL_ORDER_STATUSES = ("canceled", "cancelled", "expired", "rejected")


def _to_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def sync_kalshi_live(
    session: Session,
    exchange_clients: dict[str, KalshiClient],
) -> dict[str, int]:
    """Advance open live Kalshi signals from Kalshi-side state.

    Returns counts of state transitions performed.
    """
    counts = {"filled": 0, "settled": 0, "cancelled": 0}

    pending = session.execute(
        select(Signal).where(
            Signal.venue == "kalshi_crypto",
            Signal.signal_type == "live",
            Signal.status.in_(_PENDING_STATUSES),
        )
    ).scalars().all()

    if not pending:
        return counts

    by_user: dict[str, list[Signal]] = {}
    for sig in pending:
        by_user.setdefault(str(sig.user_id), []).append(sig)

    for user_id, signals in by_user.items():
        client = exchange_clients.get(user_id)
        if not client:
            continue

        try:
            positions = run_async(client.get_positions())
            positions_by_ticker = {p.get("ticker"): p for p in positions}
        except Exception:
            logger.exception("Failed to fetch positions for user %s", user_id)
            positions_by_ticker = {}

        try:
            settlements = run_async(client.get_settlements(limit=100))
            settlements_by_ticker = {s.get("ticker"): s for s in settlements}
        except Exception:
            logger.exception("Failed to fetch settlements for user %s", user_id)
            settlements_by_ticker = {}

        for sig in signals:
            try:
                _sync_signal(sig, client, positions_by_ticker, settlements_by_ticker, counts)
            except Exception:
                logger.exception("Failed to sync signal %s (%s)", sig.id, sig.market_ticker)

    if any(counts.values()):
        session.commit()

    return counts


def _sync_signal(
    sig: Signal,
    client: KalshiClient,
    positions: dict,
    settlements: dict,
    counts: dict,
) -> None:
    ticker = sig.market_ticker
    if not ticker:
        return

    settlement = settlements.get(ticker)

    # "closing" signals: we sold and are waiting for confirmation.
    if sig.status == "closing":
        if settlement:
            yes_count = _to_float(settlement.get("yes_count_fp"))
            no_count = _to_float(settlement.get("no_count_fp"))
            yes_cost = _to_float(settlement.get("yes_total_cost_dollars"))
            no_cost = _to_float(settlement.get("no_total_cost_dollars"))
            if yes_count == 0 and no_count == 0 and yes_cost == 0 and no_cost == 0:
                # Our sell order cleared before settlement — finalize via exit_price.
                _finalize_closing(sig, counts)
            else:
                # We still held at settlement — apply standard settlement logic.
                _apply_settlement(sig, settlement, counts)
        else:
            # No settlement yet — check if the sell order removed the position.
            _check_closing(sig, positions, counts)
        return

    if settlement:
        _apply_settlement(sig, settlement, counts)
        return

    if sig.status == "placed":
        position = positions.get(ticker)
        if position and _to_float(position.get("position_fp")) > 0:
            _apply_fill_from_position(sig, position, counts)
            return

        order_id = sig.exchange_order_id
        if not order_id:
            return

        try:
            order = run_async(client.get_order(order_id))
        except Exception:
            logger.warning("Failed to fetch order %s for %s", order_id, ticker)
            return

        order_status = (order.get("status") or "").lower()
        if order_status == "executed":
            _apply_fill_from_order(sig, order, counts)
        elif order_status in _TERMINAL_ORDER_STATUSES:
            sig.status = "cancelled"
            sig.error_message = f"order_status: {order_status}"
            counts["cancelled"] += 1


def _check_closing(sig: Signal, positions: dict, counts: dict) -> None:
    """Check if a closing signal's position has been removed on Kalshi."""
    position = positions.get(sig.market_ticker)
    pos_qty = _to_float(position.get("position_fp")) if position else 0
    if pos_qty <= 0:
        _finalize_closing(sig, counts)


def _finalize_closing(sig: Signal, counts: dict) -> None:
    """Record P&L for a closing signal whose sell order filled."""
    from datetime import datetime, timezone
    exit_p = sig.exit_price
    fill_p = sig.fill_price
    qty = sig.fill_quantity or sig.quantity or 0.0
    if exit_p and fill_p and qty > 0:
        pnl = (exit_p - fill_p) * qty
        sig.pnl_usd = round(pnl, 4)
        sig.pnl_pct = round((exit_p - fill_p) / fill_p * 100, 2) if fill_p > 0 else 0.0
        sig.resolved_at = datetime.now(timezone.utc)
        sig.status = "settled_win" if pnl >= 0 else "settled_loss"
        counts["settled"] += 1
        logger.info(
            "Kalshi sync closing->settled %s: exit=$%.2f fill=$%.2f qty=%.0f P&L=$%.4f",
            sig.market_ticker, exit_p, fill_p, qty, pnl,
        )


def _apply_fill_from_position(sig: Signal, position: dict, counts: dict) -> None:
    qty = _to_float(position.get("position_fp"))
    total_cost = _to_float(position.get("total_traded_dollars"))
    if qty <= 0:
        return

    if total_cost > 0:
        fill_price = total_cost / qty
    else:
        fill_price = _to_float(sig.entry_price)

    sig.status = "filled"
    sig.fill_price = round(fill_price, 4)
    sig.fill_quantity = qty
    if total_cost > 0:
        sig.cost_usd = round(total_cost, 4)
    sig.filled_at = datetime.now(timezone.utc)
    counts["filled"] += 1
    logger.info(
        "Kalshi sync filled %s: %.2f contracts @ $%.4f (cost $%.2f)",
        sig.market_ticker, qty, fill_price, total_cost,
    )


def _apply_fill_from_order(sig: Signal, order: dict, counts: dict) -> None:
    qty = _to_float(order.get("fill_count_fp"))
    cost = _to_float(order.get("taker_fill_cost_dollars"))
    if qty <= 0:
        return

    fill_price = cost / qty if cost > 0 and qty > 0 else _to_float(order.get("yes_price_dollars"))
    if fill_price <= 0:
        fill_price = _to_float(sig.entry_price)

    sig.status = "filled"
    sig.fill_price = round(fill_price, 4)
    sig.fill_quantity = qty
    if cost > 0:
        sig.cost_usd = round(cost, 4)
    sig.filled_at = datetime.now(timezone.utc)
    counts["filled"] += 1
    logger.info(
        "Kalshi sync filled %s (via order): %.2f contracts @ $%.4f",
        sig.market_ticker, qty, fill_price,
    )


def _apply_settlement(sig: Signal, settlement: dict, counts: dict) -> None:
    result = (settlement.get("market_result") or "").lower()
    # `revenue` is in cents (integer) — confirmed via live Kalshi API testing.
    # e.g. revenue=3900 means $39.00. Divide by 100 for dollars.
    # `fee_cost` and *_dollars fields are string-encoded decimals.
    revenue_dollars = _to_float(settlement.get("revenue")) / 100
    yes_count = _to_float(settlement.get("yes_count_fp"))
    no_count = _to_float(settlement.get("no_count_fp"))
    yes_cost = _to_float(settlement.get("yes_total_cost_dollars"))
    no_cost = _to_float(settlement.get("no_total_cost_dollars"))
    fee_dollars = _to_float(settlement.get("fee_cost"))

    # If Kalshi shows we owned zero contracts and paid nothing on either side
    # at settlement, our limit order never filled. Treat as cancelled — the
    # cost_usd in our DB is the theoretical limit cost, not money actually
    # spent. We never lost it.
    if yes_count == 0 and no_count == 0 and yes_cost == 0 and no_cost == 0:
        sig.status = "cancelled"
        sig.error_message = "order_never_filled_before_settlement"
        sig.resolved_at = datetime.now(timezone.utc)
        counts["cancelled"] += 1
        logger.info(
            "Kalshi sync cancelled %s: order never filled before settlement",
            sig.market_ticker,
        )
        return

    cost_dollars = yes_cost if yes_cost > 0 else _to_float(sig.cost_usd)

    pnl_usd = revenue_dollars - cost_dollars - fee_dollars

    if result == "yes":
        exit_price = 1.0
    elif result == "no":
        exit_price = 0.0
    else:
        # "void" or unknown — Kalshi refunds. Use the position's avg price.
        exit_price = _to_float(sig.fill_price) or _to_float(sig.entry_price)

    sig.exit_price = exit_price
    sig.cost_usd = round(cost_dollars, 4)
    sig.pnl_usd = round(pnl_usd, 4)
    if cost_dollars > 0:
        sig.pnl_pct = round((pnl_usd / cost_dollars) * 100, 2)
    sig.resolved_at = datetime.now(timezone.utc)

    if pnl_usd > 0:
        sig.status = "settled_win"
    elif pnl_usd < 0:
        sig.status = "settled_loss"
    else:
        sig.status = "settled_breakeven"

    counts["settled"] += 1
    logger.info(
        "Kalshi sync settled %s: result=%s revenue=$%.2f cost=$%.2f fees=$%.2f pnl=$%.4f",
        sig.market_ticker, result, revenue_dollars, cost_dollars, fee_dollars, pnl_usd,
    )
