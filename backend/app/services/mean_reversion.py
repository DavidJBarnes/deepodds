import logging
import math
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.bot_config import BotConfig
from app.models.signal import Signal
from app.services.coinbase_client import CoinbaseClient

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")


def _compute_vwap_and_std(candles: list[dict], lookback: int) -> tuple[float, float]:
    """Compute VWAP and standard deviation of close prices over a window.

    VWAP (Volume-Weighted Average Price): the average price weighted by
    how much volume traded at each level. A better "fair price" than a
    simple average because it accounts for where actual trading happened.

    Returns (vwap, std_dev). Both 0.0 if insufficient data.
    """
    if len(candles) < lookback:
        return 0.0, 0.0

    recent = candles[:lookback]
    closes = []
    total_pv = 0.0
    total_vol = 0.0

    for c in recent:
        close = float(c.get("close", 0))
        volume = float(c.get("volume", 0))
        if close <= 0 or volume <= 0:
            continue
        closes.append(close)
        total_pv += close * volume
        total_vol += volume

    if total_vol <= 0 or len(closes) < lookback // 2:
        return 0.0, 0.0

    vwap = total_pv / total_vol

    mean = sum(closes) / len(closes)
    variance = sum((c - mean) ** 2 for c in closes) / (len(closes) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    return vwap, std


def compute_z_score(price: float, vwap: float, std: float) -> float:
    """Z-score: how many standard deviations price is from VWAP.

    Negative = price below VWAP (oversold). Positive = above (overbought).
    A z-score of -2.0 means price is 2 standard deviations below the
    volume-weighted average — historically a strong mean-reversion signal.
    """
    if std <= 0:
        return 0.0
    return (price - vwap) / std


def _today_pnl(session: Session, user_id) -> float:
    today = date.today()
    result = session.execute(
        select(func.coalesce(func.sum(Signal.pnl_usd), 0.0)).where(
            Signal.user_id == user_id,
            func.date(Signal.resolved_at) == today,
            Signal.pnl_usd.isnot(None),
        )
    )
    return float(result.scalar())


def _signals_last_hour(session: Session, user_id) -> int:
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = session.execute(
        select(func.count(Signal.id)).where(
            Signal.user_id == user_id,
            Signal.created_at >= one_hour_ago,
            Signal.status.notin_(["cancelled"]),
        )
    )
    return result.scalar()


def _open_positions(session: Session, user_id) -> list[Signal]:
    return list(
        session.execute(
            select(Signal).where(
                Signal.user_id == user_id, Signal.status.in_(OPEN_STATUSES)
            )
        )
        .scalars()
        .all()
    )


def _has_open_position(session: Session, user_id, pair: str) -> bool:
    result = session.execute(
        select(Signal.id)
        .where(
            Signal.user_id == user_id,
            Signal.pair == pair,
            Signal.status.in_(OPEN_STATUSES),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def scan_entries(
    user_id,
    session: Session,
    coinbase: CoinbaseClient | None = None,
) -> list[Signal]:
    config = session.execute(
        select(BotConfig).where(BotConfig.user_id == user_id)
    ).scalar_one_or_none()

    if not config or not config.enabled:
        return []

    if config.daily_loss_limit_usd > 0:
        if _today_pnl(session, user_id) <= -config.daily_loss_limit_usd:
            logger.warning("Daily loss limit hit — skipping scan")
            return []

    if config.max_signals_per_hour > 0:
        if _signals_last_hour(session, user_id) >= config.max_signals_per_hour:
            return []

    open_pos = _open_positions(session, user_id)
    if len(open_pos) >= config.max_open_positions:
        return []

    pairs = [p.strip() for p in config.pairs.split(",") if p.strip()]
    signals_created = []

    for pair in pairs:
        if _has_open_position(session, user_id, pair):
            continue

        try:
            candles = run_async(
                coinbase.get_candles(pair, "FIFTEEN_MINUTE", config.lookback_periods + 4)
                if coinbase
                else _paper_candles(pair)
            )
        except Exception:
            logger.exception("Failed to fetch candles for %s", pair)
            continue

        vwap, std = _compute_vwap_and_std(candles, config.lookback_periods)
        if vwap <= 0 or std <= 0:
            continue

        try:
            price = float(candles[0].get("close", 0)) if candles else 0
            if price <= 0:
                price = run_async(coinbase.get_price(pair)) if coinbase else 0
        except Exception:
            logger.exception("Failed to get price for %s", pair)
            continue

        if price <= 0:
            continue

        z = compute_z_score(price, vwap, std)

        logger.info(
            "%s: price=%.2f vwap=%.2f std=%.2f z=%.2f (entry=%.1f)",
            pair, price, vwap, std, z, config.entry_z_score,
        )

        if z > config.entry_z_score:
            continue

        quantity = config.position_size_usd / price
        cost = config.position_size_usd

        signal = Signal(
            user_id=user_id,
            pair=pair,
            side="buy",
            signal_type=config.mode,
            status="signaled",
            entry_price=price,
            quantity=quantity,
            cost_usd=cost,
            z_score=z,
            vwap=vwap,
        )

        if config.mode == "live" and coinbase:
            try:
                result = run_async(
                    coinbase.place_market_buy(pair, cost)
                )
                order_resp = result.get("success_response", result)
                signal.coinbase_order_id = order_resp.get("order_id")
                signal.status = "placed"
                logger.info(
                    "LIVE BUY %s: $%.2f @ $%.2f (z=%.2f)",
                    pair, cost, price, z,
                )
            except Exception as e:
                signal.status = "cancelled"
                signal.error_message = str(e)[:200]
                logger.exception("Failed to place buy for %s", pair)
        else:
            signal.status = "filled"
            signal.fill_price = price
            signal.fill_quantity = quantity
            signal.filled_at = datetime.now(timezone.utc)
            logger.info(
                "PAPER BUY %s: $%.2f @ $%.2f (z=%.2f)",
                pair, cost, price, z,
            )

        session.add(signal)
        signals_created.append(signal)

    session.commit()
    return signals_created


async def _paper_candles(pair: str) -> list[dict]:
    """Fetch candles from public Coinbase API (no auth needed) for paper mode."""
    import time
    import httpx

    product_id = pair
    now = int(time.time())
    start = now - (64 * 900)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
                params={"start": str(start), "end": str(now), "granularity": "FIFTEEN_MINUTE"},
            )
            resp.raise_for_status()
            return resp.json().get("candles", [])
    except Exception:
        from app.services.binance_client import get_crypto_prices
        prices = await get_crypto_prices()
        symbol = pair.replace("-USD", "")
        price = prices.get(symbol, 0)
        if price <= 0:
            return []
        return [{"close": str(price), "volume": "100", "open": str(price), "high": str(price), "low": str(price)}] * 20


def check_exits(
    session: Session,
    coinbase_clients: dict[str, CoinbaseClient] | None = None,
) -> int:
    """Check filled positions for exit conditions (mean reversion or stop-loss)."""
    filled = session.execute(
        select(Signal).where(
            Signal.status == "filled",
            Signal.fill_price.isnot(None),
        )
    ).scalars().all()

    if not filled:
        return 0

    user_ids = {s.user_id for s in filled}
    configs = {}
    for uid in user_ids:
        cfg = session.execute(
            select(BotConfig).where(BotConfig.user_id == uid)
        ).scalar_one_or_none()
        if cfg:
            configs[uid] = cfg

    exited = 0
    now = datetime.now(timezone.utc)
    coinbase_clients = coinbase_clients or {}

    for sig in filled:
        cfg = configs.get(sig.user_id)
        if not cfg:
            continue

        coinbase = coinbase_clients.get(str(sig.user_id))

        try:
            if coinbase:
                price = run_async(coinbase.get_price(sig.pair))
            else:
                candles = run_async(_paper_candles(sig.pair))
                price = float(candles[0]["close"]) if candles else 0
        except Exception:
            logger.warning("Failed to get exit price for %s", sig.pair)
            continue

        if price <= 0:
            continue

        pnl_pct = (price - sig.fill_price) / sig.fill_price * 100
        qty = sig.fill_quantity or sig.quantity
        pnl_usd = (price - sig.fill_price) * qty

        try:
            if coinbase:
                candles = run_async(
                    coinbase.get_candles(sig.pair, "FIFTEEN_MINUTE", cfg.lookback_periods + 4)
                )
            else:
                candles = run_async(_paper_candles(sig.pair))
            vwap, std = _compute_vwap_and_std(candles, cfg.lookback_periods)
            z = compute_z_score(price, vwap, std) if vwap > 0 and std > 0 else 0
        except Exception:
            z = 0

        should_exit = False
        exit_reason = ""

        if z >= cfg.exit_z_score and z != 0:
            should_exit = True
            exit_reason = f"mean_reversion (z={z:.2f})"
        elif pnl_pct <= -cfg.stop_loss_pct:
            should_exit = True
            exit_reason = f"stop_loss ({pnl_pct:.1f}%)"

        if not should_exit:
            continue

        if cfg.mode == "live" and coinbase:
            try:
                run_async(
                    coinbase.place_market_sell(sig.pair, qty)
                )
                logger.info("LIVE SELL %s: %s", sig.pair, exit_reason)
            except Exception:
                logger.exception("Failed to place sell for %s", sig.pair)
                continue

        sig.exit_price = price
        sig.exit_z_score = z
        sig.pnl_usd = round(pnl_usd, 4)
        sig.pnl_pct = round(pnl_pct, 2)
        sig.resolved_at = now
        sig.status = "settled_win" if pnl_usd >= 0 else "settled_loss"

        exited += 1
        logger.info(
            "%s %s: exit @ $%.2f (entry $%.2f, %s, P&L $%.2f / %.1f%%)",
            sig.status.upper(), sig.pair, price, sig.fill_price,
            exit_reason, pnl_usd, pnl_pct,
        )

    session.commit()
    return exited


def sync_live_orders(
    session: Session, user_id, coinbase: CoinbaseClient
) -> dict:
    """Sync placed orders with Coinbase to detect fills."""
    placed = session.execute(
        select(Signal).where(
            Signal.user_id == user_id,
            Signal.signal_type == "live",
            Signal.status == "placed",
            Signal.coinbase_order_id.isnot(None),
        )
    ).scalars().all()

    if not placed:
        return {"synced": 0, "filled": 0}

    now = datetime.now(timezone.utc)
    filled_count = 0

    for sig in placed:
        try:
            order = run_async(coinbase.get_order(sig.coinbase_order_id))
        except Exception:
            logger.warning("Failed to fetch order %s", sig.coinbase_order_id)
            continue

        status = order.get("status", "")

        if status in ("FILLED",):
            avg_price = float(order.get("average_filled_price", sig.entry_price or 0))
            filled_size = float(order.get("filled_size", sig.quantity or 0))
            sig.fill_price = avg_price
            sig.fill_quantity = filled_size
            sig.filled_at = now
            sig.status = "filled"
            sig.cost_usd = avg_price * filled_size
            filled_count += 1
            logger.info("Live fill: %s @ $%.2f x %.6f", sig.pair, avg_price, filled_size)

        elif status in ("CANCELLED", "EXPIRED", "FAILED"):
            sig.status = "cancelled"
            sig.resolved_at = now

    session.commit()
    return {"synced": len(placed), "filled": filled_count}
