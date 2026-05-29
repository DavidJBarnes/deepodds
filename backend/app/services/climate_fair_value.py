"""Climate market scanning engine — parallel to kalshi_fair_value for crypto.

Per-market lookup of the forecasted daily extreme for the market's resolution
date. Spot is the forecast for that date, not the current observation.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.models.climate_config import ClimateConfig
from app.models.history import History
from app.models.signal import Signal
from app.services.climate_probability_model import compute_climate_edge
from app.services.kalshi_client import KalshiClient
from app.services.kalshi_utils import (
    OPEN_STATUSES,
    check_spread_filter,
    discover_markets,
    kelly_count,
    market_ask,
    market_ask_size,
    market_bid,
    market_mid,
    market_spread_pct,
    read_balance_cache,
)
from app.services.weather_client import (
    get_daily_extreme_history,
    get_daily_extreme_vol,
    get_forecast_daily_value,
    parse_event_date,
    series_to_city_kind,
)

logger = logging.getLogger(__name__)

VENUE = "kalshi_climate"


def _today_pnl_climate(session: Session, user_id) -> float:
    today_ny = datetime.now(ZoneInfo("America/New_York")).date()
    result = session.execute(
        select(func.coalesce(func.sum(Signal.pnl_usd), 0.0)).where(
            Signal.user_id == user_id,
            Signal.venue == VENUE,
            func.date(func.timezone("America/New_York", Signal.resolved_at)) == today_ny,
            Signal.pnl_usd.isnot(None),
        )
    )
    return float(result.scalar())


def _signals_last_hour_climate(session: Session, user_id) -> int:
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = session.execute(
        select(func.count(Signal.id)).where(
            Signal.user_id == user_id,
            Signal.venue == VENUE,
            Signal.created_at >= one_hour_ago,
            Signal.status.notin_(["cancelled"]),
        )
    )
    return result.scalar()


def _open_climate_positions(session: Session, user_id) -> list[Signal]:
    return list(
        session.execute(
            select(Signal).where(
                Signal.user_id == user_id,
                Signal.venue == VENUE,
                Signal.status.in_(OPEN_STATUSES),
            )
        ).scalars().all()
    )


def _has_traded_ticker(session: Session, user_id, market_ticker: str) -> bool:
    result = session.execute(
        select(Signal.id).where(
            Signal.user_id == user_id,
            Signal.venue == VENUE,
            Signal.market_ticker == market_ticker,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def _open_event_count(session: Session, user_id, event_ticker: str) -> int:
    if not event_ticker:
        return 0
    return session.execute(
        select(func.count(Signal.id)).where(
            Signal.user_id == user_id,
            Signal.venue == VENUE,
            Signal.event_ticker == event_ticker,
            Signal.status.in_(OPEN_STATUSES),
        )
    ).scalar() or 0


def _resolve_market_underlying(
    series_ticker: str,
    event_ticker: str,
    cache: dict,
) -> tuple[str, str, date, float, float, int] | None:
    """Look up (city, kind, target_date, forecast, sigma, days_ahead) for a market.

    cache key: (city, kind, target_date) -> (forecast, sigma).
    """
    mapping = series_to_city_kind(series_ticker)
    if not mapping:
        return None
    city, kind = mapping
    target_date = parse_event_date(event_ticker or series_ticker)
    if not target_date:
        return None

    key = (city, kind, target_date)
    if key in cache:
        cached = cache[key]
        if cached is None:
            return None
        forecast, sigma = cached
    else:
        forecast = run_async(get_forecast_daily_value(city, kind, target_date))
        sigma = run_async(get_daily_extreme_vol(city, kind, days=180))
        if forecast is None or sigma is None or sigma <= 0:
            cache[key] = None
            return None
        cache[key] = (forecast, sigma)

    today = datetime.now(timezone.utc).date()
    days_ahead = max((target_date - today).days, 1)
    return city, kind, target_date, forecast, sigma, days_ahead


def scan_climate_entries(
    user_id,
    session: Session,
    client: KalshiClient | None = None,
) -> list[Signal]:
    config = session.execute(
        select(ClimateConfig).where(ClimateConfig.user_id == user_id)
    ).scalar_one_or_none()

    if not config or not config.enabled:
        return []

    if config.daily_loss_limit_usd > 0:
        if _today_pnl_climate(session, user_id) <= -config.daily_loss_limit_usd:
            logger.warning("Climate daily loss limit hit — skipping scan")
            return []

    if config.max_signals_per_hour > 0:
        if _signals_last_hour_climate(session, user_id) >= config.max_signals_per_hour:
            return []

    open_pos = _open_climate_positions(session, user_id)
    if len(open_pos) >= config.max_open_positions:
        return []

    series = [s.strip() for s in config.series_tickers.split(",") if s.strip()]
    client = client or KalshiClient.public()

    markets = discover_markets(
        client, series,
        config.min_volume_24h, config.min_price, config.max_price,
        config.min_hours_to_expiry, min_ask_size=1,
    )

    forecast_cache: dict = {}
    now = datetime.now(timezone.utc)
    signals_created = []
    event_counts: dict[str, int] = {}
    for sig in open_pos:
        if sig.event_ticker:
            event_counts[sig.event_ticker] = event_counts.get(sig.event_ticker, 0) + 1

    for market_data in markets:
        ticker = market_data.get("ticker")
        if not ticker:
            continue
        series_ticker = market_data.get("_series_ticker")
        event_ticker = market_data.get("event_ticker")

        try:
            resolved = _resolve_market_underlying(series_ticker, event_ticker, forecast_cache)
            if not resolved:
                continue
            city, kind, target_date, forecast_value, forecast_sigma, days_ahead = resolved

            if _has_traded_ticker(session, user_id, ticker):
                continue

            if event_ticker and event_counts.get(event_ticker, 0) >= config.max_positions_per_event:
                continue

            if len(open_pos) + len(signals_created) >= config.max_open_positions:
                break

            floor_strike = market_data.get("floor_strike")
            cap_strike = market_data.get("cap_strike")
            strike_type = market_data.get("strike_type", "between")
            ask = float(market_data.get("_ask") or market_ask(market_data))
            bid = float(market_data.get("_bid") or market_bid(market_data))
            mid = float(market_data.get("_mid") or market_mid(market_data))
            spread_pct = float(market_data.get("_spread_pct") or market_spread_pct(market_data))
            market_price = mid if mid > 0 else ask

            if market_price <= 0:
                continue

            if floor_strike is not None:
                floor_strike = float(floor_strike)
            if cap_strike is not None:
                cap_strike = float(cap_strike)

            if strike_type == "between" and (floor_strike is None or cap_strike is None):
                continue
            if strike_type == "greater" and floor_strike is None:
                continue
            if strike_type == "less" and cap_strike is None:
                continue

            ask_sz = market_ask_size(market_data)
            if ask_sz < config.contracts_per_signal:
                continue

            result = compute_climate_edge(
                forecast_value, floor_strike, cap_strike, strike_type,
                forecast_sigma, market_price, city=city, days_ahead=days_ahead,
            )

            logger.info(
                "CLIMATE ML %s: fcst=%.1f sigma=%.2f d=%d model=%.1f%% mkt=%.1f%% edge=%.1f%% spread=%.1f%%",
                ticker, forecast_value, forecast_sigma, days_ahead,
                result.model_prob * 100, result.market_prob * 100,
                result.edge * 100, spread_pct,
            )

            if result.edge < config.min_edge:
                continue

            if not check_spread_filter(result.edge, spread_pct, mid, bid, config.stop_loss_pct, ticker):
                continue

            bankroll_cents = read_balance_cache(str(user_id))
            if bankroll_cents and bankroll_cents > 0:
                count = kelly_count(
                    result.edge, market_price, bankroll_cents,
                    config.contracts_per_signal, config.max_cost_per_signal,
                )
            else:
                count = config.contracts_per_signal
                if market_price > 0 and market_price * count > config.max_cost_per_signal:
                    count = int(config.max_cost_per_signal / market_price)

            if count < 1:
                continue

            cost = market_price * count
            close_dt = market_data.get("_close_dt")

            signal = Signal(
                user_id=user_id,
                venue=VENUE,
                pair=series_ticker,
                side="buy",
                signal_type=config.mode,
                status="signaled",
                entry_price=market_price,
                quantity=float(count),
                cost_usd=cost,
                model_prob=result.model_prob,
                market_prob=result.market_prob,
                edge=result.edge,
                floor_strike=floor_strike,
                cap_strike=cap_strike,
                strike_type=strike_type,
                underlying_price=forecast_value,
                realized_vol=forecast_sigma,
                market_ticker=ticker,
                event_ticker=event_ticker,
                expiry_time=close_dt,
            )

            if config.mode == "live" and client:
                session.add(signal)
                session.commit()
                signals_created.append(signal)
                if event_ticker:
                    event_counts[event_ticker] = event_counts.get(event_ticker, 0) + 1

                try:
                    max_price_cents = int(round(config.max_price * 100))
                    limit_price = round(mid * 100) if mid > 0 else round(ask * 100)
                    yes_price_cents = min(int(limit_price), max_price_cents)
                    order_result = run_async(client.create_order(
                        ticker=ticker, side="yes", count=count,
                        yes_price_cents=yes_price_cents,
                    ))
                    order = order_result.get("order", order_result)
                    signal.exchange_order_id = order.get("order_id")
                    signal.status = "placed"
                    session.commit()
                    logger.info("LIVE CLIMATE BUY %s: %d @ $%.2f", ticker, count, yes_price_cents / 100)
                    session.add(History(
                        user_id=user_id,
                        text=f"Climate signal: live purchase of {ticker}: {count} @ ${yes_price_cents / 100:.2f}",
                    ))
                    session.commit()
                except Exception as e:
                    signal.status = "cancelled"
                    signal.error_message = str(e)[:200]
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                    session.add(History(user_id=user_id, text=f"Climate signal cancelled for {ticker}: {str(e)[:120]}"))
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
            else:
                paper_fill = ask if ask > 0 else market_price
                signal.status = "filled"
                signal.fill_price = paper_fill
                signal.fill_quantity = float(count)
                signal.cost_usd = round(paper_fill * count, 4)
                signal.filled_at = datetime.now(timezone.utc)
                session.add(signal)
                session.commit()
                signals_created.append(signal)
                if event_ticker:
                    event_counts[event_ticker] = event_counts.get(event_ticker, 0) + 1
                logger.info(
                    "PAPER CLIMATE BUY %s: %d @ $%.2f (model=%.0f%% edge=+%.0f%%)",
                    ticker, count, paper_fill, result.model_prob * 100, result.edge * 100,
                )
                session.add(History(
                    user_id=user_id,
                    text=f"Climate signal: paper purchase of {ticker}: {count} @ ${paper_fill:.2f}",
                ))
                try:
                    session.commit()
                except Exception:
                    session.rollback()

        except Exception:
            logger.exception("Climate per-market scan error on %s", ticker)
            try:
                session.rollback()
            except Exception:
                pass
            continue

    return signals_created


def check_climate_exits(
    session: Session,
    exchange_clients: dict[str, KalshiClient] | None = None,
) -> int:
    filled = session.execute(
        select(Signal).where(
            Signal.venue == VENUE,
            Signal.status == "filled",
            Signal.fill_price.isnot(None),
        )
    ).scalars().all()

    if not filled:
        return 0

    user_ids = {s.user_id for s in filled}
    configs = {}
    for uid in user_ids:
        cfg = session.execute(
            select(ClimateConfig).where(ClimateConfig.user_id == uid)
        ).scalar_one_or_none()
        if cfg:
            configs[uid] = cfg

    forecast_cache: dict = {}
    exited = 0
    now = datetime.now(timezone.utc)
    exchange_clients = exchange_clients or {}

    for sig in filled:
        cfg = configs.get(sig.user_id)
        if not cfg:
            continue

        client = exchange_clients.get(str(sig.user_id))

        if not sig.market_ticker or not sig.pair:
            continue

        try:
            market_data = run_async((client or KalshiClient.public()).get_market(sig.market_ticker))
            sig.live_market_prob = float(
                market_data.get("last_price_dollars") or market_data.get("yes_bid_dollars") or 0
            )
            price = float(market_data.get("yes_bid_dollars") or market_data.get("last_price_dollars", 0))
        except Exception:
            logger.warning("Failed to get price for %s", sig.market_ticker)
            continue

        if price <= 0:
            continue

        pnl_pct = (price - sig.fill_price) / sig.fill_price * 100 if sig.fill_price > 0 else 0
        qty = sig.fill_quantity or sig.quantity
        pnl_usd = (price - sig.fill_price) * qty

        current_edge = 0.0
        resolved = _resolve_market_underlying(sig.pair, sig.event_ticker, forecast_cache)
        if resolved and (sig.floor_strike is not None or sig.cap_strike is not None):
            city, kind, target_date, forecast_value, forecast_sigma, days_ahead = resolved
            result = compute_climate_edge(
                forecast_value, sig.floor_strike, sig.cap_strike,
                sig.strike_type or "between",
                forecast_sigma, price, city=city, days_ahead=days_ahead,
            )
            current_edge = result.edge

        hold_minutes = (now - sig.filled_at).total_seconds() / 60 if sig.filled_at else 999
        min_hold = cfg.min_hold_minutes

        should_exit = False
        exit_reason = ""

        fee_estimate_pct = 0.07
        adjusted_pnl_pct = pnl_pct - fee_estimate_pct
        catastrophic_threshold = -cfg.stop_loss_pct * 2

        if adjusted_pnl_pct <= catastrophic_threshold:
            should_exit = True
            exit_reason = f"catastrophic_stop ({pnl_pct:.1f}%)"
        elif adjusted_pnl_pct <= -cfg.stop_loss_pct and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"stop_loss ({pnl_pct:.1f}%)"
        elif sig.expiry_time and (sig.expiry_time - now) < timedelta(hours=cfg.min_hours_to_expiry / 2):
            should_exit = True
            exit_reason = "approaching_expiry"
        elif sig.filled_at and (now - sig.filled_at) > timedelta(hours=24):
            should_exit = True
            exit_reason = "max_hold (24h)"
        elif cfg.take_profit_pct > 0 and pnl_pct >= cfg.take_profit_pct and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"take_profit ({pnl_pct:.1f}%)"
        elif current_edge <= cfg.exit_edge and hold_minutes >= min_hold:
            should_exit = True
            exit_reason = f"edge_lost ({current_edge:+.1%})"

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
                logger.info("LIVE CLIMATE SELL %s: %s", sig.market_ticker, exit_reason)
                session.add(History(
                    user_id=sig.user_id,
                    text=f"Climate signal closing {sig.market_ticker}: {exit_reason}",
                ))
                session.commit()
                exited += 1
            except Exception:
                logger.exception("Failed to sell climate position %s", sig.market_ticker)
            continue

        sig.exit_price = price
        paper_fee = round((sig.fill_price + price) * qty * 0.0007, 4)
        sig.pnl_usd = round(pnl_usd - paper_fee, 4)
        sig.pnl_pct = round((sig.pnl_usd / (sig.fill_price * qty)) * 100, 2) if sig.fill_price > 0 and qty > 0 else 0.0
        sig.resolved_at = now
        if pnl_usd > 0:
            sig.status = "settled_win"
        elif pnl_usd < 0:
            sig.status = "settled_loss"
        else:
            sig.status = "settled_breakeven"

        exited += 1
        logger.info(
            "CLIMATE %s %s: exit @ $%.2f (entry $%.2f, %s, P&L $%.4f / %.1f%%)",
            sig.status.upper(), sig.market_ticker, price, sig.fill_price,
            exit_reason, pnl_usd, pnl_pct,
        )
        session.add(History(
            user_id=sig.user_id,
            text=f"Climate signal exited {sig.market_ticker}: {exit_reason}, P&L ${pnl_usd:.2f} ({pnl_pct:.1f}%)",
        ))

    session.commit()
    return exited


def settle_expired_climate_paper(session: Session) -> int:
    """Resolve expired paper climate positions using the actual daily extreme."""
    now = datetime.now(timezone.utc)
    expired = session.execute(
        select(Signal).where(
            Signal.venue == VENUE,
            Signal.signal_type == "paper",
            Signal.status == "filled",
            Signal.expiry_time.isnot(None),
            Signal.expiry_time < now,
            Signal.fill_price.isnot(None),
        )
    ).scalars().all()

    if not expired:
        return 0

    settled = 0
    history_cache: dict = {}
    for sig in expired:
        try:
            mapping = series_to_city_kind(sig.pair or "")
            target_date = parse_event_date(sig.event_ticker or "")
            actual_value = None
            if mapping and target_date:
                city, kind = mapping
                cache_key = (city, kind)
                if cache_key not in history_cache:
                    history_cache[cache_key] = run_async(
                        get_daily_extreme_history(city, kind, days=30)
                    )
                values = history_cache[cache_key]
                if values:
                    # archive returns values ending yesterday; index by date
                    today = datetime.now(timezone.utc).date()
                    days_back = (today - target_date).days
                    if 1 <= days_back <= len(values):
                        actual_value = values[-days_back]

            if actual_value is None:
                # Fall back to the stored forecast value (best available)
                actual_value = sig.underlying_price

            floor_val = sig.floor_strike
            cap_val = sig.cap_strike
            typ = sig.strike_type or "between"

            if typ == "between":
                won = (floor_val is not None and cap_val is not None and floor_val <= actual_value <= cap_val)
            elif typ == "greater":
                won = (floor_val is not None and actual_value > floor_val)
            elif typ == "less":
                won = (cap_val is not None and actual_value < cap_val)
            else:
                won = False

            exit_price = 1.0 if won else 0.0
            qty = sig.fill_quantity or sig.quantity or 0
            fill_price = sig.fill_price or 0
            pnl_usd = (exit_price - fill_price) * qty

            sig.exit_price = exit_price
            sig.pnl_usd = round(pnl_usd, 4)
            sig.pnl_pct = round((exit_price - fill_price) / fill_price * 100, 2) if fill_price > 0 else 0.0
            sig.resolved_at = now
            sig.status = "settled_win" if pnl_usd > 0 else "settled_loss" if pnl_usd < 0 else "settled_breakeven"

            settled += 1
            logger.info(
                "CLIMATE PAPER SETTLE %s: actual=%.1f won=%s P&L=$%.2f",
                sig.market_ticker, actual_value, won, pnl_usd,
            )
            session.add(History(
                user_id=sig.user_id,
                text=f"Climate paper settlement for {sig.market_ticker}: {'won' if won else 'lost'} (actual={actual_value:.1f}, P&L=${pnl_usd:.2f})",
            ))
        except Exception:
            logger.exception("Failed to settle climate paper signal %s", sig.market_ticker)
            continue

    session.commit()
    return settled
