import logging
import math
import time
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

# Coordinates point to the NWS climate-report station for each city (the
# CLI code Kalshi resolves on), not the city center. For coastal/marine
# cities (SEA, SFO, LAX) and cities where the official station is at a
# specific airport (e.g., Houston uses Hobby/KHOU not Intercontinental,
# Chicago uses Midway/KMDW not O'Hare), the city-center coordinates were
# producing forecasts a few degrees off the resolution value.
CITY_COORDS = {
    "NYC": (40.7794, -73.9692),    # KNYC Central Park
    "CHI": (41.7868, -87.7522),    # KMDW Chicago Midway
    "MIA": (25.7959, -80.2870),    # KMIA Miami International
    "LA": (33.9425, -118.4081),    # KLAX (alias)
    "LAX": (33.9425, -118.4081),   # KLAX Los Angeles International
    "HOU": (29.6454, -95.2789),    # KHOU Houston Hobby
    "PHX": (33.4373, -112.0078),   # KPHX Sky Harbor
    "ATL": (33.6407, -84.4277),    # KATL Hartsfield-Jackson
    "BOS": (42.3656, -71.0096),    # KBOS Logan
    "DAL": (32.8998, -97.0403),    # KDFW Dallas/Fort Worth
    "DC": (38.8512, -77.0402),     # KDCA Reagan National
    "DEN": (39.8561, -104.6737),   # KDEN Denver International
    "LV": (36.0840, -115.1537),    # KLAS Harry Reid
    "MIN": (44.8848, -93.2223),    # KMSP Minneapolis-St. Paul
    "NOLA": (29.9934, -90.2580),   # KMSY Louis Armstrong
    "OKC": (35.3931, -97.6007),    # KOKC Will Rogers World
    "SATX": (29.5337, -98.4698),   # KSAT San Antonio International
    "SEA": (47.4502, -122.3088),   # KSEA Sea-Tac
    "SFO": (37.6189, -122.3750),   # KSFO San Francisco International
    "AUS": (30.1945, -97.6699),    # KAUS Austin-Bergstrom
    "PHIL": (39.8729, -75.2437),   # KPHL Philadelphia International
}

SUPPORTED_CITIES = list(CITY_COORDS.keys())

KIND_DAILY_MAX = "daily_max"
KIND_DAILY_MIN = "daily_min"
KIND_PRECIP = "precipitation"

_DAILY_VAR = {
    KIND_DAILY_MAX: "temperature_2m_max",
    KIND_DAILY_MIN: "temperature_2m_min",
    KIND_PRECIP: "precipitation_sum",
}

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 1800


def _cache_key(fn: str, *args) -> str:
    return f"{fn}:{':'.join(str(a) for a in args)}"


def _get_cached(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _set_cached(key: str, value):
    _cache[key] = (time.time(), value)


KALSHI_SERIES_MAP = {
    "KXHIGHTATL": ("ATL", KIND_DAILY_MAX),
    "KXHIGHTBOS": ("BOS", KIND_DAILY_MAX),
    "KXHIGHTDAL": ("DAL", KIND_DAILY_MAX),
    "KXHIGHTDC": ("DC", KIND_DAILY_MAX),
    "KXHIGHTEMPDEN": ("DEN", KIND_DAILY_MAX),
    "KXHIGHTHOU": ("HOU", KIND_DAILY_MAX),
    "KXHIGHTLV": ("LV", KIND_DAILY_MAX),
    "KXHIGHTMIN": ("MIN", KIND_DAILY_MAX),
    "KXHIGHTNOLA": ("NOLA", KIND_DAILY_MAX),
    "KXHIGHTOKC": ("OKC", KIND_DAILY_MAX),
    "KXHIGHTPHX": ("PHX", KIND_DAILY_MAX),
    "KXHIGHTSATX": ("SATX", KIND_DAILY_MAX),
    "KXHIGHTSEA": ("SEA", KIND_DAILY_MAX),
    "KXHIGHTSFO": ("SFO", KIND_DAILY_MAX),
    "KXLOWTATL": ("ATL", KIND_DAILY_MIN),
    "KXLOWTAUS": ("AUS", KIND_DAILY_MIN),
    "KXLOWTBOS": ("BOS", KIND_DAILY_MIN),
    "KXLOWTCHI": ("CHI", KIND_DAILY_MIN),
    "KXLOWTDAL": ("DAL", KIND_DAILY_MIN),
    "KXLOWTDC": ("DC", KIND_DAILY_MIN),
    "KXLOWTDEN": ("DEN", KIND_DAILY_MIN),
    "KXLOWTHOU": ("HOU", KIND_DAILY_MIN),
    "KXLOWTLAX": ("LAX", KIND_DAILY_MIN),
    "KXLOWTLV": ("LV", KIND_DAILY_MIN),
    "KXLOWTMIA": ("MIA", KIND_DAILY_MIN),
    "KXLOWTMIN": ("MIN", KIND_DAILY_MIN),
    "KXLOWTNOLA": ("NOLA", KIND_DAILY_MIN),
    "KXLOWTNYC": ("NYC", KIND_DAILY_MIN),
    "KXLOWTOKC": ("OKC", KIND_DAILY_MIN),
    "KXLOWTPHIL": ("PHIL", KIND_DAILY_MIN),
    "KXLOWTPHX": ("PHX", KIND_DAILY_MIN),
    "KXLOWTSATX": ("SATX", KIND_DAILY_MIN),
    "KXLOWTSEA": ("SEA", KIND_DAILY_MIN),
    "KXLOWTSFO": ("SFO", KIND_DAILY_MIN),
    "KXRAINNYC": ("NYC", KIND_PRECIP),
    "KXRAINCHIM": ("CHI", KIND_PRECIP),
    "KXRAINMIAM": ("MIA", KIND_PRECIP),
    "KXRAINMIA": ("MIA", KIND_PRECIP),
    "KXRAINHOU": ("HOU", KIND_PRECIP),
    "KXRAINHOUM": ("HOU", KIND_PRECIP),
    "KXRAINLAXM": ("LAX", KIND_PRECIP),
    "KXRAINSEAM": ("SEA", KIND_PRECIP),
    "KXRAINSEA": ("SEA", KIND_PRECIP),
    "KXRAINSFOM": ("SFO", KIND_PRECIP),
    "KXRAINDALM": ("DAL", KIND_PRECIP),
    "KXRAINDENM": ("DEN", KIND_PRECIP),
    "KXRAINAUSM": ("AUS", KIND_PRECIP),
}

_SERIES_PREFIXES = [
    ("KXHIGHTEMP", KIND_DAILY_MAX),
    ("KXHIGHT", KIND_DAILY_MAX),
    ("KXLOWT", KIND_DAILY_MIN),
    ("KXRAIN", KIND_PRECIP),
]


def series_to_city_kind(series_ticker: str) -> tuple[str, str] | None:
    """Map a Kalshi climate series ticker to (city, kind).

    kind ∈ {"daily_max", "daily_min", "precipitation"} — the underlying
    quantity that the market resolves on.
    """
    ticker = series_ticker.upper()
    entry = KALSHI_SERIES_MAP.get(ticker)
    if entry:
        return entry

    for prefix, kind in _SERIES_PREFIXES:
        if ticker.startswith(prefix):
            suffix = ticker[len(prefix):].rstrip("M")
            if suffix in CITY_COORDS:
                return (suffix, kind)
    return None


def parse_event_date(event_ticker: str) -> date | None:
    """Extract the resolution date from a Kalshi event ticker.

    Example: 'KXHIGHTPHX-26MAY29' -> date(2026, 5, 29).
    """
    if not event_ticker:
        return None
    parts = event_ticker.split("-")
    if len(parts) < 2:
        return None
    s = parts[1].upper()
    if len(s) < 6:
        return None
    try:
        year = 2000 + int(s[:2])
        month = _MONTHS.get(s[2:5])
        day = int(s[5:7])
        if month is None:
            return None
        return date(year, month, day)
    except (ValueError, KeyError):
        return None


async def get_forecast_daily_value(
    city: str, kind: str, target_date: date
) -> float | None:
    """Return the forecasted daily max/min/precip for a specific local date.

    Returns Fahrenheit for temps, inches for precipitation. None if the date is
    out of forecast range (16 days ahead) or the API call fails.
    """
    coords = CITY_COORDS.get(city.upper())
    if not coords:
        return None
    daily_var = _DAILY_VAR.get(kind)
    if not daily_var:
        return None

    today = datetime.now(timezone.utc).date()
    days_ahead = (target_date - today).days
    if days_ahead < 0 or days_ahead > 14:
        return None

    cache_k = _cache_key("daily_fcst", city, kind, target_date.isoformat())
    cached = _get_cached(cache_k)
    if cached is not None:
        return cached

    lat, lon = coords
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": daily_var,
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
    }
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("Forecast fetch failed for %s/%s/%s", city, kind, target_date)
            return None

    values = data.get("daily", {}).get(daily_var, [])
    if not values or values[0] is None:
        return None
    value = float(values[0])
    _set_cached(cache_k, value)
    return value


async def get_daily_extreme_history(
    city: str, kind: str, days: int = 365
) -> list[float] | None:
    """Fetch historical daily max/min/precip values for a city."""
    coords = CITY_COORDS.get(city.upper())
    if not coords:
        return None
    daily_var = _DAILY_VAR.get(kind)
    if not daily_var:
        return None

    cache_k = _cache_key("daily_hist", city, kind, days)
    cached = _get_cached(cache_k)
    if cached is not None:
        return cached

    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days)
    lat, lon = coords
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": daily_var,
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "wind_speed_unit": "mph",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                "https://archive-api.open-meteo.com/v1/archive", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("Daily history fetch failed for %s/%s", city, kind)
            return None

    raw = data.get("daily", {}).get(daily_var, [])
    values = [float(v) for v in raw if v is not None]
    if len(values) < 30:
        return None
    _set_cached(cache_k, values)
    return values


async def get_daily_extreme_vol(
    city: str, kind: str, days: int = 180
) -> float | None:
    """Stddev of day-to-day changes in the daily extreme (in native units).

    This is a proxy for forecast-error sigma at a 1-day horizon. It overstates
    true forecast uncertainty (NWP forecasts beat naive persistence), so the
    resulting probabilities are pulled toward 50% — conservative.
    """
    values = await get_daily_extreme_history(city, kind, days=days)
    if not values or len(values) < 30:
        return None
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    mean_d = sum(diffs) / len(diffs)
    var = sum((d - mean_d) ** 2 for d in diffs) / (len(diffs) - 1)
    return math.sqrt(var)
