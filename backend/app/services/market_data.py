"""Thread-safe TTL cache shared between scanner refresh tasks and scan functions.

Refresh tasks (async, event loop) populate the cache. Scan functions (sync,
thread pool) read it. Every read falls back to a direct fetch on cache miss
so the first scan cycle after startup behaves identically to the old sequential
code — the cache is a pure optimisation, not a correctness requirement.
"""

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()

TTL_PRICES = 30          # spot prices
TTL_STATS = 30           # 48 h vol / drift per symbol
TTL_MARKETS = 60         # Kalshi raw market listing per series ticker
TTL_VOL_BASELINE = 300   # 7 d realised vol baseline per symbol (changes slowly)
TTL_FORECAST = 1800      # weather forecast data (matches weather_client built-in cache)


def get(key: str, max_age: float | None = None) -> Any | None:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if max_age is not None and time.time() - ts > max_age:
            return None
        return value


def set(key: str, value: Any) -> None:
    with _lock:
        _cache[key] = (time.time(), value)


def clear() -> None:
    with _lock:
        _cache.clear()
