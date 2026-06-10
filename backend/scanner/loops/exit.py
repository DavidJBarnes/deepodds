"""Exit loop — resolves filled positions on Kalshi settlement only.

Strategy is hold-to-resolution: every filled position rides to the
Kalshi-published outcome ($0 or $1). No stop-loss, no take-profit, no
near-expiry forced exit. The model's edge requires collecting full
winners; bailing on intraday bid-ask noise pays spread both ways and
guarantees we never see the payouts that justify the strategy.

Reads current market state from MarketSnapshot (refreshed every ~30-60s
by the discover loop) instead of hitting the per-ticker Kalshi endpoint
on every cycle. discover.py runs two passes per series (open + settled),
so a Kalshi settlement transition shows up in the snapshot within one
discover cycle.

The only non-settlement exit kept here is `post_expiry_orphan`: a
24h-after-recorded-expiry janitor that exits at the current bid if
Kalshi never published a settlement (broken/disputed market). Without
it, an unresolved market would sit as 'filled' forever.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.climate_config import ClimateConfig
from app.models.history import History
from app.models.market_snapshot import MarketSnapshot
from app.models.signal import Signal
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger("scanner.exit")


def _settled_yes_won(market_data: dict) -> bool | None:
    """Return True/False if Kalshi has explicitly published an outcome.

    Returns True iff Kalshi reports result="yes", False iff result="no".
    Returns None in every other case — including status='settled' with an
    empty result. Callers (the exit loop) must not assume an outcome
    based on last_price drift; if Kalshi hasn't yet published a result,
    the position stays in 'filled' status until it does, or until the
    post_expiry_orphan janitor kicks in 24h after recorded expiry.

    Previous versions inferred result from last_price (>=95 → yes,
    <=5 → no) when Kalshi's result field was empty. Observed 2026-06-10:
    on Dallas June 9 markets, T90 returned False (implies high ≤ 90) but
    B96.5 also returned False (implies high ≥ 96.5) — an impossible
    state that pinned the last_price fallback as the culprit. The
    fallback misattributes settlements during the brief windows where
    Kalshi marks a market 'settled' but its result field has not yet
    populated.
    """
    status = (market_data.get("status") or "").lower()
    if status not in ("settled", "finalized"):
        return None
    result = (market_data.get("result") or "").lower()
    if result == "yes":
        return True
    if result == "no":
        return False
    return None


_VENUE_CLIMATE = "kalshi_climate"


def _snapshot_to_market_data(snap: MarketSnapshot) -> dict:
    """Project the fields _settled_yes_won + heuristic price logic read."""
    return {
        "status": snap.status,
        "result": snap.result,
        "last_price": snap.last_price,
        "yes_bid_dollars": snap.bid_price or 0,
    }


def run_exit_loop(session: Session, engine: Engine) -> None:
    """Resolve filled positions on Kalshi settlement (or post-expiry janitor)."""

    filled = session.execute(
        select(Signal).where(
            Signal.venue == _VENUE_CLIMATE,
            Signal.status == "filled",
            Signal.fill_price.isnot(None),
        )
    ).scalars().all()

    if not filled:
        return

    # Bulk-load the snapshot rows that correspond to filled positions.
    tickers = [s.market_ticker for s in filled if s.market_ticker]
    snapshots: dict[str, MarketSnapshot] = {}
    if tickers:
        rows = session.execute(
            select(MarketSnapshot).where(MarketSnapshot.ticker.in_(tickers))
        ).scalars().all()
        snapshots = {r.ticker: r for r in rows}

    user_ids = {s.user_id for s in filled}
    configs: dict = {}
    for uid in user_ids:
        ccfg = session.execute(
            select(ClimateConfig).where(ClimateConfig.user_id == uid)
        ).scalar_one_or_none()
        if ccfg:
            configs[uid] = ("climate", ccfg)

    # Per-user authed Kalshi clients are only needed for the live-sell path.
    clients: dict[str, KalshiClient] = {}
    now = datetime.now(timezone.utc)
    exited = 0

    for sig in filled:
        cfg_tuple = configs.get(sig.user_id)
        if not cfg_tuple:
            continue
        _, cfg = cfg_tuple

        if not sig.market_ticker:
            continue

        snap = snapshots.get(sig.market_ticker)
        if snap is None:
            # Race: signal placed before next discover cycle ran. Will be
            # picked up next loop.
            continue

        market_data = _snapshot_to_market_data(snap)
        fill_price = sig.fill_price or 0
        qty = sig.fill_quantity or sig.quantity or 0

        # PRIORITY: if Kalshi has finalized this market, the exchange result
        # is the authoritative outcome regardless of any intraday signal.
        yes_won = _settled_yes_won(market_data)
        if yes_won is not None:
            exit_price = 1.0 if yes_won else 0.0
            pnl_usd = (exit_price - fill_price) * qty
            sig.exit_price = exit_price
            sig.resolved_at = now
            sig.status = (
                "settled_win" if pnl_usd > 0
                else "settled_loss" if pnl_usd < 0
                else "settled_breakeven"
            )
            # P&L attribution differs by mode. In paper, fees are zero and
            # the (exit - fill) * qty math is correct. In live, kalshi_live_sync
            # is the authoritative writer for pnl_usd / pnl_pct using Kalshi's
            # fee-aware fills + settles; if we write paper math here it races
            # the sync and one of the two ends up wrong. Audited 2026-06-10.
            if cfg.mode == "live":
                # Let kalshi_live_sync attribute realized P&L. We mark the
                # signal settled (so the dashboard reflects the outcome) but
                # leave the dollar fields for the sync to fill in.
                pass
            else:
                sig.pnl_usd = round(pnl_usd, 4)
                sig.pnl_pct = (
                    round((exit_price - fill_price) / fill_price * 100, 2)
                    if fill_price > 0 else 0.0
                )
            exited += 1
            kalshi_label = "YES" if yes_won else "NO"
            logger.info(
                "KALSHI SETTLE %s: result=%s exit=$%.2f fill=$%.2f P&L=$%.2f",
                sig.market_ticker, kalshi_label, exit_price, fill_price, pnl_usd,
            )
            session.add(History(
                user_id=sig.user_id,
                text=(
                    f"Settlement for {sig.market_ticker}: "
                    f"Kalshi={kalshi_label}, P&L=${pnl_usd:.2f}"
                ),
            ))
            continue

        # Hold-to-resolution: the ONLY non-Kalshi-settlement exit is the
        # post-expiry janitor. If Kalshi hasn't published a settlement
        # 24h after our recorded expiry, exit at the current bid so the
        # row doesn't sit as 'filled' forever.
        if not (sig.expiry_time and now > sig.expiry_time + timedelta(hours=24)):
            continue

        price = float(market_data.get("yes_bid_dollars") or 0)
        if price <= 0:
            continue

        pnl_usd = (price - fill_price) * qty
        exit_reason = "post_expiry_orphan"

        # Live-sell path needs an authed client; construct lazily once per user.
        if cfg.mode == "live":
            client = clients.get(str(sig.user_id))
            if client is None:
                try:
                    from app.models.user import User
                    user = session.execute(
                        select(User).where(User.id == sig.user_id)
                    ).scalar_one_or_none()
                    if user and user.kalshi_api_key_id and user.kalshi_private_key:
                        client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
                        clients[str(sig.user_id)] = client
                except Exception:
                    pass
            if client is None:
                logger.warning("Exit: no live client for user %s; skipping sell", sig.user_id)
                continue
            try:
                yes_price_cents = int(round(price * 100))
                run_async(client.create_order(
                    ticker=sig.market_ticker, side="yes",
                    count=int(qty), yes_price_cents=yes_price_cents,
                    action="sell",
                ))
                sig.exit_price = price
                sig.status = "closing"
                session.commit()
                logger.info("LIVE SELL %s: %s", sig.market_ticker, exit_reason)
                exited += 1
            except Exception:
                logger.exception("Exit: failed to sell %s", sig.market_ticker)
            continue

        # Paper-mode post-expiry janitor exit.
        sig.exit_price = price
        paper_fee = round((fill_price + price) * qty * 0.0007, 4)
        sig.pnl_usd = round(pnl_usd - paper_fee, 4)
        sig.pnl_pct = round((pnl_usd / (fill_price * qty)) * 100, 2) if fill_price > 0 and qty > 0 else 0.0
        sig.resolved_at = now
        if pnl_usd > 0:
            sig.status = "settled_win"
        elif pnl_usd < 0:
            sig.status = "settled_loss"
        else:
            sig.status = "settled_breakeven"
        exited += 1
        logger.info("EXIT %s: %s P&L $%.2f", sig.market_ticker, exit_reason, pnl_usd)

    if exited:
        session.commit()
        logger.info("Exit loop: exited %d positions", exited)
