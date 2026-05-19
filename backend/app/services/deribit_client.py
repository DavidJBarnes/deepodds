import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.deribit.com/api/v2/public"

MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

EXPIRY_RE = re.compile(r"(\d{1,2})([A-Z]{3})(\d{2})")


def _parse_expiry(expiry_str: str) -> datetime | None:
    m = EXPIRY_RE.match(expiry_str)
    if not m:
        return None
    day, mon, yr = int(m.group(1)), MONTH_MAP.get(m.group(2)), 2000 + int(m.group(3))
    if not mon:
        return None
    return datetime(yr, mon, day, 8, 0, tzinfo=timezone.utc)


def _parse_instrument(name: str) -> dict | None:
    parts = name.split("-")
    if len(parts) != 4:
        return None
    return {
        "currency": parts[0],
        "expiry_str": parts[1],
        "expiry_dt": _parse_expiry(parts[1]),
        "strike": float(parts[2]),
        "option_type": parts[3],
    }


async def _get(endpoint: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{BASE_URL}/{endpoint}", params=params or {})
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", data)


async def get_spot_price(currency: str = "BTC") -> float:
    result = await _get("get_index_price", {"index_name": f"{currency.lower()}_usd"})
    return result["index_price"]


async def get_dvol(currency: str = "BTC") -> float | None:
    import time
    now_ms = int(time.time() * 1000)
    result = await _get("get_volatility_index_data", {
        "currency": currency,
        "resolution": 3600,
        "start_timestamp": now_ms - 3600_000,
        "end_timestamp": now_ms,
    })
    candles = result.get("data", [])
    if candles:
        return candles[-1][4]
    return None


async def get_iv_surface(currency: str = "BTC") -> dict:
    """Fetch all option IVs grouped by expiry. Returns {expiry_str: {atm_iv, spot, options}}."""
    summaries = await _get("get_book_summary_by_currency", {
        "currency": currency,
        "kind": "option",
    })
    if not summaries:
        return {}

    spot = summaries[0].get("underlying_price", 0)

    by_expiry: dict[str, list] = defaultdict(list)
    for s in summaries:
        parsed = _parse_instrument(s["instrument_name"])
        if not parsed or s.get("mark_iv", 0) <= 0:
            continue
        by_expiry[parsed["expiry_str"]].append({
            "strike": parsed["strike"],
            "type": parsed["option_type"],
            "mark_iv": s["mark_iv"],
            "expiry_dt": parsed["expiry_dt"],
        })

    result = {}
    for expiry_str, options in by_expiry.items():
        calls = [o for o in options if o["type"] == "C"]
        if not calls:
            continue
        atm = min(calls, key=lambda o: abs(o["strike"] - spot))
        result[expiry_str] = {
            "atm_iv": atm["mark_iv"],
            "atm_strike": atm["strike"],
            "expiry_dt": atm["expiry_dt"],
            "spot": spot,
            "options": options,
        }

    return result


async def get_iv_for_expiry(currency: str, target_expiry: datetime) -> tuple[float, float]:
    """Get the best IV and spot price for a target expiry. Returns (iv_decimal, spot)."""
    surface = await get_iv_surface(currency)
    if not surface:
        dvol = await get_dvol(currency)
        spot = await get_spot_price(currency)
        return ((dvol or 40.0) / 100.0, spot)

    spot = next(iter(surface.values()))["spot"]

    best_expiry = None
    best_dist = float("inf")
    for _key, data in surface.items():
        if data["expiry_dt"] is None:
            continue
        dist = abs((data["expiry_dt"] - target_expiry).total_seconds())
        if dist < best_dist:
            best_dist = dist
            best_expiry = data

    if best_expiry:
        return (best_expiry["atm_iv"] / 100.0, spot)

    dvol = await get_dvol(currency)
    return ((dvol or 40.0) / 100.0, spot)
