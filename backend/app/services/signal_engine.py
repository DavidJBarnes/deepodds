import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bot_config import BotConfig
from app.models.opportunity import Opportunity
from app.models.signal import Signal
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")


def _today_spend(session: Session, user_id) -> int:
    today = date.today()
    result = session.execute(
        select(func.coalesce(func.sum(Signal.cost_cents), 0))
        .where(
            Signal.user_id == user_id,
            func.date(Signal.created_at) == today,
            Signal.status.notin_(["cancelled"]),
        )
    )
    return result.scalar()


def _has_open_signal(session: Session, user_id, ticker: str) -> bool:
    result = session.execute(
        select(Signal.id)
        .where(
            Signal.user_id == user_id,
            Signal.ticker == ticker,
            Signal.status.in_(OPEN_STATUSES),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def evaluate_opportunities(user_id, session: Session, kalshi: KalshiClient | None = None) -> list[Signal]:
    config = session.execute(
        select(BotConfig).where(BotConfig.user_id == user_id)
    ).scalar_one_or_none()

    if not config or not config.enabled:
        return []

    now_iso = datetime.now(timezone.utc).isoformat()
    opps = session.execute(
        select(Opportunity).where(
            Opportunity.model_edge_cents.isnot(None),
            (Opportunity.close_time.is_(None)) | (Opportunity.close_time > now_iso),
        )
    ).scalars().all()

    daily_spent = _today_spend(session, user_id)
    signals_created = []

    for opp in opps:
        edge = opp.model_edge_cents
        if edge is None:
            continue
        abs_edge = abs(edge)
        if abs_edge < config.min_edge_cents:
            continue
        if opp.liquidity < config.min_liquidity:
            continue
        if _has_open_signal(session, user_id, opp.ticker):
            continue

        side = "yes" if edge > 0 else "no"
        if side == "yes":
            limit_price = int(opp.yes_ask or opp.yes_price or opp.model_fair_cents or 50)
        else:
            limit_price = int(opp.no_ask or opp.no_price or (100 - (opp.model_fair_cents or 50)))

        limit_price = max(1, min(99, limit_price))

        max_qty_by_cost = config.max_position_cents // limit_price if limit_price > 0 else 0
        quantity = min(config.max_contracts_per_signal, max_qty_by_cost)
        if quantity < 1:
            continue

        cost = limit_price * quantity
        if daily_spent + cost > config.daily_budget_cents:
            continue

        signal = Signal(
            user_id=user_id,
            opportunity_id=opp.id,
            ticker=opp.ticker,
            side=side,
            action="buy",
            limit_price_cents=limit_price,
            quantity=quantity,
            cost_cents=cost,
            signal_type=config.mode,
            status="signaled",
            model_prob=opp.model_prob,
            model_fair_cents=opp.model_fair_cents,
            model_edge_cents=opp.model_edge_cents,
            implied_vol=opp.implied_vol,
            market_yes_price_cents=opp.yes_price,
            spot_price=opp.spot_price,
            strike_price=opp.strike_price,
            close_time=opp.close_time,
        )

        if config.mode == "live" and kalshi:
            try:
                result = kalshi.place_order(opp.ticker, side, "buy", limit_price, quantity)
                signal.kalshi_order_id = result.get("order", {}).get("order_id")
                signal.status = "placed"
                logger.info("Live order placed: %s %s @ %d¢ x%d", opp.ticker, side, limit_price, quantity)
            except Exception as e:
                signal.status = "cancelled"
                signal.error_message = str(e)
                logger.exception("Failed to place live order for %s", opp.ticker)
        else:
            logger.info("Paper signal: %s %s @ %d¢ x%d (edge=%.1f¢)", opp.ticker, side, limit_price, quantity, abs_edge)

        session.add(signal)
        daily_spent += cost
        signals_created.append(signal)

    session.commit()
    return signals_created


def settle_signals(session: Session) -> int:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    open_signals = session.execute(
        select(Signal).where(
            Signal.status.in_(OPEN_STATUSES),
            Signal.close_time.isnot(None),
            Signal.close_time < now_iso,
        )
    ).scalars().all()

    settled = 0
    for sig in open_signals:
        if sig.spot_price is not None and sig.strike_price is not None:
            won_side = "yes" if sig.spot_price > sig.strike_price else "no"
        else:
            won_side = None

        if won_side is None:
            continue

        sig.settled_side = won_side
        sig.resolved_at = now

        if sig.side == won_side:
            sig.pnl_cents = (100 - sig.limit_price_cents) * sig.quantity
            sig.status = "settled_win"
        else:
            sig.pnl_cents = -(sig.limit_price_cents * sig.quantity)
            sig.status = "settled_loss"

        settled += 1
        logger.info("Settled %s: %s (P&L: %d¢)", sig.ticker, sig.status, sig.pnl_cents)

    session.commit()
    return settled
