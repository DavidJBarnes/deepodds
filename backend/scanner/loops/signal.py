"""Signal loop — checks scored market snapshots against user configs
and creates signals (paper) or places orders (live)."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
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

                exists = session.execute(
                    select(Signal.id).where(
                        Signal.user_id == config.user_id,
                        Signal.market_ticker == ticker,
                        Signal.status.in_(("signaled", "placed", "filled")),
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
                    except Exception:
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

                signal = Signal(
                    user_id=config.user_id,
                    venue=venue,
                    pair=snapshot.series,
                    side="buy",
                    signal_type=config.mode,
                    status="placed" if client else "filled",
                    entry_price=market_price,
                    quantity=float(count),
                    cost_usd=cost,
                    model_prob=snapshot.model_prob,
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

                if config.mode == "live" and client:
                    session.add(signal)
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        continue

                    try:
                        max_price_cents = int(round(config.max_price * 100))
                        limit_price = round(market_price * 100)
                        yes_price_cents = min(int(limit_price), max_price_cents)
                        order_result = run_async(client.create_order(
                            ticker=ticker, side="yes", count=count,
                            yes_price_cents=yes_price_cents,
                        ))
                        order = order_result.get("order", order_result)
                        signal.exchange_order_id = order.get("order_id")
                        signal.status = "placed"
                        session.commit()
                        logger.info("LIVE BUY %s: %d @ $%.2f", ticker, count, yes_price_cents / 100)
                    except Exception as e:
                        signal.status = "cancelled"
                        signal.error_message = str(e)[:200]
                        try:
                            session.commit()
                        except Exception:
                            session.rollback()
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
