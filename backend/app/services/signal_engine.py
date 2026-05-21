import asyncio
import logging
import math
from datetime import date, datetime, timedelta, timezone

from scipy.stats import norm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bot_config import BotConfig
from app.models.opportunity import Opportunity
from app.models.signal import Signal
from app.services.binance_client import get_realized_vol
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")

# Kalshi fee: 7% of profit, capped at contract price, minimum 2c per contract on fills
KALSHI_FEE_RATE = 0.07
KALSHI_MIN_FEE_CENTS = 2

MINUTES_PER_YEAR = 365.25 * 24 * 60

EDGE_TIERS = [
    ("elite", 80),
    ("high", 50),
    ("moderate", 20),
    ("speculative", 0),
]

# Edges above this threshold are likely model error, not alpha — cap sizing
EDGE_SANITY_CAP_CENTS = 30


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


LOSS_COOLDOWN = timedelta(hours=2)


def _recently_lost(session: Session, user_id, ticker: str) -> bool:
    cutoff = datetime.now(timezone.utc) - LOSS_COOLDOWN
    result = session.execute(
        select(Signal.id)
        .where(
            Signal.user_id == user_id,
            Signal.ticker == ticker,
            Signal.status == "settled_loss",
            Signal.resolved_at >= cutoff,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def _detect_asset_prefix(ticker: str) -> str:
    """Map a ticker to its Kalshi series prefix for asset concentration checks."""
    upper = ticker.upper()
    for prefix in ("KXSILVER", "KXGOLD", "KXDOGE", "KXXRP", "KXSOL", "KXETH", "KXBTC"):
        if upper.startswith(prefix):
            return prefix
    return "KXBTC"


def _asset_position_count(session: Session, user_id, asset_prefix: str) -> int:
    """Count open positions on tickers starting with asset prefix (e.g., 'KXBTC', 'KXETH')."""
    result = session.execute(
        select(func.count(Signal.id))
        .where(
            Signal.user_id == user_id,
            Signal.ticker.like(f"{asset_prefix}%"),
            Signal.status.in_(OPEN_STATUSES),
        )
    )
    return result.scalar()


def evaluate_naive_no(user_id, session: Session) -> list[Signal]:
    """Naive control strategy: buy NO on any range contract priced <8¢.
    No model computation — tests whether alpha is structural."""
    config = session.execute(
        select(BotConfig).where(BotConfig.user_id == user_id)
    ).scalar_one_or_none()

    if not config or not config.enabled:
        return []

    if config.daily_loss_limit_cents > 0:
        if _today_pnl(session, user_id) <= -config.daily_loss_limit_cents:
            return []

    now_iso = datetime.now(timezone.utc).isoformat()
    opps = session.execute(
        select(Opportunity).where(
            Opportunity.strike_type == "between",
            (Opportunity.close_time.is_(None)) | (Opportunity.close_time > now_iso),
        )
    ).scalars().all()

    current_exposure = _open_exposure(session, user_id)
    daily_spent = _today_spend(session, user_id)
    signals_created = []

    for opp in opps:
        no_ask = opp.no_ask or opp.no_price
        if not no_ask or no_ask <= 0 or no_ask > 8:
            continue

        if _has_open_signal(session, user_id, opp.ticker):
            continue
        if _recently_lost(session, user_id, opp.ticker):
            continue

        limit_price = int(no_ask)
        if limit_price < 1:
            limit_price = 1

        quantity = min(config.max_contracts_per_signal, config.max_position_cents // limit_price if limit_price > 0 else 0)
        if quantity < 1:
            continue

        # Per-asset position limit (same guard as model strategy)
        if config.max_positions_per_asset > 0:
            asset_prefix = _detect_asset_prefix(opp.ticker)
            if _asset_position_count(session, user_id, asset_prefix) >= config.max_positions_per_asset:
                continue

        cost = limit_price * quantity

        if current_exposure + cost > config.max_exposure_cents:
            continue
        if config.daily_budget_cents > 0 and daily_spent + cost > config.daily_budget_cents:
            continue

        signal = Signal(
            user_id=user_id,
            opportunity_id=opp.id,
            ticker=opp.ticker,
            side="no",
            action="buy",
            limit_price_cents=limit_price,
            quantity=quantity,
            cost_cents=cost,
            signal_type=config.mode,
            status="signaled",
            model_prob=opp.model_prob,
            model_fair_cents=opp.model_fair_cents,
            model_edge_cents=opp.model_edge_cents,
            edge_tier="naive",
            implied_vol=opp.implied_vol,
            market_yes_price_cents=opp.yes_price,
            spot_price=opp.spot_price,
            strike_price=opp.strike_price,
            cap_strike=opp.cap_strike,
            close_time=opp.close_time,
        )

        session.add(signal)
        current_exposure += cost
        daily_spent += cost
        signals_created.append(signal)
        logger.info("Naive NO signal: %s @ %d¢ x%d", opp.ticker, limit_price, quantity)

    session.commit()
    return signals_created


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

        # Estimate entry price for fee calculation
        if edge > 0:
            est_price = int(opp.yes_ask or opp.yes_price or opp.model_fair_cents or 50)
        else:
            est_price = int(opp.no_ask or opp.no_price or (100 - (opp.model_fair_cents or 50)))
        est_price = max(1, min(99, est_price))

        # Subtract expected fee from edge before comparing to threshold
        if opp.model_prob is not None:
            win_prob = opp.model_prob if edge > 0 else (1 - opp.model_prob)
            fee_if_win = max(KALSHI_MIN_FEE_CENTS, int((100 - est_price) * KALSHI_FEE_RATE))
            expected_fee = win_prob * fee_if_win
            abs_edge -= expected_fee

        if abs_edge < config.min_edge_cents:
            continue
        if opp.liquidity < config.min_liquidity:
            continue
        if config.mode == "live":
            ask = opp.yes_ask if edge > 0 else opp.no_ask
            if ask is None or ask <= 0:
                continue
        if _has_open_signal(session, user_id, opp.ticker):
            continue
        if _recently_lost(session, user_id, opp.ticker):
            continue

        if config.max_positions_per_asset > 0:
            asset_prefix = _detect_asset_prefix(opp.ticker)
            if _asset_position_count(session, user_id, asset_prefix) >= config.max_positions_per_asset:
                continue

        side = "yes" if edge > 0 else "no"

        min_yes_threshold = (config.min_yes_prob or 20) / 100.0
        if side == "yes" and opp.model_prob is not None and opp.model_prob < min_yes_threshold:
            continue

        if side == "yes":
            limit_price = int(opp.yes_ask or opp.yes_price or opp.model_fair_cents or 50)
        else:
            limit_price = int(opp.no_ask or opp.no_price or (100 - (opp.model_fair_cents or 50)))

        limit_price = max(1, min(99, limit_price))

        # Skip mid-range entries on range contracts — 0% win rate in backtesting
        if opp.strike_type == "between" and 10 <= limit_price <= 30:
            continue

        tier = classify_edge_tier(abs_edge)
        if abs_edge >= EDGE_SANITY_CAP_CENTS and tier in ("elite", "high"):
            logger.info(
                "Edge sanity cap: %s edge %.1f¢ exceeds %d¢, capping at moderate sizing",
                opp.ticker, abs_edge, EDGE_SANITY_CAP_CENTS,
            )
            tier = "moderate"
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

        if not current_ask or current_ask <= 0:
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

        # Settlement arb signals ride to expiry — no take-profit, no stop-loss.
        # Temporary bid dips don't change the settlement outcome.
        if sig.edge_tier == "settlement_arb":
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

        # Always track peak unrealized for trailing stop
        prev_peak = sig.max_unrealized_cents or 0
        if unrealized_per_contract > prev_peak:
            sig.max_unrealized_cents = unrealized_per_contract

        peak = sig.max_unrealized_cents or 0
        trail_distance = max(3, cfg.take_profit_cents // 2)
        trailing_active = peak >= cfg.take_profit_cents

        # Trailing stop: once TP threshold is reached, hold until price pulls back
        # by the trail distance from the peak. The floor guard (below) provides a
        # secondary exit at half the TP threshold to prevent giving back all profit
        # on positions that peaked briefly and then reversed hard.
        floor_guard_cents = max(3, cfg.take_profit_cents // 2)
        if trailing_active and (unrealized_per_contract <= peak - trail_distance or unrealized_per_contract < floor_guard_cents):
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
                "Trailing stop: %s %s exit @ %d¢ (entry %d¢, peak %d¢, net +%d¢)",
                sig.ticker, sig.side, exit_price, sig.fill_price_cents, peak, sig.pnl_cents,
            )
            continue

        # Expiry proximity exit: close profitable positions near expiry to avoid the binary coin flip
        if cfg.expiry_exit_minutes > 0 and sig.close_time and unrealized_per_contract > 0:
            try:
                expiry_dt = datetime.fromisoformat(sig.close_time.replace("Z", "+00:00"))
                minutes_left = (expiry_dt - now).total_seconds() / 60
                if 0 < minutes_left <= cfg.expiry_exit_minutes:
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
                        "Expiry exit: %s %s exit @ %d¢ (entry %d¢, %.0f min left, net +%d¢)",
                        sig.ticker, sig.side, exit_price, sig.fill_price_cents, minutes_left, sig.pnl_cents,
                    )
                    continue
            except (ValueError, TypeError):
                pass

        # Stop-loss check — skip for cheap entries (binary lottery bets should ride to expiry)
        if cfg.stop_loss_cents > 0 and sig.fill_price_cents >= 15 and unrealized_per_contract <= -cfg.stop_loss_cents:
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


def settle_signals(session: Session, kalshi_clients: dict | None = None) -> int:
    """Settle expired signals. Checks Kalshi's published market result first;
    falls back to spot-vs-strike computation if Kalshi hasn't published yet."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    open_signals = session.execute(
        select(Signal).where(
            Signal.status.in_(OPEN_STATUSES),
            Signal.close_time.isnot(None),
            Signal.close_time < now_iso,
        )
    ).scalars().all()

    # Group signals by user for Kalshi lookups
    user_ids = {s.user_id for s in open_signals}
    if kalshi_clients is None:
        kalshi_clients = {}

    settled = 0
    for sig in open_signals:
        kalshi = kalshi_clients.get(sig.user_id)

        # Try Kalshi's published result first (authoritative)
        kalshi_result = None
        if kalshi:
            try:
                market = asyncio.run(kalshi.get_market(sig.ticker))
                mkt = market.get("market", market)
                if mkt.get("status") in ("closed", "settled", "finalized"):
                    kalshi_result = mkt.get("result")
            except Exception:
                pass

        if kalshi_result:
            won_side = kalshi_result
            logger.info("Kalshi result for %s: %s", sig.ticker, won_side)
        else:
            # Fallback: compute from spot vs strike
            opp = session.execute(
                select(Opportunity).where(Opportunity.ticker == sig.ticker)
            ).scalar_one_or_none()
            current_spot = opp.spot_price if opp else sig.spot_price
            strike = sig.strike_price
            cap = sig.cap_strike
            s_type = opp.strike_type if opp else ("between" if sig.cap_strike else None)

            if current_spot is not None and strike is not None:
                if s_type == "between" and cap is not None:
                    won_side = "yes" if float(strike) < float(current_spot) < float(cap) else "no"
                elif s_type == "below":
                    won_side = "yes" if float(current_spot) < float(strike) else "no"
                else:
                    won_side = "yes" if float(current_spot) > float(strike) else "no"
            else:
                continue

            sig.spot_price = current_spot
            logger.info("Spot settlement for %s: spot=%s strike=%s cap=%s → %s",
                        sig.ticker, current_spot, strike, cap, won_side)

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


def _sigma_distance(
    spot: float,
    strike: float,
    cap_strike: float | None,
    strike_type: str | None,
    realized_vol: float,
    minutes_left: float,
) -> float:
    """How many standard deviations is spot from the nearest outcome-flipping boundary?

    For a "between" (range) contract: YES wins if low < S_T < high.
    Distance is measured from spot to the nearest boundary, as a fraction of spot,
    divided by the realized vol scaled to the remaining time.

    For "above" contracts: YES wins if S_T > strike.
    Distance is (spot - strike) / spot, positive when in-the-money.

    For "below" contracts: YES wins if S_T < strike.
    Distance is (strike - spot) / spot, positive when in-the-money.

    Returns sigma distance. Values < 0 mean the contract is out of the money.
    """
    if not spot or spot <= 0 or not realized_vol or realized_vol <= 0 or minutes_left <= 0:
        return 0.0

    # Expected fractional move over remaining time: vol * sqrt(T)
    vol_scaled = realized_vol * math.sqrt(minutes_left / MINUTES_PER_YEAR)
    if vol_scaled <= 0:
        return float("inf")

    if strike_type == "between" and cap_strike is not None:
        dist_low = (spot - strike) / spot
        dist_high = (cap_strike - spot) / spot
        min_dist = min(dist_low, dist_high)
        return min_dist / vol_scaled
    elif strike_type == "above":
        dist = (spot - strike) / spot
        return dist / vol_scaled
    elif strike_type == "below":
        dist = (strike - spot) / spot
        return dist / vol_scaled

    return 0.0


def _net_win_cents(entry_cents: int) -> int:
    """Net payout in cents after Kalshi fees for a winning $1 contract.

    Kalshi charges 7% of profit, minimum 2c per contract.
    For a contract bought at P cents that settles at $1.00 (100c):
      profit = 100 - P
      fee = max(2, floor(0.07 * profit))
      net = 100 - fee
    """
    profit = 100 - entry_cents
    fee = max(KALSHI_MIN_FEE_CENTS, int(profit * KALSHI_FEE_RATE))
    return 100 - fee


def evaluate_settlement_arb(
    user_id,
    session: Session,
    kalshi: KalshiClient | None = None,
) -> list[Signal]:
    """Late-stage settlement arbitrage strategy.

    Identifies Kalshi contracts expiring soon where spot is far enough from the
    strike boundaries that the outcome is effectively certain (>1.5 sigma away).
    Buys the near-certain side when it trades at a discount to fair probability
    value. No probability model needed -- pure mechanical edge from market makers
    pricing tail risk that can't materialize in the remaining time.

    Key config fields (on BotConfig):
      settlement_arb_max_minutes   -- only consider contracts within this window
      settlement_arb_min_sigma     -- minimum sigma distance from boundary
      settlement_arb_min_discount_cents -- minimum discount from fair value to enter
      settlement_arb_max_position_cents -- max position size per signal
    """
    config = session.execute(
        select(BotConfig).where(BotConfig.user_id == user_id)
    ).scalar_one_or_none()

    if not config or not config.enabled or not config.settlement_arb_enabled:
        return []

    # Daily loss circuit breaker (shared with model strategy)
    if config.daily_loss_limit_cents > 0:
        today_pnl = _today_pnl(session, user_id)
        if today_pnl <= -config.daily_loss_limit_cents:
            logger.warning(
                "Settlement arb: daily loss circuit breaker triggered (%dc <= -%dc)",
                today_pnl, config.daily_loss_limit_cents,
            )
            return []

    # Max signals per hour pacing (shared)
    if config.max_signals_per_hour > 0:
        recent_signals = _signals_last_hour(session, user_id)
        if recent_signals >= config.max_signals_per_hour:
            logger.info(
                "Settlement arb: pacing limit (%d signals in last hour)",
                recent_signals,
            )
            return []

    now = datetime.now(timezone.utc)
    max_minutes = config.settlement_arb_max_minutes
    cutoff = now + timedelta(minutes=max_minutes)
    now_iso = now.isoformat()
    cutoff_iso = cutoff.isoformat()

    # Fetch opportunities expiring within our window
    opps = session.execute(
        select(Opportunity).where(
            Opportunity.close_time.isnot(None),
            Opportunity.close_time > now_iso,
            Opportunity.close_time <= cutoff_iso,
            Opportunity.spot_price.isnot(None),
            Opportunity.strike_price.isnot(None),
        )
    ).scalars().all()

    if not opps:
        return []

    # Fetch realized vol once per asset to avoid redundant API calls.
    # Use 1-hour realized vol at 1-minute granularity for near-expiry contracts.
    realized_vols: dict[str, float] = {}
    assets_needed = {opp.asset for opp in opps if opp.asset}
    for asset in assets_needed:
        try:
            rv = asyncio.run(get_realized_vol(asset, hours=1, interval="1m"))
        except Exception:
            logger.warning("Failed to fetch realized vol for %s, using default", asset)
            rv = None
        if rv is None or rv <= 0:
            # Fallback: use a conservative default (65% annualized for crypto)
            rv = 0.65
        realized_vols[asset] = rv
        logger.info("Settlement arb: %s realized vol = %.1f%%", asset, rv * 100)

    current_exposure = _open_exposure(session, user_id)
    daily_spent = _today_spend(session, user_id)
    signals_created: list[Signal] = []

    for opp in opps:
        asset = opp.asset or "BTC"
        realized_vol = realized_vols.get(asset, 0.65)

        expiry_dt = datetime.fromisoformat(opp.close_time.replace("Z", "+00:00"))
        minutes_left = (expiry_dt - now).total_seconds() / 60
        if minutes_left <= 0:
            continue

        # Compute sigma distance from nearest boundary
        sigma = _sigma_distance(
            opp.spot_price,
            opp.strike_price,
            opp.cap_strike,
            opp.strike_type,
            realized_vol,
            minutes_left,
        )

        if sigma < config.settlement_arb_min_sigma:
            continue

        # Determine the near-certain side
        if opp.strike_type == "between":
            # Spot inside the range -> YES wins
            if opp.spot_price and opp.strike_price and opp.cap_strike:
                if not (opp.strike_price < opp.spot_price < opp.cap_strike):
                    # Spot outside range -> NO wins
                    side = "no"
                else:
                    side = "yes"
            else:
                continue
        elif opp.strike_type == "above":
            side = "yes" if (opp.spot_price or 0) > (opp.strike_price or 0) else "no"
        elif opp.strike_type == "below":
            side = "yes" if (opp.spot_price or 0) < (opp.strike_price or 0) else "no"
        else:
            continue

        # Probability of winning under log-normal assumption
        win_prob = float(norm.cdf(sigma))

        # Fair value in cents
        fair_cents = win_prob * 100

        # Market price (what we'd pay)
        if side == "yes":
            market_cents = opp.yes_ask or opp.yes_price
        else:
            market_cents = opp.no_ask or opp.no_price

        if not market_cents or market_cents <= 0 or market_cents >= 100:
            continue

        discount = fair_cents - market_cents
        if discount < config.settlement_arb_min_discount_cents:
            continue

        # Expected value per contract (in cents)
        net_if_win = _net_win_cents(int(market_cents))
        ev_per_contract = win_prob * net_if_win - market_cents
        if ev_per_contract <= 0:
            continue

        # Skip if we already have an open position on this ticker
        if _has_open_signal(session, user_id, opp.ticker):
            continue
        if _recently_lost(session, user_id, opp.ticker):
            continue

        # Per-asset position limit
        if config.max_positions_per_asset > 0:
            asset_prefix = _detect_asset_prefix(opp.ticker)
            if _asset_position_count(session, user_id, asset_prefix) >= config.max_positions_per_asset:
                continue

        # Position sizing: use a fixed fraction of max position, capped by exposure
        limit_price = int(market_cents)
        limit_price = max(1, min(99, limit_price))

        max_qty = config.settlement_arb_max_position_cents // limit_price if limit_price > 0 else 0
        if max_qty < 1:
            continue

        # Kelly-inspired sizing: bet proportional to edge, capped at max_qty
        edge_pct = discount / 100.0
        kelly_fraction = max(0.05, min(0.25, edge_pct * 2))
        quantity = max(1, int(max_qty * kelly_fraction))

        cost = limit_price * quantity
        if current_exposure + cost > config.max_exposure_cents:
            continue
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
            model_prob=win_prob,
            model_fair_cents=fair_cents,
            model_edge_cents=discount,
            edge_tier="settlement_arb",
            market_yes_price_cents=opp.yes_price,
            spot_price=opp.spot_price,
            strike_price=opp.strike_price,
            cap_strike=opp.cap_strike,
            close_time=opp.close_time,
        )

        if config.mode == "live" and kalshi:
            try:
                result = asyncio.run(
                    kalshi.place_order(opp.ticker, side, "buy", limit_price, quantity)
                )
                signal.kalshi_order_id = result.get("order", {}).get("order_id")
                signal.status = "placed"
                logger.info(
                    "Settlement arb LIVE: %s %s @ %dc x%d (sigma=%.1f, ev=%.1fc, %dmin left)",
                    opp.ticker, side, limit_price, quantity, sigma, ev_per_contract, int(minutes_left),
                )
            except Exception as e:
                signal.status = "cancelled"
                signal.error_message = str(e)
                logger.exception("Failed to place settlement arb order for %s", opp.ticker)
        else:
            logger.info(
                "Settlement arb PAPER: %s %s @ %dc x%d (sigma=%.1f, ev=%.1fc, %dmin left, fair=%.0fc)",
                opp.ticker, side, limit_price, quantity, sigma, ev_per_contract, int(minutes_left), fair_cents,
            )

        session.add(signal)
        current_exposure += cost
        daily_spent += cost
        signals_created.append(signal)

    session.commit()
    return signals_created
