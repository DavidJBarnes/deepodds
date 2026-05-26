import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.bot_config import BotConfig
from app.models.pair_config import PairConfig
from app.models.signal import Signal
from app.services.config_resolver import resolve_crypto_config
from app.services.robinhood_client import RobinhoodClient

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")
MAX_HOLD_HOURS = 24


def _compute_vwap_and_std(candles: list[dict], lookback: int) -> tuple[float, float]:
    if len(candles) < lookback:
        return 0.0, 0.0

    recent = candles[-lookback:]
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
    if std <= 0:
        return 0.0
    return (price - vwap) / std


def _today_pnl(session: Session, user_id) -> float:
    today_utc = datetime.now(timezone.utc).date()
    result = session.execute(
        select(func.coalesce(func.sum(Signal.pnl_usd), 0.0)).where(
            Signal.user_id == user_id,
            func.date(Signal.resolved_at) == today_utc,
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
    exchange: RobinhoodClient | None = None,
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

    overrides = {}
    for pc in session.execute(
        select(PairConfig).where(PairConfig.user_id == user_id, PairConfig.venue == "crypto")
    ).scalars().all():
        overrides[pc.pair] = pc

    signals_created = []

    for pair in pairs:
        if _has_open_position(session, user_id, pair):
            continue

        eff = resolve_crypto_config(config, overrides.get(pair))

        try:
            candles = run_async(_public_candles(pair, config.lookback_periods + 4))
        except Exception:
            logger.exception("Failed to fetch candles for %s", pair)
            continue

        if not candles:
            continue

        vwap, std = _compute_vwap_and_std(candles, config.lookback_periods)
        if vwap <= 0 or std <= 0:
            continue

        try:
            if exchange:
                price = run_async(exchange.get_price(pair))
            else:
                price = float(candles[0].get("close", 0))
        except Exception:
            logger.exception("Failed to get price for %s", pair)
            continue

        if price <= 0:
            continue

        z = compute_z_score(price, vwap, std)

        logger.info(
            "%s: price=%.2f vwap=%.2f std=%.2f z=%.2f (entry=%.1f)",
            pair, price, vwap, std, z, eff["entry_z_score"],
        )

        if z > eff["entry_z_score"]:
            continue

        position_size = eff["position_size_usd"]
        quantity = position_size / price
        cost = position_size

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

        if config.mode == "live" and exchange:
            try:
                result = run_async(
                    exchange.place_market_buy(pair, cost)
                )
                signal.exchange_order_id = result.get("id")
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


async def _public_candles(pair: str, limit: int = 64) -> list[dict]:
    """Fetch candles from public Coinbase API (no auth needed) for VWAP calculation."""
    import time
    import httpx

    product_id = pair
    now = int(time.time())
    start = now - (limit * 900)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
                params={"start": str(start), "end": str(now), "granularity": "FIFTEEN_MINUTE"},
            )
            resp.raise_for_status()
            return resp.json().get("candles", [])
    except Exception:
        logger.warning("Candle fetch failed for %s, skipping", pair)
        return []


def check_exits(
    session: Session,
    exchange_clients: dict[str, RobinhoodClient] | None = None,
) -> int:
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
    pair_overrides: dict[str, dict[str, PairConfig]] = {}
    for uid in user_ids:
        cfg = session.execute(
            select(BotConfig).where(BotConfig.user_id == uid)
        ).scalar_one_or_none()
        if cfg:
            configs[uid] = cfg
        uid_overrides = {}
        for pc in session.execute(
            select(PairConfig).where(PairConfig.user_id == uid, PairConfig.venue == "crypto")
        ).scalars().all():
            uid_overrides[pc.pair] = pc
        pair_overrides[str(uid)] = uid_overrides

    exited = 0
    now = datetime.now(timezone.utc)
    exchange_clients = exchange_clients or {}

    for sig in filled:
        cfg = configs.get(sig.user_id)
        if not cfg:
            continue

        exchange = exchange_clients.get(str(sig.user_id))
        eff = resolve_crypto_config(cfg, pair_overrides.get(str(sig.user_id), {}).get(sig.pair))

        try:
            candles = run_async(_public_candles(sig.pair))
            if not candles:
                continue
            price = float(candles[0]["close"])
            if price <= 0 and exchange:
                price = run_async(exchange.get_price(sig.pair))
        except Exception:
            logger.warning("Failed to get exit price for %s", sig.pair)
            continue

        if price <= 0:
            continue

        pnl_pct = (price - sig.fill_price) / sig.fill_price * 100
        qty = sig.fill_quantity or sig.quantity
        pnl_usd = (price - sig.fill_price) * qty

        try:
            vwap, std = _compute_vwap_and_std(candles, cfg.lookback_periods)
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
        elif sig.filled_at and (now - sig.filled_at) > timedelta(hours=MAX_HOLD_HOURS):
            should_exit = True
            exit_reason = f"max_hold ({MAX_HOLD_HOURS}h)"

        if not should_exit:
            continue

        if cfg.mode == "live" and exchange:
            try:
                run_async(
                    exchange.place_market_sell(sig.pair, qty)
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
    session: Session, user_id, exchange: RobinhoodClient
) -> dict:
    placed = session.execute(
        select(Signal).where(
            Signal.user_id == user_id,
            Signal.signal_type == "live",
            Signal.status == "placed",
            Signal.exchange_order_id.isnot(None),
        )
    ).scalars().all()

    if not placed:
        return {"synced": 0, "filled": 0}

    now = datetime.now(timezone.utc)
    filled_count = 0

    for sig in placed:
        try:
            order = run_async(exchange.get_order(sig.exchange_order_id))
        except Exception:
            logger.warning("Failed to fetch order %s", sig.exchange_order_id)
            continue

        status = order.get("state", order.get("status", ""))

        if status in ("filled",):
            avg_price = float(order.get("average_price", sig.entry_price or 0))
            filled_size = float(order.get("filled_asset_quantity", sig.quantity or 0))
            sig.fill_price = avg_price
            sig.fill_quantity = filled_size
            sig.filled_at = now
            sig.status = "filled"
            sig.cost_usd = avg_price * filled_size
            filled_count += 1
            logger.info("Live fill: %s @ $%.2f x %.6f", sig.pair, avg_price, filled_size)

        elif status in ("canceled", "cancelled", "expired", "failed"):
            sig.status = "cancelled"
            sig.resolved_at = now

    session.commit()
    return {"synced": len(placed), "filled": filled_count}
