import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.kalshi_config import KalshiConfig
from app.models.pair_config import PairConfig
from app.models.signal import Signal
from app.services.config_resolver import resolve_kalshi_config
from app.services.kalshi_client import KalshiClient
from app.services.mean_reversion import _compute_vwap_and_std, compute_z_score

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")


def _kalshi_candles_to_generic(candles: list[dict]) -> list[dict]:
    result = []
    for c in candles:
        price = c.get("price", {})
        close = price.get("close_dollars")
        volume = c.get("volume_fp")
        if close is None or volume is None:
            continue
        close_f = float(close)
        vol_f = float(volume)
        if close_f <= 0 or vol_f <= 0:
            continue
        result.append({"close": str(close_f), "volume": str(vol_f)})
    return result


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

    markets = _discover_markets(
        client or KalshiClient.public(),
        series,
        config.min_volume_24h,
        config.min_price,
        config.max_price,
        config.min_hours_to_expiry,
    )

    now_ts = int(time.time())
    lookback_seconds = config.lookback_periods * config.candle_interval * 60
    signals_created = []

    for market in markets:
        ticker = market["ticker"]
        series_ticker = market["_series_ticker"]

        if _has_open_kalshi_position(session, user_id, ticker):
            continue

        if len(open_pos) + len(signals_created) >= config.max_open_positions:
            break

        eff = resolve_kalshi_config(config, overrides.get(series_ticker))

        try:
            candles = run_async(client.get_candlesticks(
                series_ticker, ticker,
                start_ts=now_ts - lookback_seconds - 300,
                end_ts=now_ts,
                period_interval=config.candle_interval,
            ))
        except Exception:
            logger.warning("Failed to fetch candles for %s", ticker)
            continue

        generic = _kalshi_candles_to_generic(candles)
        if not generic:
            continue

        vwap, std = _compute_vwap_and_std(generic, config.lookback_periods)
        if vwap <= 0 or std <= 0:
            continue

        price = float(market.get("last_price_dollars", 0))
        if price <= 0:
            continue

        z = compute_z_score(price, vwap, std)

        logger.info(
            "KALSHI %s: price=$%.2f vwap=$%.4f std=$%.4f z=%.2f (entry=%.1f)",
            ticker, price, vwap, std, z, eff["entry_z_score"],
        )

        if z > eff["entry_z_score"]:
            continue

        count = eff["contracts_per_signal"]
        cost = price * count

        signal = Signal(
            user_id=user_id,
            venue="kalshi",
            pair=series_ticker,
            side="buy",
            signal_type=config.mode,
            status="signaled",
            entry_price=price,
            quantity=float(count),
            cost_usd=cost,
            z_score=z,
            vwap=vwap,
            market_ticker=ticker,
            event_ticker=market.get("event_ticker"),
            expiry_time=market.get("_close_dt"),
        )

        if config.mode == "live" and client:
            try:
                yes_price_cents = int(round(price * 100))
                result = run_async(client.create_order(
                    ticker=ticker, side="yes", count=count,
                    yes_price_cents=yes_price_cents,
                ))
                order = result.get("order", result)
                signal.exchange_order_id = order.get("order_id")
                signal.status = "placed"
                logger.info("LIVE KALSHI BUY %s: %d @ $%.2f", ticker, count, price)
            except Exception as e:
                signal.status = "cancelled"
                signal.error_message = str(e)[:200]
                logger.exception("Failed to place Kalshi order for %s", ticker)
        else:
            signal.status = "filled"
            signal.fill_price = price
            signal.fill_quantity = float(count)
            signal.filled_at = datetime.now(timezone.utc)
            logger.info("PAPER KALSHI BUY %s: %d @ $%.2f (z=%.2f)", ticker, count, price, z)

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

    exited = 0
    now = datetime.now(timezone.utc)
    now_ts = int(time.time())
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

        lookback_seconds = cfg.lookback_periods * cfg.candle_interval * 60
        try:
            candles = run_async((client or KalshiClient.public()).get_candlesticks(
                sig.pair, sig.market_ticker,
                start_ts=now_ts - lookback_seconds - 300,
                end_ts=now_ts,
                period_interval=cfg.candle_interval,
            ))
            generic = _kalshi_candles_to_generic(candles)
            vwap, std = _compute_vwap_and_std(generic, cfg.lookback_periods)
            z = compute_z_score(price, vwap, std) if vwap > 0 and std > 0 else 0
        except Exception:
            z = 0

        should_exit = False
        exit_reason = ""

        if z >= eff["exit_z_score"] and z != 0 and price >= sig.fill_price:
            should_exit = True
            exit_reason = f"mean_reversion (z={z:.2f})"
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
        sig.exit_z_score = z
        sig.pnl_usd = round(pnl_usd, 4)
        sig.pnl_pct = round(pnl_pct, 2)
        sig.resolved_at = now
        sig.status = "settled_win" if pnl_usd >= 0 else "settled_loss"

        exited += 1
        logger.info(
            "KALSHI %s %s: exit @ $%.2f (entry $%.2f, %s, P&L $%.4f / %.1f%%)",
            sig.status.upper(), sig.market_ticker, price, sig.fill_price,
            exit_reason, pnl_usd, pnl_pct,
        )

    session.commit()
    return exited
