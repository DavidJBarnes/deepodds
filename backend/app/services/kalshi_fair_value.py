import logging
from datetime import datetime, timedelta, timezone

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
    today_utc = datetime.now(timezone.utc).date()
    result = session.execute(
        select(func.coalesce(func.sum(Signal.pnl_usd), 0.0)).where(
            Signal.user_id == user_id,
            Signal.venue == "kalshi",
            func.date(Signal.resolved_at) == today_utc,
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


def _has_open_kalshi_position(session: Session, user_id, market_ticker: str) -> bool:
    result = session.execute(
        select(Signal.id).where(
            Signal.user_id == user_id,
            Signal.venue == "kalshi",
            Signal.market_ticker == market_ticker,
            Signal.status.in_(OPEN_STATUSES),
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def _discover_markets(
    client: KalshiClient,
    series_tickers: list[str],
    min_volume: int,
    min_price: float,
    max_price: float,
    min_hours_to_expiry: int,
) -> list[dict]:
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
            vol_24h = float(m.get("volume_24h_fp", 0))
            if vol_24h < min_volume:
                continue

            last_price = float(m.get("last_price_dollars", 0))
            if last_price < min_price or last_price > max_price:
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
            eligible.append(m)

    eligible.sort(key=lambda m: float(m.get("volume_24h_fp", 0)), reverse=True)
    return eligible


def _fetch_underlying_data(series_tickers: list[str], vol_hours: int, vol_interval: str) -> dict:
    prices = run_async(get_crypto_prices())
    result = {}
    for series in series_tickers:
        symbol = series_to_underlying(series)
        if not symbol or symbol not in prices:
            continue
        vol = run_async(get_realized_vol(symbol, hours=vol_hours, interval=vol_interval))
        if vol is None or vol <= 0:
            continue
        result[series] = {"spot": prices[symbol], "vol": vol}
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
    )

    underlying = _fetch_underlying_data(series, config.vol_lookback_hours, config.vol_interval)
    now = datetime.now(timezone.utc)
    signals_created = []

    for market in markets:
        ticker = market["ticker"]
        series_ticker = market["_series_ticker"]

        if series_ticker not in underlying:
            continue

        if _has_open_kalshi_position(session, user_id, ticker):
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
        market_price = float(market.get("last_price_dollars", 0))

        if market_price <= 0:
            continue

        if floor_strike is not None:
            floor_strike = float(floor_strike)
        if cap_strike is not None:
            cap_strike = float(cap_strike)

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

        count = eff["contracts_per_signal"]
        max_cost = eff["max_cost_per_signal"]
        if market_price > 0 and market_price * count > max_cost:
            count = int(max_cost / market_price)
        if count < 1:
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
            try:
                yes_price_cents = int(round(market_price * 100))
                order_result = run_async(client.create_order(
                    ticker=ticker, side="yes", count=count,
                    yes_price_cents=yes_price_cents,
                ))
                order = order_result.get("order", order_result)
                signal.exchange_order_id = order.get("order_id")
                signal.status = "placed"
                logger.info("LIVE KALSHI BUY %s: %d @ $%.2f", ticker, count, market_price)
            except Exception as e:
                signal.status = "cancelled"
                signal.error_message = str(e)[:200]
                logger.exception("Failed to place Kalshi order for %s", ticker)
        else:
            signal.status = "filled"
            signal.fill_price = market_price
            signal.fill_quantity = float(count)
            signal.filled_at = datetime.now(timezone.utc)
            logger.info(
                "PAPER KALSHI BUY %s: %d @ $%.2f (model=%.0f%% edge=+%.0f%%)",
                ticker, count, market_price,
                result.model_prob * 100, result.edge * 100,
            )

        session.add(signal)
        signals_created.append(signal)

    session.commit()
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
            price = float(market.get("last_price_dollars", 0))
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

        should_exit = False
        exit_reason = ""

        if current_edge <= eff["exit_edge"]:
            should_exit = True
            exit_reason = f"edge_lost ({current_edge:+.1%})"
        elif pnl_pct <= -eff["stop_loss_pct"]:
            should_exit = True
            exit_reason = f"stop_loss ({pnl_pct:.1f}%)"
        elif sig.expiry_time and (sig.expiry_time - now) < timedelta(hours=cfg.min_hours_to_expiry / 2):
            should_exit = True
            exit_reason = "approaching_expiry"
        elif sig.filled_at and (now - sig.filled_at) > timedelta(hours=24):
            should_exit = True
            exit_reason = "max_hold (24h)"

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
