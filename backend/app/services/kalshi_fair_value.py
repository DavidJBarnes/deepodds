import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.kalshi_config import KalshiConfig
from app.models.pair_config import PairConfig
from app.models.signal import Signal
from app.services.binance_client import get_crypto_prices, get_realized_vol
from app.services.config_resolver import resolve_kalshi_config
from app.services.kalshi_client import KalshiClient
from app.services.probability_model import compute_edge, series_to_underlying

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")
HOURS_TO_YEARS = 1 / (365.25 * 24)


def _today_pnl_kalshi(session: Session, user_id) -> float:
    today_ny = datetime.now(ZoneInfo("America/New_York")).date()
    result = session.execute(
        select(func.coalesce(func.sum(Signal.pnl_usd), 0.0)).where(
            Signal.user_id == user_id,
            Signal.venue == "kalshi",
            func.date(func.timezone("America/New_York", Signal.resolved_at)) == today_ny,
            Signal.pnl_usd.isnot(None),
        )
    )
    return float(result.scalar())


def _signals_last_hour_kalshi(session: Session, user_id) -> int:
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = session.execute(
        select(func.count(Signal.id)).where(
            Signal.user_id == user_id,
            Signal.venue == "kalshi",
            Signal.created_at >= one_hour_ago,
            Signal.status.notin_(["cancelled"]),
        )
    )
    return result.scalar()


def _open_kalshi_positions(session: Session, user_id) -> list[Signal]:
    return list(
        session.execute(
            select(Signal).where(
                Signal.user_id == user_id,
                Signal.venue == "kalshi",
                Signal.status.in_(OPEN_STATUSES),
            )
        ).scalars().all()
    )


def _has_traded_ticker(session: Session, user_id, market_ticker: str) -> bool:
    """True if user has ANY signal on this market_ticker — including cancelled.

    Kalshi tickers are unique per event resolution, so we never want to
    re-enter a ticker we've already touched. Including cancelled signals
    prevents the observed retry-storm pattern: order rejected with 400,
    we mark cancelled, next 30s scan re-tries, rejects again, repeat.
    Once we've cancelled a ticker, we move on for that event resolution.
    """
    result = session.execute(
        select(Signal.id).where(
            Signal.user_id == user_id,
            Signal.venue == "kalshi",
            Signal.market_ticker == market_ticker,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def _open_event_count(session: Session, user_id, event_ticker: str) -> int:
    """Count of currently-open positions in a single event.

    Buckets within an event are mutually exclusive (only one wins), so
    holding multiple buckets is correlated risk masquerading as diversification.
    """
    if not event_ticker:
        return 0
    return session.execute(
        select(func.count(Signal.id)).where(
            Signal.user_id == user_id,
            Signal.venue == "kalshi",
            Signal.event_ticker == event_ticker,
            Signal.status.in_(OPEN_STATUSES),
        )
    ).scalar() or 0


def _market_ask(market: dict) -> float:
    """Return the YES ask in dollars — the price we would actually pay to enter."""
    return float(market.get("yes_ask_dollars", 0) or 0)


def _market_ask_size(market: dict) -> float:
    return float(market.get("yes_ask_size_fp", 0) or 0)


def _discover_markets(
    client: KalshiClient,
    series_tickers: list[str],
    min_volume: int,
    min_price: float,
    max_price: float,
    min_hours_to_expiry: int,
    min_ask_size: int = 1,
) -> list[dict]:
    """Find markets where we could actually fill a buy order at a sensible price.

    Filters on the YES ask (the price we'd pay), not last_price (which can be
    stale). Also requires ask size >= min_ask_size so the order book has depth
    for at least our smallest position.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=min_hours_to_expiry)
    eligible = []

    for series in series_tickers:
        try:
            data = run_async(client.get_markets(series_ticker=series, limit=200))
        except Exception:
            logger.warning("Failed to fetch markets for series %s", series)
            continue

        for m in data.get("markets", []):
            vol_24h = float(m.get("volume_24h_fp", 0) or 0)
            if vol_24h < min_volume:
                continue

            ask = _market_ask(m)
            if ask < min_price or ask > max_price:
                continue

            if _market_ask_size(m) < min_ask_size:
                continue

            close_time = m.get("close_time", "")
            try:
                ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if ct < cutoff:
                continue

            m["_series_ticker"] = series
            m["_close_dt"] = ct
            m["_ask"] = ask
            eligible.append(m)

    eligible.sort(key=lambda m: float(m.get("volume_24h_fp", 0) or 0), reverse=True)
    return eligible


def _compute_vol_scaling(symbol: str, current_vol: float) -> float:
    """Return a position-sizing multiplier based on vol regime.

    Compares current short/medium-term vol to a 7-day baseline:
      ratio ≤ 1.5 → 1.0  (normal — no reduction)
      ratio > 1.5 → 0.5  (elevated — halve size)
      ratio > 2.5 → 0.0  (extreme — skip entirely)

    The 7-day baseline is fetched with 1h candles to avoid excessive API
    calls while still capturing the medium-term vol regime.
    """
    try:
        baseline = run_async(get_realized_vol(symbol, hours=168, interval="1h"))
    except Exception:
        return 1.0

    if baseline is None or baseline <= 0:
        return 1.0

    ratio = current_vol / baseline if baseline > 0 else 1.0
    if ratio > 2.5:
        logger.info("Vol regime extreme for %s: ratio=%.2f — skipping", symbol, ratio)
        return 0.0
    if ratio > 1.5:
        logger.info("Vol regime elevated for %s: ratio=%.2f — halving size", symbol, ratio)
        return 0.5
    return 1.0


def _read_balance_cache(user_id: str) -> float | None:
    """Return portfolio_cents from the scheduler-written balance cache, or None."""
    import json as _json
    from pathlib import Path

    try:
        path = Path(f"/tmp/kalshi_balance_{user_id}.json")
        if not path.exists():
            return None
        data = _json.loads(path.read_text())
        return float(data.get("portfolio_cents", 0))
    except Exception:
        return None


def _kelly_count(edge: float, market_price: float, bankroll_cents: float, max_contracts: int, max_cost: float) -> int:
    """Compute position size using fractional Kelly.

    For a binary YES bet at price P with edge e = model_prob - P:
      Kelly fraction f* = e / (1 - P)

    Contracts = floor(f* × bankroll / P), capped by max_contracts and max_cost.
    Uses 1/4 Kelly (quarter-Kelly) as a conservative default.
    """
    if market_price <= 0 or edge <= 0:
        return 0
    kelly = edge / (1 - market_price)
    quarter_kelly = kelly * 0.25
    bankroll_dollars = bankroll_cents / 100
    count = int(quarter_kelly * bankroll_dollars / market_price)
    count = min(count, max_contracts)
    if market_price * count > max_cost:
        count = int(max_cost / market_price)
    return max(count, 0)


def _fetch_underlying_data(series_tickers: list[str], vol_hours: int, vol_interval: str) -> dict:
    symbol_to_series = {}
    for series in series_tickers:
        symbol = series_to_underlying(series)
        if symbol:
            symbol_to_series.setdefault(symbol, []).append(series)
        else:
            logger.warning("Kalshi series %s does not match KX{SYMBOL} convention; skipping", series)

    if not symbol_to_series:
        return {}

    prices = run_async(get_crypto_prices(list(symbol_to_series.keys())))
    result = {}
    for symbol, series_list in symbol_to_series.items():
        if symbol not in prices:
            logger.warning("No spot price available for %s (series %s)", symbol, series_list)
            continue
        vol = run_async(get_realized_vol(symbol, hours=vol_hours, interval=vol_interval))
        if vol is None or vol <= 0:
            logger.warning("No realized vol for %s (series %s)", symbol, series_list)
            continue
        vol_scaling = _compute_vol_scaling(symbol, vol)
        for series in series_list:
            result[series] = {"spot": prices[symbol], "vol": vol, "vol_scaling": vol_scaling}
    return result


def scan_kalshi_entries(
    user_id,
    session: Session,
    client: KalshiClient | None = None,
) -> list[Signal]:
    config = session.execute(
        select(KalshiConfig).where(KalshiConfig.user_id == user_id)
    ).scalar_one_or_none()

    if not config or not config.enabled:
        return []

    if config.daily_loss_limit_usd > 0:
        if _today_pnl_kalshi(session, user_id) <= -config.daily_loss_limit_usd:
            logger.warning("Kalshi daily loss limit hit — skipping scan")
            return []

    if config.max_signals_per_hour > 0:
        if _signals_last_hour_kalshi(session, user_id) >= config.max_signals_per_hour:
            return []

    open_pos = _open_kalshi_positions(session, user_id)
    if len(open_pos) >= config.max_open_positions:
        return []

    series = [s.strip() for s in config.series_tickers.split(",") if s.strip()]

    overrides = {}
    for pc in session.execute(
        select(PairConfig).where(PairConfig.user_id == user_id, PairConfig.venue == "kalshi")
    ).scalars().all():
        overrides[pc.pair] = pc

    client = client or KalshiClient.public()
    markets = _discover_markets(
        client, series,
        config.min_volume_24h, config.min_price, config.max_price,
        config.min_hours_to_expiry,
        min_ask_size=1,
    )

    underlying = _fetch_underlying_data(series, config.vol_lookback_hours, config.vol_interval)
    now = datetime.now(timezone.utc)
    signals_created = []

    event_counts: dict[str, int] = {}
    for sig in open_pos:
        if sig.event_ticker:
            event_counts[sig.event_ticker] = event_counts.get(sig.event_ticker, 0) + 1

    for market in markets:
        ticker = market.get("ticker")
        if not ticker:
            continue
        series_ticker = market.get("_series_ticker")
        event_ticker = market.get("event_ticker")

        # Per-market try/except so a single bad market (e.g. missing strike
        # data) can't crash the whole scan mid-loop. Previously this caused
        # signals to never be persisted while their orders had already gone
        # through to Kalshi — duplicate-order disaster.
        try:
            if series_ticker not in underlying:
                continue

            if _has_traded_ticker(session, user_id, ticker):
                continue

            if event_ticker and event_counts.get(event_ticker, 0) >= config.max_positions_per_event:
                continue

            if len(open_pos) + len(signals_created) >= config.max_open_positions:
                break

            eff = resolve_kalshi_config(config, overrides.get(series_ticker))

            spot = underlying[series_ticker]["spot"]
            vol = underlying[series_ticker]["vol"]
            close_dt = market["_close_dt"]
            t_hours = (close_dt - now).total_seconds() / 3600
            t_years = t_hours * HOURS_TO_YEARS

            floor_strike = market.get("floor_strike")
            cap_strike = market.get("cap_strike")
            strike_type = market.get("strike_type", "between")
            market_price = float(market.get("_ask") or _market_ask(market))

            if market_price <= 0:
                continue

            if floor_strike is not None:
                floor_strike = float(floor_strike)
            if cap_strike is not None:
                cap_strike = float(cap_strike)

            # compute_edge crashes if the strike(s) it needs are None for the
            # given strike_type. Skip incomplete markets instead.
            if strike_type == "between" and (floor_strike is None or cap_strike is None):
                logger.warning("skipping %s: 'between' market missing strike(s)", ticker)
                continue
            if strike_type == "greater" and floor_strike is None:
                logger.warning("skipping %s: 'greater' market missing floor_strike", ticker)
                continue
            if strike_type == "less" and cap_strike is None:
                logger.warning("skipping %s: 'less' market missing cap_strike", ticker)
                continue

            result = compute_edge(
                spot, floor_strike, cap_strike, strike_type,
                t_years, vol, market_price,
            )

            logger.info(
                "KALSHI %s: model=%.1f%% market=%.1f%% edge=%.1f%% (min=%.1f%%)",
                ticker, result.model_prob * 100, result.market_prob * 100,
                result.edge * 100, eff["min_edge"] * 100,
            )

            if result.edge < eff["min_edge"]:
                continue

            # P0: Vol regime filter + Kelly position sizing
            vol_scaling = underlying[series_ticker].get("vol_scaling", 1.0)
            if vol_scaling <= 0:
                logger.info("Skipping %s: vol regime extreme", ticker)
                continue

            bankroll_cents = _read_balance_cache(str(user_id))
            if bankroll_cents and bankroll_cents > 0:
                count = _kelly_count(
                    result.edge, market_price, bankroll_cents,
                    eff["contracts_per_signal"], eff["max_cost_per_signal"],
                )
            else:
                # Fallback to flat sizing when no balance cache
                count = eff["contracts_per_signal"]
                if market_price > 0 and market_price * count > eff["max_cost_per_signal"]:
                    count = int(eff["max_cost_per_signal"] / market_price)

            count = int(count * vol_scaling)
            if count < 1:
                continue

            if _market_ask_size(market) < count:
                continue

            cost = market_price * count

            signal = Signal(
                user_id=user_id,
                venue="kalshi",
                pair=series_ticker,
                side="buy",
                signal_type=config.mode,
                status="signaled",
                entry_price=market_price,
                quantity=float(count),
                cost_usd=cost,
                model_prob=result.model_prob,
                market_prob=result.market_prob,
                edge=result.edge,
                floor_strike=floor_strike,
                cap_strike=cap_strike,
                strike_type=strike_type,
                underlying_price=spot,
                realized_vol=vol,
                market_ticker=ticker,
                event_ticker=market.get("event_ticker"),
                expiry_time=close_dt,
            )

            if config.mode == "live" and client:
                # Save the signal in "signaled" state BEFORE hitting Kalshi.
                # If create_order then succeeds we update to "placed". If we
                # crash after Kalshi accepts but before our update lands, the
                # next scan sees a signaled-state record and won't re-place
                # the order (the orphaned position is still visible to
                # sync_kalshi_live via the ticker).
                session.add(signal)
                session.commit()
                signals_created.append(signal)
                if event_ticker:
                    event_counts[event_ticker] = event_counts.get(event_ticker, 0) + 1

                try:
                    max_price_cents = int(round(config.max_price * 100))
                    yes_price_cents = min(
                        int(round(market_price * 100)) + 1,
                        max_price_cents,
                    )
                    order_result = run_async(client.create_order(
                        ticker=ticker, side="yes", count=count,
                        yes_price_cents=yes_price_cents,
                    ))
                    order = order_result.get("order", order_result)
                    signal.exchange_order_id = order.get("order_id")
                    signal.status = "placed"
                    session.commit()
                    logger.info(
                        "LIVE KALSHI BUY %s: %d @ limit $%.2f (ask was $%.2f)",
                        ticker, count, yes_price_cents / 100, market_price,
                    )
                except Exception as e:
                    signal.status = "cancelled"
                    signal.error_message = str(e)[:200]
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                    logger.exception("Failed to place Kalshi order for %s", ticker)
            else:
                bid = float(market.get("yes_bid_dollars") or 0)
                mid = round((market_price + bid) / 2, 4) if bid > 0 else market_price
                signal.status = "filled"
                signal.fill_price = mid
                signal.fill_quantity = float(count)
                signal.filled_at = datetime.now(timezone.utc)
                session.add(signal)
                session.commit()
                signals_created.append(signal)
                if event_ticker:
                    event_counts[event_ticker] = event_counts.get(event_ticker, 0) + 1
                logger.info(
                    "PAPER KALSHI BUY %s: %d @ $%.2f (mid $%.2f, ask $%.2f, model=%.0f%% edge=+%.0f%%)",
                    ticker, count, mid, mid, market_price,
                    result.model_prob * 100, result.edge * 100,
                )

        except Exception:
            logger.exception(
                "Per-market scan error on %s — skipping (session rolled back)",
                ticker,
            )
            try:
                session.rollback()
            except Exception:
                logger.exception("Session rollback failed")
            continue

    return signals_created


def check_kalshi_exits(
    session: Session,
    exchange_clients: dict[str, KalshiClient] | None = None,
) -> int:
    filled = session.execute(
        select(Signal).where(
            Signal.venue == "kalshi",
            Signal.status == "filled",
            Signal.fill_price.isnot(None),
        )
    ).scalars().all()

    if not filled:
        return 0

    user_ids = {s.user_id for s in filled}
    configs = {}
    pair_overrides: dict[str, dict[str, PairConfig]] = {}
    for uid in user_ids:
        cfg = session.execute(
            select(KalshiConfig).where(KalshiConfig.user_id == uid)
        ).scalar_one_or_none()
        if cfg:
            configs[uid] = cfg
        uid_overrides = {}
        for pc in session.execute(
            select(PairConfig).where(PairConfig.user_id == uid, PairConfig.venue == "kalshi")
        ).scalars().all():
            uid_overrides[pc.pair] = pc
        pair_overrides[str(uid)] = uid_overrides

    series_set = {s.pair for s in filled if s.pair}
    all_series = list(series_set)
    vol_hours = 24
    vol_interval = "15m"
    if configs:
        first_cfg = next(iter(configs.values()))
        vol_hours = first_cfg.vol_lookback_hours
        vol_interval = first_cfg.vol_interval

    underlying = _fetch_underlying_data(all_series, vol_hours, vol_interval)

    exited = 0
    now = datetime.now(timezone.utc)
    exchange_clients = exchange_clients or {}

    for sig in filled:
        cfg = configs.get(sig.user_id)
        if not cfg:
            continue

        client = exchange_clients.get(str(sig.user_id))

        if not sig.market_ticker or not sig.pair:
            continue

        eff = resolve_kalshi_config(cfg, pair_overrides.get(str(sig.user_id), {}).get(sig.pair))

        try:
            market = run_async((client or KalshiClient.public()).get_market(sig.market_ticker))
            # B1: Use bid price for exit valuation (what we'd actually receive selling)
            price = float(market.get("yes_bid_dollars") or market.get("last_price_dollars", 0))
        except Exception:
            logger.warning("Failed to get price for %s", sig.market_ticker)
            continue

        if price <= 0:
            continue

        pnl_pct = (price - sig.fill_price) / sig.fill_price * 100 if sig.fill_price > 0 else 0
        qty = sig.fill_quantity or sig.quantity
        pnl_usd = (price - sig.fill_price) * qty

        current_edge = 0.0
        if sig.pair in underlying and sig.floor_strike is not None:
            spot = underlying[sig.pair]["spot"]
            vol = underlying[sig.pair]["vol"]
            close_dt = sig.expiry_time
            if close_dt:
                t_hours = max(0, (close_dt - now).total_seconds() / 3600)
                t_years = t_hours * HOURS_TO_YEARS
                result = compute_edge(
                    spot, sig.floor_strike, sig.cap_strike,
                    sig.strike_type or "between",
                    t_years, vol, price,
                )
                current_edge = result.edge

        hold_minutes = (now - sig.filled_at).total_seconds() / 60 if sig.filled_at else 999
        min_hold = cfg.min_hold_minutes

        should_exit = False
        exit_reason = ""

        # B4: Fee-aware stop-loss — adjust P&L by estimated 0.5% round-trip fees
        # so the stop triggers slightly earlier, preventing fee-eroded exits.
        fee_estimate_pct = 0.5
        adjusted_pnl_pct = pnl_pct - fee_estimate_pct

        # Stop loss is gated by min_hold to prevent bid-ask spread from
        # triggering immediate exits (entry at ask, exit check uses bid).
        # Approaching expiry remains ungated — a real time constraint.
        # take_profit and edge_lost are also gated by min_hold.
        if adjusted_pnl_pct <= -eff["stop_loss_pct"] and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"stop_loss ({pnl_pct:.1f}%)"
        elif sig.expiry_time and (sig.expiry_time - now) < timedelta(hours=cfg.min_hours_to_expiry / 2):
            should_exit = True
            exit_reason = "approaching_expiry"
        elif sig.filled_at and (now - sig.filled_at) > timedelta(hours=24):
            should_exit = True
            exit_reason = "max_hold (24h)"
        elif eff["take_profit_pct"] > 0 and pnl_pct >= eff["take_profit_pct"] and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"take_profit ({pnl_pct:.1f}%)"
        elif current_edge <= eff["exit_edge"] and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"edge_lost ({current_edge:+.1%})"

        if not should_exit:
            continue

        if cfg.mode == "live" and client:
            try:
                yes_price_cents = int(round(price * 100))
                run_async(client.create_order(
                    ticker=sig.market_ticker, side="yes",
                    count=int(qty), yes_price_cents=yes_price_cents,
                    action="sell",
                ))
                logger.info("LIVE KALSHI SELL %s: %s", sig.market_ticker, exit_reason)
            except Exception:
                logger.exception("Failed to sell Kalshi position %s", sig.market_ticker)
                continue

        sig.exit_price = price
        sig.pnl_usd = round(pnl_usd, 4)
        sig.pnl_pct = round(pnl_pct, 2)
        sig.resolved_at = now
        if pnl_usd > 0:
            sig.status = "settled_win"
        elif pnl_usd < 0:
            sig.status = "settled_loss"
        else:
            sig.status = "settled_breakeven"

        exited += 1
        logger.info(
            "KALSHI %s %s: exit @ $%.2f (entry $%.2f, %s, P&L $%.4f / %.1f%%)",
            sig.status.upper(), sig.market_ticker, price, sig.fill_price,
            exit_reason, pnl_usd, pnl_pct,
        )

    session.commit()
    return exited
