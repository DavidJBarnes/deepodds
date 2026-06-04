"""Shared utilities for Kalshi market scanning (crypto + climate)."""

import logging
from datetime import datetime, timedelta, timezone

from app.core.async_util import run_async
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("signaled", "placed", "filled")
HOURS_TO_YEARS = 1 / (365.25 * 24)


def market_ask(market: dict) -> float:
    return float(market.get("yes_ask_dollars", 0) or 0)


def market_bid(market: dict) -> float:
    return float(market.get("yes_bid_dollars") or 0)


def market_ask_size(market: dict) -> float:
    return float(market.get("yes_ask_size_fp", 0) or 0)


def market_mid(market: dict) -> float:
    bid = float(market.get("yes_bid_dollars", 0) or 0)
    ask = float(market.get("yes_ask_dollars", 0) or 0)
    if bid <= 0 or ask <= 0:
        return ask
    return (bid + ask) / 2


def market_spread_pct(market: dict) -> float:
    bid = float(market.get("yes_bid_dollars", 0) or 0)
    ask = float(market.get("yes_ask_dollars", 0) or 0)
    if bid <= 0 or ask <= 0:
        return 0.0
    return (ask - bid) / ask * 100 if ask > 0 else 0.0


def fetch_raw_markets(client: KalshiClient, series_ticker: str) -> dict | None:
    """Fetch raw Kalshi API response for one series ticker.

    Returns the full JSON dict from GET /markets?series_ticker=… or None
    on failure.  Callers populate the shared cache with the result so
    subsequent discover_markets calls within the same scan cycle skip
    redundant API round-trips.
    """
    try:
        return run_async(client.get_markets(series_ticker=series_ticker, limit=200))
    except Exception:
        logger.warning("Failed to fetch raw markets for series %s", series_ticker)
        return None


def discover_markets(
    client: KalshiClient,
    series_tickers: list[str],
    min_volume: int,
    min_price: float,
    max_price: float,
    min_hours_to_expiry: int,
    min_ask_size: int = 1,
    raw_data: dict[str, dict] | None = None,
) -> list[dict]:
    """Find markets where we could actually fill a buy order at a sensible price.

    If *raw_data* is supplied it is a ``{series_ticker: raw_api_json}``
    mapping — the Kalshi API call is skipped for any series present in the
    dict (the caller prepopulated it from the shared market_data cache or
    a parallel pre-fetch).
    """
    raw_data = raw_data or {}
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=min_hours_to_expiry)
    eligible = []

    for series in series_tickers:
        data = raw_data.get(series)
        if data is None:
            try:
                data = run_async(client.get_markets(series_ticker=series, limit=200))
            except Exception:
                logger.warning("Failed to fetch markets for series %s", series)
                continue

        for m in data.get("markets", []):
            vol_24h = float(m.get("volume_24h_fp", 0) or 0)
            if vol_24h < min_volume:
                continue

            ask = market_ask(m)
            if ask < min_price or ask > max_price:
                continue

            if market_ask_size(m) < min_ask_size:
                continue

            close_time = m.get("close_time", "")
            try:
                ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if ct < cutoff:
                continue

            m["_series_ticker"] = series
            m["_close_dt"] = ct
            m["_ask"] = ask
            m["_bid"] = market_bid(m)
            m["_mid"] = market_mid(m)
            m["_spread_pct"] = market_spread_pct(m)
            eligible.append(m)

    eligible.sort(key=lambda m: float(m.get("volume_24h_fp", 0) or 0), reverse=True)
    return eligible


def kelly_count(
    edge: float, market_price: float, bankroll_cents: float,
    max_contracts: int, max_cost: float,
) -> int:
    """Quarter-Kelly position sizing for binary YES bets."""
    if market_price <= 0 or edge <= 0:
        return 0
    kelly = edge / (1 - market_price)
    quarter_kelly = kelly * 0.25
    bankroll_dollars = bankroll_cents / 100
    count = int(quarter_kelly * bankroll_dollars / market_price)
    count = min(count, max_contracts)
    if market_price * count > max_cost:
        count = int(max_cost / market_price)
    return max(count, 0)


def read_balance_cache(user_id: str) -> float | None:
    """Return portfolio_cents from the scheduler-written balance cache, or None."""
    import json as _json
    from pathlib import Path

    try:
        path = Path(f"/tmp/kalshi_balance_{user_id}.json")
        if not path.exists():
            return None
        data = _json.loads(path.read_text())
        return float(data.get("cash_cents", 0))
    except Exception:
        return None


def check_spread_filter(
    edge: float, spread_pct: float, mid: float, bid: float, stop_loss_pct: float,
    ticker: str,
) -> bool:
    """Return True if the market passes the bid-ask spread filter.

    Edge must exceed half the spread (cost of round-trip friction).
    Entering at mid then exiting at bid would lose spread/2 — reject if
    that instant loss would exceed the stop-loss threshold.
    """
    if spread_pct <= 0:
        return True
    if edge * 100 < spread_pct / 2:
        logger.info("Skipping %s: edge=%.1f%% < spread/2=%.1f%%", ticker, edge * 100, spread_pct / 2)
        return False
    # When stop_loss_pct == 0 ("hold to resolution" mode), the exit-at-bid
    # check is irrelevant — we don't exit on bid moves anyway.
    if stop_loss_pct > 0:
        loss_if_exit_at_bid = (mid - bid) / mid * 100 if mid > 0 else 0
        if loss_if_exit_at_bid > stop_loss_pct:
            logger.info("Skipping %s: exit-at-bid loss %.1f%% > stop %.1f%%", ticker, loss_if_exit_at_bid, stop_loss_pct)
            return False
    return True
