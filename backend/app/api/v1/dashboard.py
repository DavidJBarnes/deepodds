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
from app.services.binance_client import get_crypto_prices, get_realized_vol
from app.services.config_resolver import resolve_crypto_config, resolve_kalshi_config
from app.services.kalshi_client import KalshiClient
from app.services.mean_reversion import _compute_vwap_and_std, _public_candles, compute_z_score
from app.services.probability_model import compute_edge, series_to_underlying

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

    # Unrealized P&L applies to crypto positions where we hold the underlying
    # and its current price drives our position value. Kalshi binary contracts
    # price in [$0, $1] — applying the same formula gives nonsense (a $0.07
    # contract vs ETH spot of $2,070 would yield ~$41k unrealized "profit").
    # Kalshi unrealized requires querying current Kalshi market prices per
    # ticker; do that as a follow-up. For now we omit it for Kalshi signals.
    needed_symbols: set[str] = set()
    for s in recent:
        if s.status == "filled" and s.fill_price and s.venue == "crypto":
            needed_symbols.add(s.pair.replace("-USD", ""))

    unrealized_prices: dict[str, float] = {}
    if needed_symbols:
        try:
            unrealized_prices = await get_crypto_prices(sorted(needed_symbols))
        except Exception:
            unrealized_prices = {}

    recent_signals = []
    for s in recent:
        unrealized = None
        if s.status == "filled" and s.fill_price and s.venue == "crypto":
            symbol = s.pair.replace("-USD", "")
            current = unrealized_prices.get(symbol, 0)
            if current > 0:
                qty = s.fill_quantity or s.quantity
                unrealized = round((current - s.fill_price) * qty, 4)

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
                model_prob=s.model_prob,
                market_prob=s.market_prob,
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
    breakevens = (
        await db.execute(
            select(func.count())
            .select_from(Signal)
            .where(Signal.user_id == user.id, Signal.status == "settled_breakeven")
        )
    ).scalar()
    settled_count = wins + losses + breakevens
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
                Signal.status.in_(["settled_win", "settled_loss", "settled_breakeven"]),
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
    crypto_symbols = [p.replace("-USD", "") for p in pairs]
    try:
        prices = await get_crypto_prices(crypto_symbols) if crypto_symbols else {}
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
        kalshi_open_stats = (
            await db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(Signal.cost_usd), 0.0),
                    func.coalesce(func.sum(Signal.quantity), 0.0),
                )
                .select_from(Signal)
                .where(Signal.user_id == user.id, Signal.venue == "kalshi", Signal.status.in_(OPEN_STATUSES))
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

        kalshi_overrides = {}
        for pc in (
            await db.execute(select(PairConfig).where(PairConfig.user_id == user.id, PairConfig.venue == "kalshi"))
        ).scalars().all():
            kalshi_overrides[pc.pair] = pc

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
                    vol = await get_realized_vol(symbol, hours=kalshi_cfg.vol_lookback_hours, interval=kalshi_cfg.vol_interval)
                    if vol and vol > 0:
                        underlying_data[series] = {"spot": spot_prices[symbol], "vol": vol}
                except Exception:
                    pass

            for series in series_list:
                eff = resolve_kalshi_config(kalshi_cfg, kalshi_overrides.get(series))
                eff_min_edge = eff["min_edge"]

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
                        would_signal=edge_val >= eff_min_edge and edge_val > 0,
                    ))

            kalshi_markets_list.sort(key=lambda x: x.edge, reverse=True)
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
