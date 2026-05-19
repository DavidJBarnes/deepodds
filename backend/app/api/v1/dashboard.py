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

    today = date.today()
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

    bot_status = BotStatusResponse(
        mode=config.mode,
        enabled=config.enabled,
        has_kalshi_keys=bool(user.kalshi_api_key_id),
        max_exposure_cents=config.max_exposure_cents,
        current_exposure_cents=current_exposure,
        exposure_remaining_cents=max(0, config.max_exposure_cents - current_exposure),
        daily_budget_cents=config.daily_budget_cents,
        daily_spent_cents=daily_spent,
        signals_today=signals_today,
        active_signals=active_signals,
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
        .order_by(Opportunity.model_edge_cents.desc().nullslast())
        .limit(20)
    )).scalars().all()

    opportunities = [
        OpportunitySummary(
            ticker=o.ticker, asset=o.asset, title=o.title,
            strike_price=o.strike_price, spot_price=o.spot_price,
            yes_price=o.yes_price, model_fair_cents=o.model_fair_cents,
            model_edge_cents=o.model_edge_cents, implied_vol=o.implied_vol,
            liquidity=o.liquidity, close_time=o.close_time, quality=o.quality,
        )
        for o in opps
    ]

    return DashboardResponse(
        bot_status=bot_status,
        recent_signals=recent_signals,
        opportunities=opportunities,
        stats=stats,
    )


@router.get("/dashboard/pnl-chart", response_model=PnLChartResponse)
async def get_pnl_chart(
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    day_col = func.date(Signal.resolved_at).label("day")
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
