"""Signal loop — checks scored market snapshots against user configs
and creates signals (paper) or places orders (live)."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.market_snapshot import MarketSnapshot
from app.models.signal import Signal
from app.models.user import User
from app.services.kalshi_client import KalshiClient
from app.services.kalshi_utils import (
    OPEN_STATUSES,
    check_spread_filter,
    kelly_count,
    market_ask,
    market_bid,
    market_mid,
    read_balance_cache,
)

logger = logging.getLogger("scanner.signal")

# Granular rejection reasons we recognize. Kept for documentation /
# downstream filtering; the signal-refire check is one-shot-per-ticker
# regardless of how the prior signal ended (see the dedup query below).
_REJECTION_STATUSES = (
    "rejected_insufficient_funds",
    "rejected_rate_limit",
    "expired_unfilled",
)


def _classify_rejection(err_msg: str) -> str:
    """Map a Kalshi/order-placement error into a granular Signal.status."""
    msg = (err_msg or "").lower()
    if "insufficient_balance" in msg or "insufficient balance" in msg:
        return "rejected_insufficient_funds"
    if "too_many_requests" in msg or "429" in msg or "rate" in msg:
        return "rejected_rate_limit"
    return "cancelled"


def run_signal_loop(session: Session) -> None:
    """Check scored snapshots against each enabled user's config.

    For each user, reads global market_snapshots where edge >= user's
    min_edge, then checks position limits, Kelly sizes, and creates
    a signal (paper) or places an order (live).
    """

    crypto_cfgs = session.execute(
        select(CryptoConfig).where(CryptoConfig.enabled.is_(True))
    ).scalars().all()
    climate_cfgs = session.execute(
        select(ClimateConfig).where(ClimateConfig.enabled.is_(True))
    ).scalars().all()

    all_configs = [
        (cfg, "kalshi_crypto") for cfg in crypto_cfgs
    ] + [
        (cfg, "kalshi_climate") for cfg in climate_cfgs
    ]

    if not all_configs:
        return

    _VENUES = {"kalshi_crypto", "kalshi_climate"}
    snapshots = session.execute(
        select(MarketSnapshot).where(
            MarketSnapshot.venue.in_(_VENUES),
            MarketSnapshot.edge.is_not(None),
            MarketSnapshot.filter_reason.is_(None),
        ).order_by(MarketSnapshot.edge.desc()).limit(500)
    ).scalars().all()

    if not snapshots:
        return

    snap_by_ticker: dict[str, MarketSnapshot] = {}
    for s in snapshots:
        snap_by_ticker[s.ticker] = s

    for config, venue in all_configs:
        try:
            user = session.execute(
                select(User).where(User.id == config.user_id)
            ).scalar_one_or_none()
            if not user:
                continue

            open_positions = session.execute(
                select(Signal).where(
                    Signal.user_id == config.user_id,
                    Signal.venue == venue,
                    Signal.status.in_(OPEN_STATUSES),
                )
            ).scalars().all()

            if len(open_positions) >= config.max_open_positions:
                continue

            event_counts: dict[str, int] = {}
            for sig in open_positions:
                if sig.event_ticker:
                    event_counts[sig.event_ticker] = event_counts.get(sig.event_ticker, 0) + 1

            client = None
            if config.mode == "live" and user.kalshi_api_key_id and user.kalshi_private_key:
                try:
                    client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
                except Exception:
                    pass

            for snapshot in snapshots:
                if snapshot.venue != venue:
                    continue
                ticker = snapshot.ticker
                if not ticker:
                    continue

                if snapshot.edge is None or snapshot.edge < config.min_edge:
                    continue

                # Band filter: gate by raw model_prob. Default ceiling of 0.80
                # blocks the bucket where the climate model has been measured
                # systematically overconfident; floor of 0.0 leaves the
                # underconfident low-prob bucket firing.
                if snapshot.model_prob is None:
                    continue
                if (
                    snapshot.model_prob < config.min_model_prob
                    or snapshot.model_prob > config.max_model_prob
                ):
                    logger.info(
                        "Signal %s skipped: model_prob=%.3f outside [%.2f, %.2f]",
                        ticker, snapshot.model_prob,
                        config.min_model_prob, config.max_model_prob,
                    )
                    continue

                # One-shot per (user, ticker). If any prior signal exists for
                # this market — settled win/loss, stopped out, rejected,
                # expired, or still open — do not refire. The previous design
                # only blocked the open/rejected states, which let a stop-out
                # transition (filled -> settled_loss) immediately reopen the
                # ticker for refire. The scanner then re-entered the same
                # idea within ~10 seconds, stacking losses on identical
                # entries. Climate markets resolve same-day; the model output
                # on a touched ticker is the same idea repeating, not new
                # information.
                exists = session.execute(
                    select(Signal.id).where(
                        Signal.user_id == config.user_id,
                        Signal.market_ticker == ticker,
                    ).limit(1)
                ).scalar_one_or_none()
                if exists:
                    continue

                event_ticker = getattr(snapshot, "_event_ticker", None)
                if event_ticker and event_counts.get(event_ticker, 0) >= config.max_positions_per_event:
                    continue

                if len(open_positions) + 1 > config.max_open_positions:
                    break

                ask_price = snapshot.ask_price
                mid_price = snapshot.mid_price or ask_price
                market_price = mid_price if mid_price > 0 else ask_price
                if market_price <= 0:
                    continue

                if client:
                    try:
                        market_data = run_async(client.get_market(ticker))
                        fresh_ask = float(market_data.get("yes_ask_dollars", 0) or 0)
                        fresh_bid = float(market_data.get("yes_bid_dollars", 0) or 0)
                        if fresh_ask <= 0:
                            continue
                        market_price = (fresh_ask + fresh_bid) / 2 if fresh_bid > 0 else fresh_ask
                        ask_price = fresh_ask
                    except Exception as e:
                        logger.warning(
                            "Signal: get_market for fresh ask failed on %s: %r", ticker, e,
                        )
                        continue

                bankroll_cents = read_balance_cache(str(config.user_id))
                if bankroll_cents and bankroll_cents > 0:
                    count = kelly_count(
                        snapshot.edge, market_price, bankroll_cents,
                        config.contracts_per_signal, config.max_cost_per_signal,
                    )
                else:
                    count = config.contracts_per_signal
                    if market_price > 0 and market_price * count > config.max_cost_per_signal:
                        count = int(config.max_cost_per_signal / market_price)

                if count < 1:
                    continue

                cost = market_price * count

                # Pre-flight balance check for live mode. We still create a
                # Signal row so the (raw_model_prob, market_ticker) data is
                # preserved for future Platt training even though no order
                # gets placed.
                preflight_status: str | None = None
                if config.mode == "live" and client and bankroll_cents is not None and bankroll_cents > 0:
                    needed_cents = int(cost * 100)
                    if needed_cents > bankroll_cents:
                        preflight_status = "rejected_insufficient_funds"
                        logger.info(
                            "Pre-flight reject %s: need %d cents, have %d cents",
                            ticker, needed_cents, bankroll_cents,
                        )

                signal = Signal(
                    user_id=config.user_id,
                    venue=venue,
                    pair=snapshot.series,
                    side="buy",
                    signal_type=config.mode,
                    status=preflight_status or ("placed" if client else "filled"),
                    entry_price=market_price,
                    quantity=float(count),
                    cost_usd=cost,
                    model_prob=snapshot.model_prob,
                    raw_model_prob=snapshot.raw_model_prob,
                    market_prob=market_price,
                    edge=snapshot.edge,
                    floor_strike=snapshot.floor_strike,
                    cap_strike=snapshot.cap_strike,
                    strike_type=snapshot.strike_type,
                    underlying_price=snapshot.underlying_price,
                    realized_vol=snapshot.realized_vol,
                    market_ticker=ticker,
                    event_ticker=event_ticker,
                    expiry_time=snapshot.expiry_time,
                )

                if preflight_status is not None:
                    # Persist the rejection and move on — no Kalshi call.
                    signal.error_message = f"pre-flight: need {needed_cents}c have {bankroll_cents}c"
                    session.add(signal)
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                    continue

                if config.mode == "live" and client:
                    # Stage with status='signaled' to claim the unique partial
                    # index slot. The Kalshi call follows; whatever its result,
                    # we transition the row to a final state. Using 'signaled'
                    # (not 'placed') here means a transient rejection doesn't
                    # leave behind a phantom 'placed' row if the status-update
                    # commit fails — we'll see 'signaled' and can detect it.
                    signal.status = "signaled"
                    session.add(signal)
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        continue

                    sig_id = signal.id
                    try:
                        max_price_cents = int(round(config.max_price * 100))
                        limit_price = round(market_price * 100)
                        yes_price_cents = min(int(limit_price), max_price_cents)
                        order_result = run_async(client.create_order(
                            ticker=ticker, side="yes", count=count,
                            yes_price_cents=yes_price_cents,
                        ))
                        order = order_result.get("order", order_result) if isinstance(order_result, dict) else {}
                        order_id = order.get("order_id") if isinstance(order, dict) else None
                        if not order_id:
                            # Kalshi returned 2xx but the response is malformed.
                            # Treat as a failure so we don't end up with an
                            # untrackable order on the exchange.
                            raise ValueError(f"Kalshi response missing order_id: {order_result}")
                        signal.exchange_order_id = order_id
                        signal.status = "placed"
                        session.commit()
                        logger.info("LIVE BUY %s: %d @ $%.2f", ticker, count, yes_price_cents / 100)
                    except Exception as e:
                        # The Kalshi call (or our handling) raised. SQLAlchemy's
                        # session may be in a 'rollback required' state after
                        # a failed in-memory mutation + commit attempt, which
                        # is what was leaving phantom 'signaled' rows. Roll
                        # back explicitly, then UPDATE the row via SQL Core
                        # so we bypass any lingering ORM dirty-tracking.
                        try:
                            session.rollback()
                        except Exception:
                            pass
                        new_status = _classify_rejection(str(e))
                        try:
                            session.execute(
                                update(Signal).where(Signal.id == sig_id).values(
                                    status=new_status,
                                    error_message=str(e)[:200],
                                )
                            )
                            session.commit()
                            logger.info(
                                "LIVE BUY %s rejected: status=%s err=%s",
                                ticker, new_status, str(e)[:120],
                            )
                        except Exception:
                            logger.exception(
                                "Failed to update signal %s to %s — row may be stuck at 'signaled'",
                                sig_id, new_status,
                            )
                            try:
                                session.rollback()
                            except Exception:
                                pass
                else:
                    signal.fill_price = market_price
                    signal.fill_quantity = float(count)
                    signal.cost_usd = round(cost, 4)
                    signal.filled_at = datetime.now(timezone.utc)
                    session.add(signal)
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        continue
                    logger.info("PAPER BUY %s: %d @ $%.2f", ticker, count, market_price)

                if event_ticker:
                    event_counts[event_ticker] = event_counts.get(event_ticker, 0) + 1

        except Exception:
            logger.exception("Signal processing failed for user %s, venue %s", config.user_id, venue)
            try:
                session.rollback()
            except Exception:
                pass
            continue
