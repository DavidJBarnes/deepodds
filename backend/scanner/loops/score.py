"""Score loop — computes ML edge for unscored market snapshots."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.market_snapshot import MarketSnapshot
from app.services.probability_model import series_to_underlying

logger = logging.getLogger("scanner.score")

_VENUE_CRYPTO = "kalshi_crypto"
_VENUE_CLIMATE = "kalshi_climate"
_HOURS_TO_YEARS = 1 / (365.25 * 24)


def score_crypto(session: Session) -> None:
    """Compute model edge for unscored crypto market snapshots."""
    rows = session.execute(
        select(MarketSnapshot).where(
            MarketSnapshot.venue == _VENUE_CRYPTO,
            MarketSnapshot.edge.is_(None),
            MarketSnapshot.filter_reason.is_(None),
            MarketSnapshot.floor_strike.isnot(None),
        ).order_by(MarketSnapshot.discovered_at.asc()).limit(200)
    ).scalars().all()

    if not rows:
        return

    from app.core.async_util import run_async
    from app.services.binance_client import get_crypto_prices, get_realized_vol
    from app.services.probability_model import compute_edge

    symbols = {series_to_underlying(r.series) for r in rows}
    symbols.discard(None)
    spot_prices = {}
    vol_cache: dict[str, float] = {}
    if symbols:
        spot_prices = run_async(get_crypto_prices(list(symbols)))

    scored = 0
    for row in rows:
        symbol = series_to_underlying(row.series)
        if not symbol or symbol not in spot_prices:
            continue

        spot = spot_prices[symbol]
        if spot <= 0:
            continue

        if symbol not in vol_cache:
            try:
                vol = run_async(get_realized_vol(symbol, hours=24, interval="15m"))
                if vol and vol > 0:
                    vol_cache[symbol] = vol
            except Exception:
                pass

        vol = vol_cache.get(symbol)
        if not vol or vol <= 0:
            continue

        t_years = (row.hours_to_expiry or 0) * _HOURS_TO_YEARS
        if t_years <= 0:
            continue

        result = compute_edge(
            spot, row.floor_strike, row.cap_strike, row.strike_type,
            t_years, vol, row.ask_price,
        )

        session.execute(
            update(MarketSnapshot)
            .where(MarketSnapshot.ticker == row.ticker)
            .values(
                underlying_price=spot,
                realized_vol=vol,
                model_prob=result.model_prob,
                raw_model_prob=getattr(result, "raw_model_prob", result.model_prob),
                edge=result.edge,
                scored_at=datetime.now(timezone.utc),
            )
        )
        scored += 1

    if scored:
        session.commit()
        import gc
        gc.collect()
        logger.info("Score crypto: %d markets scored", scored)


def score_climate(session: Session) -> None:
    """Compute model edge for unscored climate market snapshots."""
    rows = session.execute(
        select(MarketSnapshot).where(
            MarketSnapshot.venue == _VENUE_CLIMATE,
            MarketSnapshot.edge.is_(None),
            MarketSnapshot.filter_reason.is_(None),
        ).order_by(MarketSnapshot.discovered_at.asc()).limit(200)
    ).scalars().all()

    if not rows:
        return

    from app.core.async_util import run_async
    from app.services.climate_probability_model import compute_climate_edge
    from app.services.weather_client import (
        get_daily_extreme_vol,
        get_forecast_daily_value,
        parse_event_date,
        series_to_city_kind,
    )

    sigma_cache: dict[tuple[str, str], float] = {}
    forecast_cache: dict[tuple[str, str, str], float] = {}
    today_utc = datetime.now(timezone.utc).date()

    scored = 0
    for row in rows:
        try:
            mapping = series_to_city_kind(row.series)
            if not mapping:
                continue
            city, kind = mapping

            event_ticker_raw = getattr(row, "_event_ticker", None)
            target_date = parse_event_date(event_ticker_raw or row.ticker or "")
            if not target_date:
                continue

            sigma_k = (city, kind)
            if sigma_k not in sigma_cache:
                sigma = run_async(get_daily_extreme_vol(city, kind, days=180))
                if sigma and sigma > 0:
                    sigma_cache[sigma_k] = sigma
            sigma = sigma_cache.get(sigma_k)
            if not sigma or sigma <= 0:
                continue

            fc_k = (city, kind, target_date.isoformat())
            if fc_k not in forecast_cache:
                fc = run_async(get_forecast_daily_value(city, kind, target_date))
                if fc is not None:
                    forecast_cache[fc_k] = fc
            fc = forecast_cache.get(fc_k)
            if fc is None:
                continue

            days_ahead = max((target_date - today_utc).days, 1)

            result = compute_climate_edge(
                fc, row.floor_strike, row.cap_strike, row.strike_type,
                sigma, row.ask_price, city=city, days_ahead=days_ahead,
            )

            session.execute(
                update(MarketSnapshot)
                .where(MarketSnapshot.ticker == row.ticker)
                .values(
                    underlying_price=fc,
                    realized_vol=sigma,
                    model_prob=result.model_prob,
                    raw_model_prob=getattr(result, "raw_model_prob", result.model_prob),
                    edge=result.edge,
                    scored_at=datetime.now(timezone.utc),
                )
            )
            scored += 1
        except Exception:
            logger.exception("Score climate failed for %s", row.ticker)

    if scored:
        session.commit()
        import gc
        gc.collect()
        logger.info("Score climate: %d markets scored", scored)
