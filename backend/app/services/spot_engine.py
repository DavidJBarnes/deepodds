import logging
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.bot_config import BotConfig
from app.models.spot_position import SpotPosition
from app.models.spot_trade import SpotTrade
from app.models.user import User
from app.services.coinbase_client import CoinbaseClient

logger = logging.getLogger(__name__)

# Coinbase Advanced Trade taker fee (market orders)
COINBASE_TAKER_FEE_RATE = 0.005


def _get_redis():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _get_btc_price() -> tuple[float | None, float | None, float | None]:
    r = _get_redis()
    price_str = r.get("spot:btc:price")
    high_1h_str = r.get("spot:btc:high_1h")
    high_4h_str = r.get("spot:btc:high_4h")
    price = float(price_str) if price_str else None
    high_1h = float(high_1h_str) if high_1h_str else None
    high_4h = float(high_4h_str) if high_4h_str else None
    return price, high_1h, high_4h


def check_dip_buys(session: Session) -> int:
    price, _high_1h, high_4h = _get_btc_price()
    if not price or price <= 0 or high_4h is None or high_4h <= 0:
        logger.debug("No BTC price in Redis, skipping dip check")
        return 0

    dip_pct = (high_4h - price) / high_4h * 100

    configs = session.execute(
        select(BotConfig).where(BotConfig.spot_enabled.is_(True))
    ).scalars().all()

    buys = 0
    for config in configs:
        if dip_pct < config.spot_dip_pct:
            continue

        open_position = session.execute(
            select(SpotPosition).where(
                SpotPosition.user_id == config.user_id,
                SpotPosition.status == "open",
            )
        ).scalar_one_or_none()

        current_position_usd = open_position.cost_basis_usd if open_position else 0
        if current_position_usd >= config.spot_max_position_usd:
            continue

        cooldown_cutoff = datetime.now(timezone.utc) - timedelta(minutes=config.spot_cooldown_minutes)
        recent_buy = session.execute(
            select(SpotTrade).where(
                SpotTrade.user_id == config.user_id,
                SpotTrade.side == "buy",
                SpotTrade.created_at >= cooldown_cutoff,
            ).limit(1)
        ).scalar_one_or_none()
        if recent_buy:
            continue

        buy_usd = min(config.spot_buy_amount_usd, config.spot_max_position_usd - current_position_usd)
        if buy_usd <= 0:
            continue

        quantity_btc = buy_usd / price

        buy_fee = round(buy_usd * COINBASE_TAKER_FEE_RATE, 2)

        if config.spot_mode == "live":
            user = session.execute(select(User).where(User.id == config.user_id)).scalar_one()
            if not user.coinbase_api_key or not user.coinbase_api_secret:
                logger.warning("User %s has no Coinbase keys, skipping live buy", config.user_id)
                continue

            import asyncio
            cb = CoinbaseClient(user.coinbase_api_key, user.coinbase_api_secret)
            try:
                result = asyncio.run(cb.create_market_order("BUY", "BTC-USD", buy_usd))
                order_id = result.get("success_response", {}).get("order_id")
            except Exception:
                logger.exception("Coinbase buy failed for user %s", config.user_id)
                continue

            trade = SpotTrade(
                user_id=config.user_id, side="buy", price_usd=price,
                quantity_btc=quantity_btc, amount_usd=buy_usd,
                trigger="dip", status="filled", coinbase_order_id=order_id,
                fee_usd=buy_fee,
            )
        else:
            trade = SpotTrade(
                user_id=config.user_id, side="buy", price_usd=price,
                quantity_btc=quantity_btc, amount_usd=buy_usd,
                trigger="dip", status="filled", fee_usd=buy_fee,
            )

        session.add(trade)

        if open_position:
            total_cost = open_position.cost_basis_usd + buy_usd
            total_btc = open_position.quantity_btc + quantity_btc
            open_position.entry_price_usd = total_cost / total_btc
            open_position.quantity_btc = total_btc
            open_position.cost_basis_usd = total_cost
        else:
            session.add(SpotPosition(
                user_id=config.user_id, entry_price_usd=price,
                quantity_btc=quantity_btc, cost_basis_usd=buy_usd,
            ))

        session.commit()
        buys += 1
        logger.info(
            "Spot BUY [%s] user=%s price=$%.2f amount=$%.2f dip=%.1f%%",
            config.spot_mode, config.user_id, price, buy_usd, dip_pct,
        )

    return buys


def check_spot_exits(session: Session) -> int:
    price, _high_1h, _high_4h = _get_btc_price()
    if not price or price <= 0:
        return 0

    positions = session.execute(
        select(SpotPosition).where(SpotPosition.status == "open")
    ).scalars().all()

    exits = 0
    for pos in positions:
        config = session.execute(
            select(BotConfig).where(BotConfig.user_id == pos.user_id)
        ).scalar_one_or_none()
        if not config or not config.spot_enabled:
            continue

        change_pct = (price - pos.entry_price_usd) / pos.entry_price_usd * 100

        # Always track peak P&L for trailing stop
        prev_peak = pos.peak_pnl_pct or 0.0
        if change_pct > prev_peak:
            pos.peak_pnl_pct = change_pct

        peak = pos.peak_pnl_pct or 0.0
        trail_distance = config.spot_take_profit_pct / 2.0
        trailing_active = peak >= config.spot_take_profit_pct

        trigger = None
        if trailing_active and (change_pct <= peak - trail_distance or change_pct < config.spot_take_profit_pct):
            trigger = "take_profit"
        elif change_pct <= -config.spot_stop_loss_pct:
            trigger = "stop_loss"

        if not trigger:
            continue

        sell_usd = pos.quantity_btc * price
        buy_fees = pos.cost_basis_usd * COINBASE_TAKER_FEE_RATE
        sell_fee = round(sell_usd * COINBASE_TAKER_FEE_RATE, 2)
        pnl = sell_usd - pos.cost_basis_usd - buy_fees - sell_fee

        if config.spot_mode == "live":
            user = session.execute(select(User).where(User.id == pos.user_id)).scalar_one()
            if not user.coinbase_api_key or not user.coinbase_api_secret:
                continue
            import asyncio
            cb = CoinbaseClient(user.coinbase_api_key, user.coinbase_api_secret)
            try:
                result = asyncio.run(cb.create_market_order("SELL", "BTC-USD", sell_usd))
                order_id = result.get("success_response", {}).get("order_id")
            except Exception:
                logger.exception("Coinbase sell failed for user %s", pos.user_id)
                continue
            trade = SpotTrade(
                user_id=pos.user_id, side="sell", price_usd=price,
                quantity_btc=pos.quantity_btc, amount_usd=sell_usd,
                trigger=trigger, status="filled", coinbase_order_id=order_id,
                fee_usd=sell_fee, pnl_usd=round(pnl, 2),
            )
        else:
            trade = SpotTrade(
                user_id=pos.user_id, side="sell", price_usd=price,
                quantity_btc=pos.quantity_btc, amount_usd=sell_usd,
                trigger=trigger, status="filled",
                fee_usd=sell_fee, pnl_usd=round(pnl, 2),
            )

        session.add(trade)
        pos.status = "closed"
        pos.closed_at = datetime.now(timezone.utc)
        session.commit()
        exits += 1
        logger.info(
            "Spot SELL [%s] user=%s trigger=%s price=$%.2f pnl=$%.2f (fees=$%.2f)",
            config.spot_mode, pos.user_id, trigger, price, pnl, buy_fees + sell_fee,
        )

    # Persist any peak_pnl_pct updates from non-exit iterations
    session.commit()
    return exits
