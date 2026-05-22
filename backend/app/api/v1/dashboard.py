from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.bot_config import BotConfig
from app.models.opportunity import Opportunity
from app.models.signal import Signal
from app.models.user import User
from app.schemas.dashboard import (
    BotStatusResponse,
    DailyPnLPoint,
    DashboardResponse,
    OpportunitySummary,
    PaperPnLStats,
    PnLChartResponse,
)
from app.schemas.signal import SignalResponse
from app.services.signal_engine import _net_win_cents, _sigma_distance

router = APIRouter(tags=["dashboard"])


def _unrealized_pnl(sig, opp_map: dict) -> int | None:
    if sig.status != "filled" or sig.fill_price_cents is None:
        return None
    opp = opp_map.get(sig.ticker)
    if not opp:
        return None
    bid = opp.yes_price if sig.side == "yes" else opp.no_price
    if bid is None:
        return None
    return (int(bid) - sig.fill_price_cents) * (sig.fill_quantity or sig.quantity)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (await db.execute(
        select(BotConfig).where(BotConfig.user_id == user.id)
    )).scalar_one_or_none()

    if not config:
        config = BotConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    today = datetime.now(timezone.utc).astimezone().date()
    daily_spent = (await db.execute(
        select(func.coalesce(func.sum(Signal.cost_cents), 0))
        .where(
            Signal.user_id == user.id,
            func.date(Signal.created_at) == today,
            Signal.status.notin_(["cancelled"]),
        )
    )).scalar()

    signals_today = (await db.execute(
        select(func.count())
        .select_from(Signal)
        .where(Signal.user_id == user.id, func.date(Signal.created_at) == today)
    )).scalar()

    active_signals = (await db.execute(
        select(func.count())
        .select_from(Signal)
        .where(Signal.user_id == user.id, Signal.status.in_(["signaled", "placed", "filled"]))
    )).scalar()

    current_exposure = (await db.execute(
        select(func.coalesce(func.sum(Signal.cost_cents), 0))
        .where(Signal.user_id == user.id, Signal.status.in_(["signaled", "placed", "filled"]))
    )).scalar()

    # Check key validity (non-blocking — don't fail dashboard if Kalshi is slow)
    keys_valid = False
    if user.kalshi_api_key_id:
        try:
            from app.services.kalshi_client import KalshiClient
            kalshi = KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)
            keys_valid = await kalshi.validate()
        except Exception:
            pass

    bot_status = BotStatusResponse(
        mode=config.mode,
        strategy=config.strategy,
        enabled=config.enabled,
        has_kalshi_keys=bool(user.kalshi_api_key_id),
        kalshi_keys_valid=keys_valid,
        max_exposure_cents=config.max_exposure_cents,
        current_exposure_cents=current_exposure,
        exposure_remaining_cents=max(0, config.max_exposure_cents - current_exposure),
        daily_budget_cents=config.daily_budget_cents,
        daily_spent_cents=daily_spent,
        signals_today=signals_today,
        active_signals=active_signals,
        settlement_arb_enabled=config.settlement_arb_enabled,
        settlement_arb_max_minutes=config.settlement_arb_max_minutes,
        settlement_arb_min_sigma=config.settlement_arb_min_sigma,
    )

    recent = (await db.execute(
        select(Signal)
        .where(Signal.user_id == user.id)
        .order_by(Signal.created_at.desc())
        .limit(50)
    )).scalars().all()

    filled_tickers = {s.ticker for s in recent if s.status == "filled" and s.fill_price_cents is not None}
    opp_map: dict = {}
    if filled_tickers:
        opps_for_pnl = (await db.execute(
            select(Opportunity).where(Opportunity.ticker.in_(filled_tickers))
        )).scalars().all()
        opp_map = {o.ticker: o for o in opps_for_pnl}

    recent_signals = [
        SignalResponse(
            id=s.id, ticker=s.ticker, side=s.side, action=s.action,
            limit_price_cents=s.limit_price_cents, quantity=s.quantity,
            cost_cents=s.cost_cents, signal_type=s.signal_type, status=s.status,
            model_prob=s.model_prob, model_fair_cents=s.model_fair_cents,
            model_edge_cents=s.model_edge_cents, edge_tier=s.edge_tier,
            implied_vol=s.implied_vol, market_yes_price_cents=s.market_yes_price_cents,
            spot_price=s.spot_price, strike_price=s.strike_price,
            cap_strike=s.cap_strike,
            kalshi_order_id=s.kalshi_order_id, fill_price_cents=s.fill_price_cents,
            exit_price_cents=s.exit_price_cents, filled_at=s.filled_at,
            unrealized_pnl_cents=_unrealized_pnl(s, opp_map),
            pnl_cents=s.pnl_cents, settled_side=s.settled_side,
            close_time=s.close_time, created_at=s.created_at,
            resolved_at=s.resolved_at,
        )
        for s in recent
    ]

    total_signals = (await db.execute(
        select(func.count()).select_from(Signal).where(Signal.user_id == user.id)
    )).scalar()
    wins = (await db.execute(
        select(func.count()).select_from(Signal)
        .where(Signal.user_id == user.id, Signal.status == "settled_win")
    )).scalar()
    losses = (await db.execute(
        select(func.count()).select_from(Signal)
        .where(Signal.user_id == user.id, Signal.status == "settled_loss")
    )).scalar()
    settled_count = wins + losses
    total_pnl = (await db.execute(
        select(func.coalesce(func.sum(Signal.pnl_cents), 0))
        .where(Signal.user_id == user.id, Signal.pnl_cents.isnot(None))
    )).scalar()
    total_cost = (await db.execute(
        select(func.coalesce(func.sum(Signal.cost_cents), 0))
        .where(Signal.user_id == user.id, Signal.status.in_(["settled_win", "settled_loss"]))
    )).scalar()

    open_positions = (await db.execute(
        select(func.count()).select_from(Signal)
        .where(Signal.user_id == user.id, Signal.status == "filled")
    )).scalar()
    total_unrealized = sum(
        _unrealized_pnl(s, opp_map) or 0
        for s in recent if s.status == "filled"
    )

    stats = PaperPnLStats(
        total_signals=total_signals,
        settled_count=settled_count,
        wins=wins,
        losses=losses,
        win_rate=round(wins / settled_count * 100, 1) if settled_count > 0 else 0,
        total_pnl_cents=total_pnl,
        total_cost_cents=total_cost,
        roi_pct=round(total_pnl / total_cost * 100, 1) if total_cost > 0 else 0,
        unrealized_pnl_cents=total_unrealized,
        open_positions=open_positions,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    opps = (await db.execute(
        select(Opportunity)
        .where(
            (Opportunity.close_time.is_(None)) | (Opportunity.close_time > now_iso)
        )
        .order_by(Opportunity.source.desc(), Opportunity.close_time.asc().nullslast())
        .limit(50)
    )).scalars().all()

    opportunities = []
    now = datetime.now(timezone.utc)
    arb_sigma = config.settlement_arb_min_sigma
    arb_discount = config.settlement_arb_min_discount_cents
    # Default realized vol for UI display (bot uses real Binance data)
    DEFAULT_RV = 0.65

    for o in opps:
        sigma = None
        discount = None
        would = False

        if o.close_time and o.spot_price and o.strike_price:
            try:
                expiry_dt = datetime.fromisoformat(o.close_time.replace("Z", "+00:00"))
                minutes_left = (expiry_dt - now).total_seconds() / 60
                if minutes_left > 0:
                    sigma = _sigma_distance(
                        o.spot_price, o.strike_price, o.cap_strike,
                        o.strike_type, DEFAULT_RV, minutes_left,
                    )
                    abs_sigma = abs(sigma) if sigma else 0
                    if abs_sigma >= arb_sigma:
                        # Determine near-certain side and discount
                        win_prob = float(__import__('scipy').stats.norm.cdf(abs_sigma))
                        fair_cents = win_prob * 100
                        inside = None
                        if o.strike_type == "between" and o.cap_strike:
                            inside = o.strike_price < o.spot_price < o.cap_strike
                        elif o.strike_type == "above":
                            inside = o.spot_price > o.strike_price
                        elif o.strike_type == "below":
                            inside = o.spot_price < o.strike_price
                        if inside is not None:
                            if inside:
                                market_cents = o.yes_ask or o.yes_price
                                target_fair = win_prob * 100
                            else:
                                market_cents = o.no_ask or o.no_price
                                target_fair = (1 - win_prob) * 100
                            if market_cents and market_cents > 0:
                                discount = target_fair - market_cents
                                ev = win_prob * _net_win_cents(int(market_cents)) - market_cents
                                would = discount >= arb_discount and ev > 0
            except Exception:
                pass

        edge_cents = o.model_edge_cents if o.source == "kalshi" else (o.edge or 0)

        opportunities.append(OpportunitySummary(
            source=o.source, ticker=o.ticker, asset=o.asset, title=o.title,
            subtitle=o.subtitle,
            strike_price=o.strike_price, cap_strike=o.cap_strike,
            strike_type=o.strike_type,
            spot_price=o.spot_price,
            yes_price=o.yes_price, no_price=o.no_price,
            yes_ask=o.yes_ask, no_ask=o.no_ask,
            model_prob=o.model_prob,
            model_fair_cents=o.model_fair_cents,
            model_edge_cents=edge_cents,
            edge_direction=o.edge_direction,
            liquidity=o.liquidity, close_time=o.close_time,
            sigma_distance=round(abs(sigma), 2) if sigma is not None else None,
            discount_cents=round(discount, 1) if discount else None,
            would_signal=would,
        ))

    # Read scanner health from file (written by the scheduler's scan loop)
    scanner_health = None
    try:
        import json as _json
        from pathlib import Path
        raw = Path("/tmp/scanner_health.json").read_text()
        scanner_health = _json.loads(raw)
    except Exception:
        pass

    return DashboardResponse(
        bot_status=bot_status,
        recent_signals=recent_signals,
        opportunities=opportunities,
        stats=stats,
        scanner_health=scanner_health,
    )


@router.get("/dashboard/pnl-chart", response_model=PnLChartResponse)
async def get_pnl_chart(
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    day_col = func.date(func.timezone('America/New_York', Signal.resolved_at)).label("day")
    stmt = (
        select(
            day_col,
            func.sum(Signal.pnl_cents).label("daily_pnl"),
            func.count().label("cnt"),
            func.sum(case((Signal.status == "settled_win", 1), else_=0)).label("wins"),
            func.sum(case((Signal.status == "settled_loss", 1), else_=0)).label("losses"),
        )
        .where(
            Signal.user_id == user.id,
            Signal.pnl_cents.isnot(None),
            Signal.resolved_at >= since,
        )
        .group_by(day_col)
        .order_by(day_col)
    )

    rows = (await db.execute(stmt)).all()

    daily = []
    cumulative = 0
    for row in rows:
        cumulative += row.daily_pnl
        daily.append(DailyPnLPoint(
            date=str(row.day),
            pnl_cents=row.daily_pnl,
            cumulative_pnl_cents=cumulative,
            signals_count=row.cnt,
            wins=row.wins,
            losses=row.losses,
        ))

    pnls = [d.pnl_cents for d in daily] or [0]
    return PnLChartResponse(
        daily=daily,
        total_pnl_cents=cumulative,
        best_day_cents=max(pnls),
        worst_day_cents=min(pnls),
        winning_days=sum(1 for d in daily if d.pnl_cents > 0),
        losing_days=sum(1 for d in daily if d.pnl_cents < 0),
    )
