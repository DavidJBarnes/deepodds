"""Exit loop — checks filled positions for exit conditions."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.signal import Signal
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger("scanner.exit")

_VENUE_CRYPTO = "kalshi_crypto"
_VENUE_CLIMATE = "kalshi_climate"


def run_exit_loop(session: Session, engine: Engine) -> None:
    """Check filled positions for stop-loss, take-profit, edge-lost, expiry."""

    filled = session.execute(
        select(Signal).where(
            Signal.venue.in_([_VENUE_CRYPTO, _VENUE_CLIMATE]),
            Signal.status == "filled",
            Signal.fill_price.isnot(None),
        )
    ).scalars().all()

    if not filled:
        return

    user_ids = {s.user_id for s in filled}
    configs: dict = {}
    for uid in user_ids:
        cfg = session.execute(
            select(CryptoConfig).where(CryptoConfig.user_id == uid)
        ).scalar_one_or_none()
        if cfg:
            configs[uid] = ("crypto", cfg)
            continue
        ccfg = session.execute(
            select(ClimateConfig).where(ClimateConfig.user_id == uid)
        ).scalar_one_or_none()
        if ccfg:
            configs[uid] = ("climate", ccfg)

    clients: dict[str, KalshiClient] = {}
    now = datetime.now(timezone.utc)
    exited = 0

    for sig in filled:
        cfg_tuple = configs.get(sig.user_id)
        if not cfg_tuple:
            continue
        _, cfg = cfg_tuple

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

        if not sig.market_ticker:
            continue

        try:
            market_data = run_async(
                (client or KalshiClient.public()).get_market(sig.market_ticker)
            )
            price = float(
                market_data.get("yes_bid_dollars")
                or market_data.get("last_price_dollars", 0)
            )
        except Exception:
            logger.warning("Exit: failed to get price for %s", sig.market_ticker)
            continue

        if price <= 0:
            continue

        fill_price = sig.fill_price or 0
        qty = sig.fill_quantity or sig.quantity or 0
        pnl_pct = (price - fill_price) / fill_price * 100 if fill_price > 0 else 0
        pnl_usd = (price - fill_price) * qty
        hold_minutes = (now - sig.filled_at).total_seconds() / 60 if sig.filled_at else 999
        min_hold = getattr(cfg, "min_hold_minutes", 0)
        fee_estimate_pct = 0.07
        adjusted_pnl_pct = pnl_pct - fee_estimate_pct
        stops_enabled = cfg.stop_loss_pct > 0

        should_exit = False
        exit_reason = ""

        if stops_enabled and adjusted_pnl_pct <= -cfg.stop_loss_pct * 2:
            should_exit = True
            exit_reason = f"catastrophic_stop ({pnl_pct:.1f}%)"
        elif stops_enabled and adjusted_pnl_pct <= -cfg.stop_loss_pct and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"stop_loss ({pnl_pct:.1f}%)"
        elif sig.expiry_time and (sig.expiry_time - now) < timedelta(hours=getattr(cfg, "min_hours_to_expiry", 2) / 2):
            should_exit = True
            exit_reason = "approaching_expiry"
        elif sig.expiry_time and now > sig.expiry_time + timedelta(hours=2):
            should_exit = True
            exit_reason = "post_expiry_orphan"
        elif getattr(cfg, "take_profit_pct", 0) > 0 and pnl_pct >= cfg.take_profit_pct and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"take_profit ({pnl_pct:.1f}%)"

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
                sig.exit_price = price
                sig.status = "closing"
                session.commit()
                logger.info("LIVE SELL %s: %s", sig.market_ticker, exit_reason)
                exited += 1
            except Exception:
                logger.exception("Exit: failed to sell %s", sig.market_ticker)
            continue

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
