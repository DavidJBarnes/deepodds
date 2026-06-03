from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.signal import Signal
from app.models.user import User
from app.schemas.dashboard import (
    ClimateStatusResponse,
    DailyPnLPoint,
    DashboardResponse,
    KalshiFilteredMarket,
    KalshiMarketSnapshot,
    KalshiStatusResponse,
    PnLChartResponse,
    PnLStats,
)
from app.models.market_snapshot import MarketSnapshot
from app.models.scanner_heartbeat import ScannerHeartbeat
from app.schemas.signal import SignalResponse
from app.services.binance_client import get_crypto_prices, get_realized_vol
from app.services.climate_probability_model import compute_climate_edge
from app.services.kalshi_client import KalshiClient
from app.services.probability_model import compute_edge, series_to_underlying
from app.services.weather_client import (
    get_daily_extreme_vol,
    get_forecast_daily_value,
    parse_event_date,
    series_to_city_kind,
)

router = APIRouter(tags=["dashboard"])

OPEN_STATUSES = ("signaled", "placed", "filled")


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    venue: str = Query("all", pattern="^(all|kalshi_crypto|kalshi_climate)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    venue_filter = []
    if venue == "kalshi_crypto":
        venue_filter = [Signal.venue == "kalshi_crypto"]
    elif venue == "kalshi_climate":
        venue_filter = [Signal.venue == "kalshi_climate"]

    recent_q = select(Signal).where(Signal.user_id == user.id, *venue_filter).order_by(Signal.created_at.desc()).limit(50)
    recent = (await db.execute(recent_q)).scalars().all()

    recent_signals = []
    for s in recent:
        fill_p = s.fill_price or s.entry_price
        qty = s.fill_quantity or s.quantity or 0
        live_prob = getattr(s, "live_market_prob", None)
        unrealized = None
        if s.status == "filled" and live_prob is not None and fill_p > 0 and qty > 0:
            unrealized = round((live_prob - fill_p) * qty, 4)

        recent_signals.append(
            SignalResponse(
                id=s.id,
                venue=s.venue or "kalshi_crypto",
                pair=s.pair,
                side=s.side,
                signal_type=s.signal_type,
                status=s.status,
                entry_price=s.entry_price,
                quantity=s.quantity,
                cost_usd=s.cost_usd,
                model_prob=s.model_prob,
                market_prob=s.market_prob,
                live_market_prob=live_prob,
                edge=s.edge,
                floor_strike=s.floor_strike,
                cap_strike=s.cap_strike,
                strike_type=s.strike_type,
                underlying_price=s.underlying_price,
                realized_vol=s.realized_vol,
                exchange_order_id=s.exchange_order_id,
                fill_price=s.fill_price,
                fill_quantity=s.fill_quantity,
                filled_at=s.filled_at,
                exit_price=s.exit_price,
                pnl_usd=s.pnl_usd,
                pnl_pct=s.pnl_pct,
                unrealized_pnl_usd=unrealized,
                market_ticker=s.market_ticker,
                event_ticker=s.event_ticker,
                expiry_time=s.expiry_time,
                created_at=s.created_at,
                resolved_at=s.resolved_at,
            )
        )

    # Stats (venue-filtered)
    total_signals = (
        await db.execute(
            select(func.count()).select_from(Signal).where(Signal.user_id == user.id, *venue_filter)
        )
    ).scalar()
    wins = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "settled_win", *venue_filter)
        )
    ).scalar()
    losses = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "settled_loss", *venue_filter)
        )
    ).scalar()
    breakevens = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "settled_breakeven", *venue_filter)
        )
    ).scalar()
    settled_count = wins + losses + breakevens
    total_pnl = (
        await db.execute(
            select(func.coalesce(func.sum(Signal.pnl_usd), 0.0)).where(
                Signal.user_id == user.id, Signal.pnl_usd.isnot(None), *venue_filter
            )
        )
    ).scalar()
    total_cost = (
        await db.execute(
            select(func.coalesce(func.sum(Signal.cost_usd), 0.0)).where(
                Signal.user_id == user.id,
                Signal.status.in_(["settled_win", "settled_loss", "settled_breakeven"]),
                *venue_filter,
            )
        )
    ).scalar()

    open_positions_count = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "filled", *venue_filter)
        )
    ).scalar()

    filled_signals = (
        await db.execute(
            select(Signal)
            .where(
                Signal.user_id == user.id,
                Signal.status == "filled",
                Signal.live_market_prob.isnot(None),
                Signal.fill_price.isnot(None),
                *venue_filter,
            )
        )
    ).scalars().all()
    total_unrealized = 0.0
    for fs in filled_signals:
        qty = fs.fill_quantity or fs.quantity or 0
        lp = fs.live_market_prob or 0
        fp = fs.fill_price or 0
        total_unrealized += (lp - fp) * qty

    stats = PnLStats(
        total_signals=total_signals,
        settled_count=settled_count,
        wins=wins,
        losses=losses,
        win_rate=round(wins / settled_count * 100, 1) if settled_count > 0 else 0,
        total_pnl_usd=round(float(total_pnl), 2),
        total_cost_usd=round(float(total_cost), 2),
        roi_pct=round(float(total_pnl) / float(total_cost) * 100, 1)
        if total_cost > 0
        else 0,
        unrealized_pnl_usd=round(total_unrealized, 2),
        open_positions=open_positions_count,
    )

    scanner_health = None
    try:
        hb = (await db.execute(
            select(ScannerHeartbeat).where(ScannerHeartbeat.id == 1)
        )).scalar_one_or_none()
        if hb:
            scanner_health = {
                "last_scan": hb.last_beat.isoformat(),
                "status": hb.status,
            }
            if hb.error:
                scanner_health["error"] = hb.error
    except Exception:
        pass

    kalshi_cfg = (
        await db.execute(select(CryptoConfig).where(CryptoConfig.user_id == user.id))
    ).scalar_one_or_none()

    kalshi_status = None
    kalshi_markets_list: list[KalshiMarketSnapshot] = []
    kalshi_filtered_list: list[KalshiFilteredMarket] = []
    if kalshi_cfg:
        kalshi_open_stats = (
            await db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(Signal.cost_usd), 0.0),
                    func.coalesce(func.sum(Signal.quantity), 0.0),
                )
                .select_from(Signal)
                .where(
                    Signal.user_id == user.id,
                    Signal.venue == "kalshi_crypto",
                    Signal.signal_type == kalshi_cfg.mode,
                    Signal.status.in_(OPEN_STATUSES)
                )
            )
        ).one()
        kalshi_open, kalshi_exposure, kalshi_payout = kalshi_open_stats
        kalshi_status = KalshiStatusResponse(
            mode=kalshi_cfg.mode,
            enabled=kalshi_cfg.enabled,
            has_keys=bool(user.kalshi_api_key_id),
            series_tickers=kalshi_cfg.series_tickers,
            open_positions=kalshi_open,
            max_open_positions=kalshi_cfg.max_open_positions,
            min_edge=kalshi_cfg.min_edge,
            exit_edge=kalshi_cfg.exit_edge,
            current_exposure_usd=round(float(kalshi_exposure), 2),
            max_payout_usd=round(float(kalshi_payout), 2),
        )

        try:
            snapshots = (
                await db.execute(
                    select(MarketSnapshot).where(
                        MarketSnapshot.venue == "kalshi_crypto",
                        MarketSnapshot.edge.is_not(None),
                    ).order_by(MarketSnapshot.edge.desc()).limit(200)
                )
            ).scalars().all()

            for s in snapshots:
                kalshi_markets_list.append(KalshiMarketSnapshot(
                    ticker=s.ticker,
                    series=s.series,
                    title=s.title or "",
                    price=round(s.ask_price, 2),
                    model_prob=round(s.model_prob, 4) if s.model_prob else 0.0,
                    edge=round(s.edge, 4) if s.edge else 0.0,
                    floor_strike=s.floor_strike,
                    cap_strike=s.cap_strike,
                    strike_type=s.strike_type or "between",
                    underlying_price=round(s.underlying_price, 2) if s.underlying_price else 0.0,
                    realized_vol=round(s.realized_vol, 4) if s.realized_vol else 0.0,
                    volume_24h=s.volume_24h or 0,
                    hours_to_expiry=round(s.hours_to_expiry, 1) if s.hours_to_expiry else 0,
                    expiry_time=s.expiry_time,
                    would_signal=(s.edge or 0) >= kalshi_cfg.min_edge and (s.edge or 0) > 0,
                ))

            for s in snapshots:
                if s.filter_reason:
                    kalshi_filtered_list.append(KalshiFilteredMarket(
                        ticker=s.ticker, series=s.series, title=s.title or "",
                        price=round(s.ask_price, 2), volume_24h=s.volume_24h or 0,
                        hours_to_expiry=round(s.hours_to_expiry, 1) if s.hours_to_expiry else 0,
                        filter_reason=s.filter_reason,
                    ))
        except Exception:
            pass

    # Climate status + market scanning
    from app.schemas.dashboard import ClimateStatusResponse

    climate_cfg = (
        await db.execute(select(ClimateConfig).where(ClimateConfig.user_id == user.id))
    ).scalar_one_or_none()

    climate_status = None
    climate_markets_list: list[KalshiMarketSnapshot] = []
    climate_filtered_list: list[KalshiFilteredMarket] = []

    if climate_cfg:
        climate_open_stats = (
            await db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(Signal.cost_usd), 0.0),
                    func.coalesce(func.sum(Signal.quantity), 0.0),
                )
                .select_from(Signal)
                .where(
                    Signal.user_id == user.id,
                    Signal.venue == "kalshi_climate",
                    Signal.signal_type == climate_cfg.mode,
                    Signal.status.in_(OPEN_STATUSES),
                )
            )
        ).one()
        climate_open, climate_exposure, climate_payout = climate_open_stats
        climate_status = ClimateStatusResponse(
            mode=climate_cfg.mode,
            enabled=climate_cfg.enabled,
            has_keys=bool(user.kalshi_api_key_id),
            series_tickers=climate_cfg.series_tickers,
            open_positions=climate_open,
            max_open_positions=climate_cfg.max_open_positions,
            min_edge=climate_cfg.min_edge,
            exit_edge=climate_cfg.exit_edge,
            current_exposure_usd=round(float(climate_exposure), 2),
            max_payout_usd=round(float(climate_payout), 2),
        )

        if venue in ("all", "kalshi_climate"):
            try:
                snapshots = (
                    await db.execute(
                        select(MarketSnapshot).where(
                            MarketSnapshot.venue == "kalshi_climate",
                            MarketSnapshot.edge.is_not(None),
                        ).order_by(MarketSnapshot.edge.desc()).limit(200)
                    )
                ).scalars().all()

                for s in snapshots:
                    climate_markets_list.append(KalshiMarketSnapshot(
                        ticker=s.ticker,
                        series=s.series,
                        title=s.title or "",
                        price=round(s.ask_price, 2),
                        model_prob=round(s.model_prob, 4) if s.model_prob else 0.0,
                        edge=round(s.edge, 4) if s.edge else 0.0,
                        floor_strike=s.floor_strike,
                        cap_strike=s.cap_strike,
                        strike_type=s.strike_type or "between",
                        underlying_price=round(s.underlying_price, 2) if s.underlying_price else 0.0,
                        realized_vol=round(s.realized_vol, 4) if s.realized_vol else 0.0,
                        volume_24h=s.volume_24h or 0,
                        hours_to_expiry=round(s.hours_to_expiry, 1) if s.hours_to_expiry else 0,
                        expiry_time=s.expiry_time,
                        would_signal=(s.edge or 0) >= climate_cfg.min_edge and (s.edge or 0) > 0,
                    ))

                for s in snapshots:
                    if s.filter_reason:
                        climate_filtered_list.append(KalshiFilteredMarket(
                            ticker=s.ticker, series=s.series, title=s.title or "",
                            price=round(s.ask_price, 2), volume_24h=s.volume_24h or 0,
                            hours_to_expiry=round(s.hours_to_expiry, 1) if s.hours_to_expiry else 0,
                            filter_reason=s.filter_reason,
                        ))
            except Exception:
                pass

    climate_scanner_health = None
    try:
        hb = (await db.execute(
            select(ScannerHeartbeat).where(ScannerHeartbeat.id == 1)
        )).scalar_one_or_none()
        if hb:
            climate_scanner_health = {
                "last_scan": hb.last_beat.isoformat(),
                "status": hb.status,
            }
            if hb.error:
                climate_scanner_health["error"] = hb.error
    except Exception:
        pass

    return DashboardResponse(
        kalshi_status=kalshi_status,
        climate_status=climate_status,
        recent_signals=recent_signals,
        kalshi_markets=kalshi_markets_list,
        kalshi_filtered=kalshi_filtered_list,
        climate_markets=climate_markets_list,
        climate_filtered=climate_filtered_list,
        stats=stats,
        scanner_health=scanner_health,
        climate_scanner_health=climate_scanner_health,
    )


@router.get("/dashboard/pnl-chart", response_model=PnLChartResponse)
async def get_pnl_chart(
    days: int = Query(30, ge=7, le=365),
    venue: str = Query("all", pattern="^(all|kalshi_crypto|kalshi_climate)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    pnl_venue_filter = []
    if venue == "kalshi_crypto":
        pnl_venue_filter = [Signal.venue == "kalshi_crypto"]
    elif venue == "kalshi_climate":
        pnl_venue_filter = [Signal.venue == "kalshi_climate"]

    day_col = func.date(
        func.timezone("America/New_York", Signal.resolved_at)
    ).label("day")
    stmt = (
        select(
            day_col,
            func.sum(Signal.pnl_usd).label("daily_pnl"),
            func.count().label("cnt"),
            func.sum(case((Signal.status == "settled_win", 1), else_=0)).label("wins"),
            func.sum(case((Signal.status == "settled_loss", 1), else_=0)).label(
                "losses"
            ),
        )
        .where(
            Signal.user_id == user.id,
            Signal.pnl_usd.isnot(None),
            Signal.resolved_at >= since,
            *pnl_venue_filter,
        )
        .group_by(day_col)
        .order_by(day_col)
    )

    rows = (await db.execute(stmt)).all()

    daily = []
    cumulative = 0.0
    for row in rows:
        cumulative += float(row.daily_pnl)
        daily.append(
            DailyPnLPoint(
                date=str(row.day),
                pnl_usd=round(float(row.daily_pnl), 2),
                cumulative_pnl_usd=round(cumulative, 2),
                signals_count=row.cnt,
                wins=row.wins,
                losses=row.losses,
            )
        )

    pnls = [d.pnl_usd for d in daily] or [0]
    return PnLChartResponse(
        daily=daily,
        total_pnl_usd=round(cumulative, 2),
        best_day_usd=max(pnls),
        worst_day_usd=min(pnls),
        winning_days=sum(1 for d in daily if d.pnl_usd > 0),
        losing_days=sum(1 for d in daily if d.pnl_usd < 0),
    )
