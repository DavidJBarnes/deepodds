"""Score loop — computes ML edge for unscored market snapshots."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.market_snapshot import MarketSnapshot

logger = logging.getLogger("scanner.score")

_VENUE_CLIMATE = "kalshi_climate"


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

            # MarketSnapshot has no event_ticker attribute; parse the date
            # directly from the market_ticker. The previous getattr lookup
            # for `_event_ticker` always returned None and the OR-fallback
            # silently masked the dead reference.
            target_date = parse_event_date(row.ticker or "")
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
