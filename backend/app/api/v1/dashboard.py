from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.bot_config import BotConfig
from app.models.kalshi_config import KalshiConfig
from app.models.pair_config import PairConfig
from app.models.signal import Signal
from app.models.user import User
from app.schemas.dashboard import (
    BotStatusResponse,
    DailyPnLPoint,
    DashboardResponse,
    KalshiFilteredMarket,
    KalshiMarketSnapshot,
    KalshiStatusResponse,
    MarketSnapshot,
    PnLChartResponse,
    PnLStats,
)
from app.schemas.signal import SignalResponse
from app.services.binance_client import get_crypto_prices
from app.services.config_resolver import resolve_crypto_config, resolve_kalshi_config
from app.services.kalshi_client import KalshiClient
from app.services.kalshi_mean_reversion import _kalshi_candles_to_generic
from app.services.mean_reversion import _compute_vwap_and_std, _public_candles, compute_z_score

router = APIRouter(tags=["dashboard"])

OPEN_STATUSES = ("signaled", "placed", "filled")


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(BotConfig).where(BotConfig.user_id == user.id))
    ).scalar_one_or_none()

    if not config:
        config = BotConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    open_count = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status.in_(OPEN_STATUSES))
        )
    ).scalar()

    keys_valid = False
    if user.robinhood_api_key:
        try:
            from app.services.robinhood_client import RobinhoodClient

            RobinhoodClient(user.robinhood_api_key, user.robinhood_private_key)
            keys_valid = True
        except Exception:
            pass

    bot_status = BotStatusResponse(
        mode=config.mode,
        enabled=config.enabled,
        has_exchange_keys=bool(user.robinhood_api_key),
        exchange_keys_valid=keys_valid,
        pairs=config.pairs,
        open_positions=open_count,
        max_open_positions=config.max_open_positions,
        entry_z_score=config.entry_z_score,
        exit_z_score=config.exit_z_score,
        stop_loss_pct=config.stop_loss_pct,
    )

    recent = (
        await db.execute(
            select(Signal)
            .where(Signal.user_id == user.id)
            .order_by(Signal.created_at.desc())
            .limit(50)
        )
    ).scalars().all()

    recent_signals = []
    for s in recent:
        unrealized = None
        if s.status == "filled" and s.fill_price:
            try:
                prices = await get_crypto_prices()
                symbol = s.pair.replace("-USD", "")
                current = prices.get(symbol, 0)
                if current > 0:
                    qty = s.fill_quantity or s.quantity
                    unrealized = round((current - s.fill_price) * qty, 4)
            except Exception:
                pass

        recent_signals.append(
            SignalResponse(
                id=s.id,
                venue=s.venue or "crypto",
                pair=s.pair,
                side=s.side,
                signal_type=s.signal_type,
                status=s.status,
                entry_price=s.entry_price,
                quantity=s.quantity,
                cost_usd=s.cost_usd,
                z_score=s.z_score,
                vwap=s.vwap,
                exchange_order_id=s.exchange_order_id,
                fill_price=s.fill_price,
                fill_quantity=s.fill_quantity,
                filled_at=s.filled_at,
                exit_price=s.exit_price,
                exit_z_score=s.exit_z_score,
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

    # Stats
    total_signals = (
        await db.execute(
            select(func.count()).select_from(Signal).where(Signal.user_id == user.id)
        )
    ).scalar()
    wins = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "settled_win")
        )
    ).scalar()
    losses = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "settled_loss")
        )
    ).scalar()
    settled_count = wins + losses
    total_pnl = (
        await db.execute(
            select(func.coalesce(func.sum(Signal.pnl_usd), 0.0)).where(
                Signal.user_id == user.id, Signal.pnl_usd.isnot(None)
            )
        )
    ).scalar()
    total_cost = (
        await db.execute(
            select(func.coalesce(func.sum(Signal.cost_usd), 0.0)).where(
                Signal.user_id == user.id,
                Signal.status.in_(["settled_win", "settled_loss"]),
            )
        )
    ).scalar()

    open_positions_count = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "filled")
        )
    ).scalar()

    total_unrealized = sum(s.unrealized_pnl_usd or 0 for s in recent_signals)

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

    # Market snapshots — current z-scores for each configured pair
    crypto_overrides = {}
    for pc in (
        await db.execute(select(PairConfig).where(PairConfig.user_id == user.id, PairConfig.venue == "crypto"))
    ).scalars().all():
        crypto_overrides[pc.pair] = pc

    markets = []
    pairs = [p.strip() for p in config.pairs.split(",") if p.strip()]
    try:
        prices = await get_crypto_prices()
        for pair in pairs:
            symbol = pair.replace("-USD", "")
            price = prices.get(symbol, 0)
            if price <= 0:
                continue

            eff = resolve_crypto_config(config, crypto_overrides.get(pair))
            eff_entry_z = eff["entry_z_score"]

            try:
                candles = await _public_candles(pair, 96)
                vwap, std = _compute_vwap_and_std(candles, config.lookback_periods)
                z = compute_z_score(price, vwap, std) if vwap > 0 and std > 0 else 0
            except Exception:
                vwap, std, z = price, 0, 0

            min_z_24h = z
            if candles and len(candles) >= config.lookback_periods and std > 0:
                try:
                    window = config.lookback_periods
                    for i in range(1, min(len(candles) - window + 1, 96 - window + 1)):
                        w_candles = candles[i:i + window]
                        w_vwap, w_std = _compute_vwap_and_std(w_candles, window)
                        if w_vwap > 0 and w_std > 0:
                            w_close = float(w_candles[0].get("close", 0))
                            if w_close > 0:
                                w_z = compute_z_score(w_close, w_vwap, w_std)
                                min_z_24h = min(min_z_24h, w_z)
                except Exception:
                    pass

            z_distance = z - eff_entry_z

            markets.append(
                MarketSnapshot(
                    pair=pair,
                    price=round(price, 2),
                    vwap=round(vwap, 2),
                    z_score=round(z, 2),
                    std_dev=round(std, 2),
                    would_signal=z <= eff_entry_z and z != 0,
                    min_z_24h=round(min_z_24h, 2),
                    z_distance=round(z_distance, 2),
                    effective_entry_z=eff_entry_z,
                )
            )
    except Exception:
        pass

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
        kalshi_open = (
            await db.execute(
                select(func.count())
                .select_from(Signal)
                .where(Signal.user_id == user.id, Signal.venue == "kalshi", Signal.status.in_(OPEN_STATUSES))
            )
        ).scalar()
        kalshi_status = KalshiStatusResponse(
            enabled=kalshi_cfg.enabled,
            has_keys=bool(user.kalshi_api_key_id),
            series_tickers=kalshi_cfg.series_tickers,
            open_positions=kalshi_open,
            max_open_positions=kalshi_cfg.max_open_positions,
            entry_z_score=kalshi_cfg.entry_z_score,
            exit_z_score=kalshi_cfg.exit_z_score,
        )

        kalshi_overrides = {}
        for pc in (
            await db.execute(select(PairConfig).where(PairConfig.user_id == user.id, PairConfig.venue == "kalshi"))
        ).scalars().all():
            kalshi_overrides[pc.pair] = pc

        try:
            import time as _time

            kc = KalshiClient.public()
            series_list = [s.strip() for s in kalshi_cfg.series_tickers.split(",") if s.strip()]
            now_ts = int(_time.time())
            cutoff = datetime.now(timezone.utc) + timedelta(hours=kalshi_cfg.min_hours_to_expiry)
            lookback_sec = kalshi_cfg.lookback_periods * kalshi_cfg.candle_interval * 60

            for series in series_list:
                eff = resolve_kalshi_config(kalshi_cfg, kalshi_overrides.get(series))
                eff_entry_z = eff["entry_z_score"]

                try:
                    data = await kc.get_markets(series_ticker=series, limit=50)
                except Exception:
                    continue

                for m in data.get("markets", []):
                    vol_24h = float(m.get("volume_24h_fp", 0))
                    last_price = float(m.get("last_price_dollars", 0))
                    ticker = m.get("ticker", "")
                    title = m.get("title", "")

                    close_time = m.get("close_time", "")
                    try:
                        ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                        hours_left = (ct - datetime.now(timezone.utc)).total_seconds() / 3600
                    except (ValueError, AttributeError):
                        ct = None
                        hours_left = None

                    filter_reason = None
                    if last_price <= 0:
                        filter_reason = "no_trades"
                    elif vol_24h < kalshi_cfg.min_volume_24h:
                        filter_reason = "low_volume"
                    elif last_price < kalshi_cfg.min_price or last_price > kalshi_cfg.max_price:
                        filter_reason = "price_range"
                    elif ct is None:
                        filter_reason = "invalid_expiry"
                    elif ct < cutoff:
                        filter_reason = "expiry_too_soon"

                    if filter_reason:
                        kalshi_filtered_list.append(KalshiFilteredMarket(
                            ticker=ticker, series=series, title=title,
                            price=round(last_price, 2), volume_24h=vol_24h,
                            hours_to_expiry=round(hours_left, 1) if hours_left is not None else None,
                            filter_reason=filter_reason,
                        ))
                        continue

                    vwap, std, z = 0.0, 0.0, 0.0
                    try:
                        candles = await kc.get_candlesticks(
                            series, ticker,
                            start_ts=now_ts - lookback_sec - 300,
                            end_ts=now_ts,
                            period_interval=kalshi_cfg.candle_interval,
                        )
                        generic = _kalshi_candles_to_generic(candles)
                        if generic:
                            vwap, std = _compute_vwap_and_std(generic, kalshi_cfg.lookback_periods)
                            if vwap > 0 and std > 0:
                                z = compute_z_score(last_price, vwap, std)
                    except Exception:
                        pass

                    z_distance = z - eff_entry_z

                    kalshi_markets_list.append(KalshiMarketSnapshot(
                        ticker=ticker,
                        series=series,
                        title=title,
                        price=round(last_price, 2),
                        vwap=round(vwap, 4),
                        z_score=round(z, 2),
                        std_dev=round(std, 4),
                        volume_24h=vol_24h,
                        hours_to_expiry=round(hours_left, 1),
                        would_signal=z <= eff_entry_z and z != 0,
                        z_distance=round(z_distance, 2),
                        effective_entry_z=eff_entry_z,
                    ))

            kalshi_markets_list.sort(key=lambda x: x.volume_24h, reverse=True)
        except Exception:
            pass

    return DashboardResponse(
        bot_status=bot_status,
        kalshi_status=kalshi_status,
        recent_signals=recent_signals,
        markets=markets,
        kalshi_markets=kalshi_markets_list,
        kalshi_filtered=kalshi_filtered_list,
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
