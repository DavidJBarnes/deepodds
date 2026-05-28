from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.climate_config import ClimateConfig
from app.models.kalshi_config import KalshiConfig
from app.models.signal import Signal
from app.models.user import User
from app.schemas.dashboard import (
    DailyPnLPoint,
    DashboardResponse,
    KalshiFilteredMarket,
    KalshiMarketSnapshot,
    KalshiStatusResponse,
    PnLChartResponse,
    PnLStats,
)
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
    venue: str = Query("all", pattern="^(all|crypto|climate)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    venue_filter = []
    if venue == "crypto":
        venue_filter = [Signal.venue == "kalshi"]
    elif venue == "climate":
        venue_filter = [Signal.venue == "climate"]

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
                venue=s.venue or "kalshi",
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
        import json as _json
        from pathlib import Path

        raw = Path("/tmp/scanner_health.json").read_text()
        scanner_health = _json.loads(raw)
    except Exception:
        pass

    kalshi_cfg = (
        await db.execute(select(KalshiConfig).where(KalshiConfig.user_id == user.id))
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
                    Signal.venue == "kalshi",
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
            kc = KalshiClient.public()
            series_list = [s.strip() for s in kalshi_cfg.series_tickers.split(",") if s.strip()]
            now = datetime.now(timezone.utc)
            cutoff = now + timedelta(hours=kalshi_cfg.min_hours_to_expiry)
            hours_to_years = 1 / (365.25 * 24)

            underlying_data: dict[str, dict] = {}
            kalshi_symbols = [s for s in (series_to_underlying(x) for x in series_list) if s]
            spot_prices = await get_crypto_prices(kalshi_symbols) if kalshi_symbols else {}
            for series in series_list:
                symbol = series_to_underlying(series)
                if not symbol:
                    continue
                if symbol not in spot_prices:
                    continue
                try:
                    vol = await get_realized_vol(symbol, hours=24, interval="15m")
                    if vol and vol > 0:
                        underlying_data[series] = {"spot": spot_prices[symbol], "vol": vol}
                except Exception:
                    pass

            for series in series_list:
                try:
                    data = await kc.get_markets(series_ticker=series, limit=200)
                except Exception:
                    continue

                for m in data.get("markets", []):
                    vol_24h = float(m.get("volume_24h_fp", 0) or 0)
                    ask_price = float(m.get("yes_ask_dollars", 0) or 0)
                    ask_size = float(m.get("yes_ask_size_fp", 0) or 0)
                    ticker = m.get("ticker", "")
                    title = m.get("title", "")

                    close_time = m.get("close_time", "")
                    try:
                        ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                        hours_left = (ct - now).total_seconds() / 3600
                    except (ValueError, AttributeError):
                        ct = None
                        hours_left = None

                    filter_reason = None
                    if ask_price <= 0:
                        filter_reason = "no_ask"
                    elif ask_size < 1:
                        filter_reason = "no_ask_size"
                    elif vol_24h < kalshi_cfg.min_volume_24h:
                        filter_reason = "low_volume"
                    elif ask_price < kalshi_cfg.min_price or ask_price > kalshi_cfg.max_price:
                        filter_reason = "price_range"
                    elif ct is None:
                        filter_reason = "invalid_expiry"
                    elif ct < cutoff:
                        filter_reason = "expiry_too_soon"

                    if filter_reason:
                        kalshi_filtered_list.append(KalshiFilteredMarket(
                            ticker=ticker, series=series, title=title,
                            price=round(ask_price, 2), volume_24h=vol_24h,
                            hours_to_expiry=round(hours_left, 1) if hours_left is not None else None,
                            filter_reason=filter_reason,
                        ))
                        continue

                    model_prob_val = 0.0
                    edge_val = 0.0
                    floor_strike = m.get("floor_strike")
                    cap_strike = m.get("cap_strike")
                    strike_type = m.get("strike_type", "between")
                    spot_val = 0.0
                    vol_val = 0.0

                    if floor_strike is not None:
                        floor_strike = float(floor_strike)
                    if cap_strike is not None:
                        cap_strike = float(cap_strike)

                    if series in underlying_data and (floor_strike is not None or cap_strike is not None):
                        spot_val = underlying_data[series]["spot"]
                        vol_val = underlying_data[series]["vol"]
                        t_years = (hours_left or 0) * hours_to_years
                        if t_years > 0:
                            result = compute_edge(
                                spot_val, floor_strike, cap_strike, strike_type,
                                t_years, vol_val, ask_price,
                            )
                            model_prob_val = result.model_prob
                            edge_val = result.edge

                    kalshi_markets_list.append(KalshiMarketSnapshot(
                        ticker=ticker,
                        series=series,
                        title=title,
                        price=round(ask_price, 2),
                        model_prob=round(model_prob_val, 4),
                        edge=round(edge_val, 4),
                        floor_strike=floor_strike,
                        cap_strike=cap_strike,
                        strike_type=strike_type,
                        underlying_price=round(spot_val, 2),
                        realized_vol=round(vol_val, 4),
                        volume_24h=vol_24h,
                        hours_to_expiry=round(hours_left, 1),
                        expiry_time=ct,
                        would_signal=edge_val >= kalshi_cfg.min_edge and edge_val > 0,
                    ))

            kalshi_markets_list.sort(key=lambda x: x.edge, reverse=True)
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
                    Signal.venue == "climate",
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

        if venue in ("all", "climate"):
            try:
                kc = KalshiClient.public()
                climate_series = [s.strip() for s in climate_cfg.series_tickers.split(",") if s.strip()]
                now = datetime.now(timezone.utc)
                today_utc = now.date()
                cutoff = now + timedelta(hours=climate_cfg.min_hours_to_expiry)

                # Per-series sigma + per-date forecast caches
                sigma_cache: dict[tuple[str, str], float | None] = {}
                forecast_cache: dict[tuple[str, str, str], float | None] = {}

                async def resolve_forecast(series_ticker: str, event_ticker: str):
                    mapping = series_to_city_kind(series_ticker)
                    if not mapping:
                        return None
                    city, kind = mapping
                    target_date = parse_event_date(event_ticker or series_ticker)
                    if not target_date:
                        return None
                    sigma_k = (city, kind)
                    if sigma_k not in sigma_cache:
                        sigma_cache[sigma_k] = await get_daily_extreme_vol(city, kind, days=180)
                    sigma = sigma_cache[sigma_k]
                    if sigma is None or sigma <= 0:
                        return None
                    fc_k = (city, kind, target_date.isoformat())
                    if fc_k not in forecast_cache:
                        forecast_cache[fc_k] = await get_forecast_daily_value(city, kind, target_date)
                    fc = forecast_cache[fc_k]
                    if fc is None:
                        return None
                    days_ahead = max((target_date - today_utc).days, 1)
                    return city, kind, target_date, fc, sigma, days_ahead

                for series in climate_series:
                    try:
                        data = await kc.get_markets(series_ticker=series, limit=200)
                    except Exception:
                        continue

                    for m in data.get("markets", []):
                        vol_24h = float(m.get("volume_24h_fp", 0) or 0)
                        ask_price = float(m.get("yes_ask_dollars", 0) or 0)
                        ask_size = float(m.get("yes_ask_size_fp", 0) or 0)
                        ticker = m.get("ticker", "")
                        title = m.get("title", "")
                        event_ticker = m.get("event_ticker", "")

                        close_time = m.get("close_time", "")
                        try:
                            ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                            hours_left = (ct - now).total_seconds() / 3600
                        except (ValueError, AttributeError):
                            ct = None
                            hours_left = None

                        filter_reason = None
                        if ask_price <= 0:
                            filter_reason = "no_ask"
                        elif ask_size < 1:
                            filter_reason = "no_ask_size"
                        elif vol_24h < climate_cfg.min_volume_24h:
                            filter_reason = "low_volume"
                        elif ask_price < climate_cfg.min_price or ask_price > climate_cfg.max_price:
                            filter_reason = "price_range"
                        elif ct is None:
                            filter_reason = "invalid_expiry"
                        elif ct < cutoff:
                            filter_reason = "expiry_too_soon"

                        if filter_reason:
                            climate_filtered_list.append(KalshiFilteredMarket(
                                ticker=ticker, series=series, title=title,
                                price=round(ask_price, 2), volume_24h=vol_24h,
                                hours_to_expiry=round(hours_left, 1) if hours_left is not None else None,
                                filter_reason=filter_reason,
                            ))
                            continue

                        model_prob_val = 0.0
                        edge_val = 0.0
                        floor_strike = m.get("floor_strike")
                        cap_strike = m.get("cap_strike")
                        strike_type = m.get("strike_type", "between")
                        forecast_val = 0.0
                        sigma_val = 0.0

                        if floor_strike is not None:
                            floor_strike = float(floor_strike)
                        if cap_strike is not None:
                            cap_strike = float(cap_strike)

                        resolved = await resolve_forecast(series, event_ticker)
                        if resolved and (floor_strike is not None or cap_strike is not None):
                            _city, _kind, _date, forecast_val, sigma_val, days_ahead = resolved
                            result = compute_climate_edge(
                                forecast_val, floor_strike, cap_strike, strike_type,
                                sigma_val, ask_price, city=_city, days_ahead=days_ahead,
                            )
                            model_prob_val = result.model_prob
                            edge_val = result.edge

                        climate_markets_list.append(KalshiMarketSnapshot(
                            ticker=ticker,
                            series=series,
                            title=title,
                            price=round(ask_price, 2),
                            model_prob=round(model_prob_val, 4),
                            edge=round(edge_val, 4),
                            floor_strike=floor_strike,
                            cap_strike=cap_strike,
                            strike_type=strike_type,
                            underlying_price=round(forecast_val, 2),
                            realized_vol=round(sigma_val, 4),
                            volume_24h=vol_24h,
                            hours_to_expiry=round(hours_left, 1),
                            expiry_time=ct,
                            would_signal=edge_val >= climate_cfg.min_edge and edge_val > 0,
                        ))

                climate_markets_list.sort(key=lambda x: x.edge, reverse=True)
            except Exception:
                pass

    climate_scanner_health = None
    try:
        import json as _json
        from pathlib import Path

        raw = Path("/tmp/scanner_health_climate.json").read_text()
        climate_scanner_health = _json.loads(raw)
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
    venue: str = Query("all", pattern="^(all|crypto|climate)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    pnl_venue_filter = []
    if venue == "crypto":
        pnl_venue_filter = [Signal.venue == "kalshi"]
    elif venue == "climate":
        pnl_venue_filter = [Signal.venue == "climate"]

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
