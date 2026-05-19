import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bot_config import BotConfig
from app.models.opportunity import Opportunity
from app.models.signal import Signal
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")

# Kalshi fee: 7% of profit, capped at contract price, minimum 2c per contract on fills
KALSHI_FEE_RATE = 0.07
KALSHI_MIN_FEE_CENTS = 2

EDGE_TIERS = [
    ("elite", 80),
    ("high", 50),
    ("moderate", 20),
    ("speculative", 0),
]


def classify_edge_tier(abs_edge: float) -> str:
    for tier_name, threshold in EDGE_TIERS:
        if abs_edge >= threshold:
            return tier_name
    return "speculative"


def _tier_limits(config: BotConfig, tier: str) -> tuple[int, int]:
    if tier == "elite":
        return config.max_position_cents_elite, config.max_contracts_elite
    elif tier == "high":
        return config.max_position_cents_high, config.max_contracts_high
    elif tier == "moderate":
        return config.max_position_cents_moderate, config.max_contracts_moderate
    return config.max_position_cents, config.max_contracts_per_signal


def _estimate_fee(entry_price: int, exit_price: int, quantity: int) -> int:
    profit_per_contract = exit_price - entry_price
    if profit_per_contract <= 0:
        return KALSHI_MIN_FEE_CENTS * quantity
    fee_per_contract = max(KALSHI_MIN_FEE_CENTS, int(profit_per_contract * KALSHI_FEE_RATE))
    return fee_per_contract * quantity


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


def _today_pnl(session: Session, user_id) -> int:
    today = date.today()
    result = session.execute(
        select(func.coalesce(func.sum(Signal.pnl_cents), 0))
        .where(
            Signal.user_id == user_id,
            func.date(Signal.resolved_at) == today,
            Signal.pnl_cents.isnot(None),
        )
    )
    return result.scalar()


def _signals_last_hour(session: Session, user_id) -> int:
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = session.execute(
        select(func.count(Signal.id))
        .where(
            Signal.user_id == user_id,
            Signal.created_at >= one_hour_ago,
            Signal.status.notin_(["cancelled"]),
        )
    )
    return result.scalar()


def _open_exposure(session: Session, user_id) -> int:
    result = session.execute(
        select(func.coalesce(func.sum(Signal.cost_cents), 0))
        .where(
            Signal.user_id == user_id,
            Signal.status.in_(OPEN_STATUSES),
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

    # Daily loss circuit breaker
    if config.daily_loss_limit_cents > 0:
        today_pnl = _today_pnl(session, user_id)
        if today_pnl <= -config.daily_loss_limit_cents:
            logger.warning(
                "Daily loss circuit breaker: today P&L %d¢ <= -%d¢ limit, skipping evaluation",
                today_pnl, config.daily_loss_limit_cents,
            )
            return []

    # Max signals per hour pacing
    if config.max_signals_per_hour > 0:
        recent_signals = _signals_last_hour(session, user_id)
        if recent_signals >= config.max_signals_per_hour:
            logger.info(
                "Pacing: %d signals in last hour >= %d max, skipping evaluation",
                recent_signals, config.max_signals_per_hour,
            )
            return []

    now_iso = datetime.now(timezone.utc).isoformat()
    opps = session.execute(
        select(Opportunity).where(
            Opportunity.model_edge_cents.isnot(None),
            (Opportunity.close_time.is_(None)) | (Opportunity.close_time > now_iso),
        )
    ).scalars().all()

    current_exposure = _open_exposure(session, user_id)
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
        if config.mode == "live" and opp.liquidity <= 0:
            continue
        if _has_open_signal(session, user_id, opp.ticker):
            continue

        side = "yes" if edge > 0 else "no"
        if side == "yes":
            limit_price = int(opp.yes_ask or opp.yes_price or opp.model_fair_cents or 50)
        else:
            limit_price = int(opp.no_ask or opp.no_price or (100 - (opp.model_fair_cents or 50)))

        limit_price = max(1, min(99, limit_price))

        tier = classify_edge_tier(abs_edge)
        tier_max_position, tier_max_contracts = _tier_limits(config, tier)
        max_qty_by_cost = tier_max_position // limit_price if limit_price > 0 else 0
        quantity = min(tier_max_contracts, max_qty_by_cost)
        if quantity < 1:
            continue

        cost = limit_price * quantity

        # Primary gate: max open exposure
        exposure_limit = config.max_exposure_cents
        elite_pct = config.tier_budget_pct_elite
        high_pct = config.tier_budget_pct_high
        if tier == "elite":
            effective_exposure = exposure_limit
        elif tier == "high":
            effective_exposure = exposure_limit * (100 - elite_pct) // 100
        else:
            effective_exposure = exposure_limit * (100 - elite_pct - high_pct) // 100

        if current_exposure + cost > effective_exposure:
            continue

        # Optional hard cap: daily budget (0 = disabled)
        if config.daily_budget_cents > 0 and daily_spent + cost > config.daily_budget_cents:
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
            edge_tier=tier,
            implied_vol=opp.implied_vol,
            market_yes_price_cents=opp.yes_price,
            spot_price=opp.spot_price,
            strike_price=opp.strike_price,
            cap_strike=opp.cap_strike,
            close_time=opp.close_time,
        )

        if config.mode == "live" and kalshi:
            try:
                result = asyncio.run(kalshi.place_order(opp.ticker, side, "buy", limit_price, quantity))
                signal.kalshi_order_id = result.get("order", {}).get("order_id")
                signal.status = "placed"
                logger.info("Live order placed: %s %s @ %d¢ x%d", opp.ticker, side, limit_price, quantity)
            except Exception as e:
                signal.status = "cancelled"
                signal.error_message = str(e)
                logger.exception("Failed to place live order for %s", opp.ticker)
        else:
            logger.info("Paper signal: %s %s @ %d¢ x%d (edge=%.1f¢, tier=%s)", opp.ticker, side, limit_price, quantity, abs_edge, tier)

        session.add(signal)
        current_exposure += cost
        daily_spent += cost
        signals_created.append(signal)

    session.commit()
    return signals_created


def simulate_fills(session: Session) -> int:
    paper_signals = session.execute(
        select(Signal).where(
            Signal.status == "signaled",
            Signal.signal_type == "paper",
        )
    ).scalars().all()

    filled = 0
    now = datetime.now(timezone.utc)
    for sig in paper_signals:
        opp = session.execute(
            select(Opportunity).where(Opportunity.ticker == sig.ticker)
        ).scalar_one_or_none()
        if not opp:
            continue

        if sig.side == "yes":
            current_ask = opp.yes_ask or opp.yes_price
        else:
            current_ask = opp.no_ask or opp.no_price

        if current_ask is None:
            continue

        if current_ask <= sig.limit_price_cents:
            sig.status = "filled"
            sig.fill_price_cents = int(current_ask)
            sig.fill_quantity = sig.quantity
            sig.filled_at = now
            filled += 1
            logger.info("Paper fill: %s %s @ %d¢ (limit %d¢)", sig.ticker, sig.side, sig.fill_price_cents, sig.limit_price_cents)

    session.commit()
    return filled


def check_take_profits(session: Session) -> int:
    filled_signals = session.execute(
        select(Signal).where(
            Signal.status == "filled",
            Signal.signal_type == "paper",
            Signal.fill_price_cents.isnot(None),
        )
    ).scalars().all()

    if not filled_signals:
        return 0

    user_ids = {s.user_id for s in filled_signals}
    configs = session.execute(
        select(BotConfig).where(BotConfig.user_id.in_(user_ids))
    ).scalars().all()
    config_map = {c.user_id: c for c in configs}

    exited = 0
    now = datetime.now(timezone.utc)
    for sig in filled_signals:
        cfg = config_map.get(sig.user_id)
        if not cfg or cfg.take_profit_cents <= 0:
            continue

        opp = session.execute(
            select(Opportunity).where(Opportunity.ticker == sig.ticker)
        ).scalar_one_or_none()
        if not opp:
            continue

        if sig.side == "yes":
            current_bid = opp.yes_price
        else:
            current_bid = opp.no_price

        if current_bid is None:
            continue

        unrealized_per_contract = int(current_bid) - sig.fill_price_cents

        # Take-profit check
        if unrealized_per_contract >= cfg.take_profit_cents:
            exit_price = int(current_bid)
            qty = sig.fill_quantity or sig.quantity
            gross_pnl = (exit_price - sig.fill_price_cents) * qty
            fees = _estimate_fee(sig.fill_price_cents, exit_price, qty)
            sig.status = "settled_win"
            sig.exit_price_cents = exit_price
            sig.pnl_cents = gross_pnl - fees
            sig.resolved_at = now
            exited += 1
            logger.info(
                "Take-profit: %s %s exit @ %d¢ (entry %d¢, gross +%d¢, fees %d¢, net +%d¢)",
                sig.ticker, sig.side, exit_price, sig.fill_price_cents, gross_pnl, fees, sig.pnl_cents,
            )
            continue

        # Stop-loss check
        if cfg.stop_loss_cents > 0 and unrealized_per_contract <= -cfg.stop_loss_cents:
            exit_price = int(current_bid)
            qty = sig.fill_quantity or sig.quantity
            pnl = (exit_price - sig.fill_price_cents) * qty
            sig.status = "settled_loss"
            sig.exit_price_cents = exit_price
            sig.pnl_cents = pnl
            sig.resolved_at = now
            exited += 1
            logger.info(
                "Stop-loss: %s %s exit @ %d¢ (entry %d¢, loss %d¢)",
                sig.ticker, sig.side, exit_price, sig.fill_price_cents, pnl,
            )

    session.commit()
    return exited


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
        opp = session.execute(
            select(Opportunity).where(Opportunity.ticker == sig.ticker)
        ).scalar_one_or_none()

        current_spot = opp.spot_price if opp else sig.spot_price
        strike = sig.strike_price
        cap = sig.cap_strike
        s_type = opp.strike_type if opp else None

        if current_spot is not None and strike is not None:
            if s_type == "between" and cap is not None:
                won_side = "yes" if strike < current_spot < cap else "no"
            elif s_type == "below":
                won_side = "yes" if current_spot < strike else "no"
            else:
                won_side = "yes" if current_spot > strike else "no"
        else:
            won_side = None

        if won_side is None:
            continue

        sig.spot_price = current_spot

        entry_price = sig.fill_price_cents or sig.limit_price_cents
        qty = sig.fill_quantity or sig.quantity
        sig.settled_side = won_side
        sig.resolved_at = now

        if sig.side == won_side:
            gross_pnl = (100 - entry_price) * qty
            fees = _estimate_fee(entry_price, 100, qty)
            sig.pnl_cents = gross_pnl - fees
            sig.status = "settled_win"
        else:
            sig.pnl_cents = -(entry_price * qty)
            sig.status = "settled_loss"

        settled += 1
        logger.info("Settled %s: %s (P&L: %d¢)", sig.ticker, sig.status, sig.pnl_cents)

    session.commit()
    return settled


def sync_live_orders(session: Session, user_id, kalshi: "KalshiClient") -> dict:
    live_signals = session.execute(
        select(Signal).where(
            Signal.user_id == user_id,
            Signal.signal_type == "live",
            Signal.status.in_(("placed", "filled")),
            Signal.kalshi_order_id.isnot(None),
        )
    ).scalars().all()

    if not live_signals:
        return {"synced": 0, "filled": 0, "settled": 0}

    now = datetime.now(timezone.utc)
    filled_count = 0
    settled_count = 0

    for sig in live_signals:
        try:
            order = asyncio.run(kalshi.get_order(sig.kalshi_order_id))
        except Exception:
            logger.warning("Failed to fetch order %s for %s", sig.kalshi_order_id, sig.ticker)
            continue

        order_status = order.get("status", "")

        if sig.status == "placed" and order_status in ("executed", "filled"):
            price_dollars = order.get("yes_price_dollars") if sig.side == "yes" else order.get("no_price_dollars")
            fill_count_str = order.get("fill_count_fp", "0")
            fill_count = int(float(fill_count_str)) if fill_count_str else sig.quantity
            if price_dollars:
                sig.fill_price_cents = int(float(price_dollars) * 100)
            sig.fill_quantity = fill_count or sig.quantity
            sig.filled_at = now
            sig.status = "filled"
            sig.cost_cents = (sig.fill_price_cents or sig.limit_price_cents) * (sig.fill_quantity or sig.quantity)
            filled_count += 1
            logger.info(
                "Live fill synced: %s %s @ %d¢ x%d",
                sig.ticker, sig.side, sig.fill_price_cents, sig.fill_quantity,
            )

        if order_status == "canceled":
            sig.status = "cancelled"
            sig.resolved_at = now
            logger.info("Live order cancelled on Kalshi: %s", sig.ticker)
            continue

        try:
            market = asyncio.run(kalshi.get_market(sig.ticker))
        except Exception:
            logger.warning("Failed to fetch market %s", sig.ticker)
            continue

        mkt = market.get("market", market)
        market_result = mkt.get("result", "")
        market_status = mkt.get("status", "")

        if market_status in ("closed", "settled", "finalized") and market_result:
            entry_price = sig.fill_price_cents or sig.limit_price_cents
            qty = sig.fill_quantity or sig.quantity

            if sig.status == "placed":
                if order_status in ("executed", "filled"):
                    pass
                else:
                    sig.status = "cancelled"
                    sig.resolved_at = now
                    logger.info("Live order expired unfilled: %s", sig.ticker)
                    continue

            sig.settled_side = market_result
            sig.resolved_at = now

            if sig.side == market_result:
                gross_pnl = (100 - entry_price) * qty
                fees = _estimate_fee(entry_price, 100, qty)
                sig.pnl_cents = gross_pnl - fees
                sig.status = "settled_win"
            else:
                sig.pnl_cents = -(entry_price * qty)
                sig.status = "settled_loss"

            settled_count += 1
            logger.info(
                "Live settled: %s %s (P&L: %d¢)",
                sig.ticker, sig.status, sig.pnl_cents,
            )

    session.commit()
    return {"synced": len(live_signals), "filled": filled_count, "settled": settled_count}
