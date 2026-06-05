"""Discover loop — fetches Kalshi market listings and populates market_snapshots."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.market_snapshot import MarketSnapshot
from app.services.kalshi_client import KalshiClient
from app.services.kalshi_utils import market_ask, market_ask_size, market_bid, market_mid, market_spread_pct

logger = logging.getLogger("scanner.discover")

_VENUE_CRYPTO = "kalshi_crypto"
_VENUE_CLIMATE = "kalshi_climate"


def _fetch_and_upsert(
    session: Session,
    client: KalshiClient,
    series_list: list[str],
    venue: str,
    min_volume: int = 1,
    min_price: float = 0.01,
    max_price: float = 0.99,
    min_hours_to_expiry: int = 0,
) -> int:
    """Fetch open + settled markets for a list of series and upsert into
    market_snapshots.

    Open markets get the usual filter_reason logic (no_ask / low_volume /
    etc). Settled markets are upserted with filter_reason='settled' so the
    signal-creation loop ignores them, but the exit loop can still read
    their status/result for finalized payouts without making per-ticker
    Kalshi calls.

    Returns the total number of markets upserted across both passes.
    """
    from app.core.async_util import run_async

    now = datetime.now(timezone.utc)
    cutoff = now
    if min_hours_to_expiry > 0:
        from datetime import timedelta
        cutoff = now + timedelta(hours=min_hours_to_expiry)

    count = 0
    for series in series_list:
        # Pass 1: open markets — full filter logic, normal flow.
        try:
            data = run_async(client.get_markets(series_ticker=series, limit=200, status="open"))
        except Exception as e:
            logger.warning("Discover: failed to fetch open markets for %s: %r", series, e)
        else:
            count += _upsert_markets(
                session, data.get("markets", []), series, venue, now, cutoff,
                min_volume, min_price, max_price, kalshi_status="open",
            )

        # Pass 2: settled markets — bypass open-only filters, carry result.
        try:
            data = run_async(client.get_markets(series_ticker=series, limit=200, status="settled"))
        except Exception as e:
            logger.warning("Discover: failed to fetch settled markets for %s: %r", series, e)
        else:
            count += _upsert_markets(
                session, data.get("markets", []), series, venue, now, cutoff,
                min_volume, min_price, max_price, kalshi_status="settled",
            )

        session.commit()
    return count


def _upsert_markets(
    session: Session,
    markets: list[dict],
    series: str,
    venue: str,
    now: datetime,
    cutoff: datetime,
    min_volume: int,
    min_price: float,
    max_price: float,
    kalshi_status: str,
) -> int:
    """Upsert one page of markets from Kalshi into market_snapshots.

    kalshi_status='open' applies normal entry filters; kalshi_status='settled'
    forces filter_reason='settled' so the row is preserved with its result
    but excluded from signal candidates.
    """
    count = 0
    for m in markets:
        ticker = m.get("ticker", "")
        if not ticker:
            continue

        ask_price = market_ask(m)
        ask_size = market_ask_size(m)
        bid_price = market_bid(m)
        mid_price = market_mid(m)
        spread_pct = market_spread_pct(m)
        vol_24h = float(m.get("volume_24h_fp", 0) or 0)
        title = m.get("title", "")
        floor_strike = m.get("floor_strike")
        cap_strike = m.get("cap_strike")
        strike_type = m.get("strike_type", "between")
        status = (m.get("status") or "").lower() or None
        result = (m.get("result") or "").lower() or None
        last_price = m.get("last_price")
        if last_price is not None:
            try:
                last_price = float(last_price)
            except (TypeError, ValueError):
                last_price = None

        if floor_strike is not None:
            floor_strike = float(floor_strike)
        if cap_strike is not None:
            cap_strike = float(cap_strike)

        close_time = m.get("close_time", "")
        ct = None
        hours_left = None
        try:
            ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            hours_left = (ct - now).total_seconds() / 3600
        except (ValueError, AttributeError):
            pass

        if kalshi_status == "settled":
            filter_reason = "settled"
        else:
            filter_reason = None
            if ask_price <= 0:
                filter_reason = "no_ask"
            elif ask_size < 1:
                filter_reason = "no_ask_size"
            elif vol_24h < min_volume:
                filter_reason = "low_volume"
            elif ask_price < min_price or ask_price > max_price:
                filter_reason = "price_range"
            elif ct is None:
                filter_reason = "invalid_expiry"
            elif ct < cutoff:
                filter_reason = "expiry_too_soon"

        existing = session.execute(
            select(MarketSnapshot.filter_reason, MarketSnapshot.edge)
            .where(MarketSnapshot.ticker == ticker)
        ).one_or_none()

        old_reason = existing[0] if existing else None
        old_edge = existing[1] if existing else None

        new_edge = old_edge
        new_model_prob = None
        new_scored_at = None

        if filter_reason is not None:
            new_edge = None
            new_model_prob = None
            new_scored_at = None
        elif old_reason is not None:
            new_edge = None
            new_model_prob = None
            new_scored_at = None

        values = {
            "ticker": ticker,
            "series": series,
            "venue": venue,
            "title": title,
            "ask_price": ask_price,
            "ask_size": ask_size,
            "bid_price": bid_price,
            "mid_price": mid_price,
            "spread_pct": spread_pct,
            "volume_24h": vol_24h,
            "hours_to_expiry": hours_left,
            "expiry_time": ct,
            "floor_strike": floor_strike,
            "cap_strike": cap_strike,
            "strike_type": strike_type,
            "filter_reason": filter_reason,
            "edge": new_edge,
            "model_prob": new_model_prob,
            "scored_at": new_scored_at,
            "status": status,
            "result": result,
            "last_price": last_price,
            "discovered_at": now,
            "price_updated_at": now,
        }
        stmt = insert(MarketSnapshot).values(**values)
        update_set = {k: v for k, v in values.items() if k != "ticker"}
        # Settled-pass must NOT overwrite the score that was recorded while
        # this market was open — that's the data point we want to feed
        # Platt. score.py writes both model_prob and raw_model_prob; only
        # the open-pass should clear them here on filter transitions.
        if kalshi_status == "settled":
            for k in ("model_prob", "edge", "scored_at"):
                update_set.pop(k, None)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_=update_set)
        session.execute(stmt)
        count += 1
    return count


def _priority_order(series_list: list[str]) -> list[str]:
    """Sort series so highest-liquidity markets are fetched first."""
    high_priority = {"KXBTC", "KXETH"}
    mid_priority = {"KXSOL", "KXXRP"}
    rest = set(series_list)

    result = []
    for p in [high_priority, mid_priority]:
        for s in sorted(rest & p):
            result.append(s)
            rest.discard(s)
    result.extend(sorted(rest))
    return result


def discover_crypto(session: Session) -> None:
    """Discover Kalshi crypto markets for all enabled users.

    Collects unique series across all user configs, fetches Kalshi
    listings, and upserts them into market_snapshots.
    """
    configs = session.execute(
        select(CryptoConfig).where(CryptoConfig.enabled.is_(True))
    ).scalars().all()

    series_set: set[str] = set()
    min_volume = 999999
    max_price_val = 0.0
    min_price_val = 1.0
    min_hours = 0

    for cfg in configs:
        for s in (cfg.series_tickers or "").split(","):
            s = s.strip()
            if s:
                series_set.add(s)
        min_volume = min(min_volume, cfg.min_volume_24h)
        min_price_val = min(min_price_val, cfg.min_price)
        max_price_val = max(max_price_val, cfg.max_price)
        if min_hours == 0 or (cfg.min_hours_to_expiry > 0 and cfg.min_hours_to_expiry < min_hours):
            min_hours = cfg.min_hours_to_expiry

    if not series_set:
        return

    client = KalshiClient.public()
    series_list = _priority_order(list(series_set))

    count = _fetch_and_upsert(
        session, client, series_list, _VENUE_CRYPTO,
        min_volume=min_volume, min_price=min_price_val,
        max_price=max_price_val, min_hours_to_expiry=min_hours,
    )
    logger.info("Discover crypto: %d markets upserted from %d series", count, len(series_list))


def discover_climate(session: Session) -> None:
    """Discover Kalshi climate markets for all enabled users."""
    configs = session.execute(
        select(ClimateConfig).where(ClimateConfig.enabled.is_(True))
    ).scalars().all()

    series_set: set[str] = set()
    min_volume = 999999
    max_price_val = 0.0
    min_price_val = 1.0
    min_hours = 0

    for cfg in configs:
        for s in (cfg.series_tickers or "").split(","):
            s = s.strip()
            if s:
                series_set.add(s)
        min_volume = min(min_volume, cfg.min_volume_24h)
        min_price_val = min(min_price_val, cfg.min_price)
        max_price_val = max(max_price_val, cfg.max_price)
        if min_hours == 0 or (cfg.min_hours_to_expiry > 0 and cfg.min_hours_to_expiry < min_hours):
            min_hours = cfg.min_hours_to_expiry

    if not series_set:
        return

    client = KalshiClient.public()
    series_list = _priority_order(list(series_set))

    count = _fetch_and_upsert(
        session, client, series_list, _VENUE_CLIMATE,
        min_volume=min_volume, min_price=min_price_val,
        max_price=max_price_val, min_hours_to_expiry=min_hours,
    )
    logger.info("Discover climate: %d markets upserted from %d series", count, len(series_list))
