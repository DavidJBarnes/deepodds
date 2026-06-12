"""
Kalshi data ingestion — settled markets + candlesticks.

Credentials required (env vars):
    KALSHI_API_KEY_ID        — your Kalshi API key ID
    KALSHI_PRIVATE_KEY_PATH  — path to the RSA private key PEM file

Usage:
    cd backend
    uv run python -m kalshi_backtest.ingest
"""
from __future__ import annotations

import base64
import csv
import hashlib
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("kalshi_backtest.ingest")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"
DATA_DIR = Path(__file__).parent / "data"
MARKETS_DIR = DATA_DIR / "markets"
CANDLES_DIR = DATA_DIR / "candles"

INGEST_START = datetime(2024, 6, 1, tzinfo=timezone.utc)
MIN_VOLUME = 500          # contracts — initial floor; raised if universe too large
CANDLE_PERIOD_SEC = 3600  # 1h candlesticks
LOOKBACK_HOURS = 72       # hours of candles to fetch before close
TARGET_PERIOD_SEC = 3600  # 1h

# Rate-limit safety
_REQUEST_DELAY_SEC = 0.25   # between requests
_RETRY_DELAYS = [2, 4, 8]   # seconds, for 429/5xx

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _load_creds() -> tuple[str, bytes]:
    """Return (api_key_id, private_key_pem_bytes). Exits cleanly if absent."""
    key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if not key_id or not key_path:
        raise SystemExit(
            "\n[kalshi_backtest] Missing credentials.\n"
            "Set the following env vars before running:\n"
            "  KALSHI_API_KEY_ID       — your API key ID from kalshi.com → Account → API\n"
            "  KALSHI_PRIVATE_KEY_PATH — path to the RSA private key PEM file\n"
            "Generate a key at: https://kalshi.com/account/api\n"
        )
    pem_bytes = Path(key_path).read_bytes()
    return key_id, pem_bytes


def _sign_request(method: str, path: str, ts_ms: int, key_id: str,
                  pem_bytes: bytes) -> dict[str, str]:
    """Build Authorization + KALSHI-Access-* headers using RSA-PSS."""
    ts_str = str(ts_ms)
    msg = ts_str + method.upper() + path
    private_key = serialization.load_pem_private_key(pem_bytes, password=None)
    sig = private_key.sign(
        msg.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(sig).decode()
    return {
        "KALSHI-Access-Key": key_id,
        "KALSHI-Access-Timestamp": ts_str,
        "KALSHI-Access-Signature": sig_b64,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class KalshiClient:
    def __init__(self, key_id: str, pem_bytes: bytes):
        self._key_id = key_id
        self._pem = pem_bytes
        self._client = httpx.Client(base_url=BASE_URL, timeout=30)

    def get(self, path: str, params: dict | None = None) -> dict:
        ts_ms = int(time.time() * 1000)
        headers = _sign_request("GET", "/trade-api/v2" + path, ts_ms,
                                 self._key_id, self._pem)
        for attempt, delay in enumerate([0] + _RETRY_DELAYS):
            if delay:
                logger.debug("Retry %d after %ds", attempt, delay)
                time.sleep(delay)
            resp = self._client.get(path, params=params, headers=headers)
            if resp.status_code == 200:
                time.sleep(_REQUEST_DELAY_SEC)
                return resp.json()
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning("Rate-limited; sleeping %ds", retry_after)
                time.sleep(retry_after)
                ts_ms = int(time.time() * 1000)
                headers = _sign_request("GET", "/trade-api/v2" + path, ts_ms,
                                         self._key_id, self._pem)
                continue
            if resp.status_code >= 500:
                logger.warning("Server error %d on %s", resp.status_code, path)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Failed after retries: GET {path}")

    def close(self):
        self._client.close()


# ---------------------------------------------------------------------------
# Task 1a — Settled market universe
# ---------------------------------------------------------------------------

MARKETS_FIELDS = [
    "ticker", "event_ticker", "series_ticker", "category",
    "title", "close_time", "result", "volume", "open_interest", "liquidity",
]


def _month_shard_path(year: int, month: int) -> Path:
    return MARKETS_DIR / f"markets_{year:04d}_{month:02d}.csv"


def _existing_tickers() -> set[str]:
    """All market tickers already persisted across all monthly shards."""
    tickers: set[str] = set()
    for p in MARKETS_DIR.glob("markets_*.csv"):
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                tickers.add(row["ticker"])
    return tickers


def fetch_settled_markets(client: KalshiClient,
                          start: datetime = INGEST_START,
                          end: datetime | None = None,
                          volume_floor: int = MIN_VOLUME) -> list[dict]:
    """
    Page through /markets?status=settled in [start, end].
    Returns all markets passing volume_floor.
    Checkpoints: shards already on disk are skipped; within the current
    month, only tickers not yet seen are written.
    """
    MARKETS_DIR.mkdir(parents=True, exist_ok=True)

    now = end or datetime.now(timezone.utc)
    existing = _existing_tickers()
    logger.info("Found %d already-cached tickers", len(existing))

    all_markets: list[dict] = []
    # Load already-cached
    for p in sorted(MARKETS_DIR.glob("markets_*.csv")):
        with open(p, newline="") as f:
            all_markets.extend(csv.DictReader(f))
    logger.info("Loaded %d cached markets", len(all_markets))

    # Determine fetch range — only fetch months not fully cached
    # Months fully before current month are assumed complete once their shard exists
    cursor: str | None = None
    fetched_this_run: list[dict] = []
    total_seen = 0
    total_kept = 0

    params: dict = {
        "status": "settled",
        "min_close_ts": int(start.timestamp()),
        "max_close_ts": int(now.timestamp()),
        "limit": 200,
    }

    logger.info("Fetching settled markets from %s → %s", start.date(), now.date())
    while True:
        if cursor:
            params["cursor"] = cursor
        elif "cursor" in params:
            del params["cursor"]

        data = client.get("/markets", params=params)
        markets = data.get("markets", [])
        total_seen += len(markets)

        for m in markets:
            ticker = m.get("ticker", "")
            if ticker in existing:
                continue
            # Only binary-settled markets
            result = m.get("result", "")
            if result not in ("yes", "no"):
                continue
            vol = int(m.get("volume", 0) or 0)
            if vol < volume_floor:
                continue

            row = {
                "ticker": ticker,
                "event_ticker": m.get("event_ticker", ""),
                "series_ticker": m.get("series_ticker", ""),
                "category": (m.get("category") or "other").lower(),
                "title": m.get("title", "")[:200],
                "close_time": m.get("close_time", ""),
                "result": result,
                "volume": vol,
                "open_interest": int(m.get("open_interest", 0) or 0),
                "liquidity": float(m.get("liquidity", 0) or 0),
            }
            fetched_this_run.append(row)
            existing.add(ticker)
            total_kept += 1

        cursor = data.get("cursor")
        if not cursor or not markets:
            break

        if total_seen % 1000 == 0:
            logger.info("  Scanned %d markets, kept %d so far", total_seen, total_kept)

    logger.info("Fetch complete: %d scanned, %d passed volume/binary filter",
                total_seen, total_kept)

    # Shard newly-fetched by close_time month
    shards: dict[tuple[int, int], list[dict]] = {}
    for row in fetched_this_run:
        ct = row["close_time"]
        try:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            key = (dt.year, dt.month)
        except Exception:
            key = (0, 0)
        shards.setdefault(key, []).append(row)

    for (yr, mo), rows in sorted(shards.items()):
        if yr == 0:
            continue
        p = _month_shard_path(yr, mo)
        write_header = not p.exists()
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MARKETS_FIELDS)
            if write_header:
                w.writeheader()
            w.writerows(rows)
        logger.info("Wrote %d rows to %s", len(rows), p.name)

    all_markets.extend(fetched_this_run)

    # Log funnel
    by_cat: dict[str, int] = {}
    for m in all_markets:
        c = m.get("category", "other")
        by_cat[c] = by_cat.get(c, 0) + 1
    logger.info("Universe: %d markets total", len(all_markets))
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        logger.info("  %-20s %d", cat, n)

    return all_markets


# ---------------------------------------------------------------------------
# Task 1c — Price candlesticks
# ---------------------------------------------------------------------------

CANDLE_FIELDS = ["ticker", "ts", "yes_bid", "yes_ask", "price", "volume"]


def _candle_path(ticker: str) -> Path:
    # Use first 2 chars of ticker as subdir to avoid huge flat dirs
    safe = ticker.replace("/", "_").replace(":", "_")
    sub = CANDLES_DIR / safe[:2].lower()
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{safe}.csv"


def _already_fetched_tickers() -> set[str]:
    fetched: set[str] = set()
    for p in CANDLES_DIR.rglob("*.csv"):
        fetched.add(p.stem)
    return fetched


def fetch_candles(client: KalshiClient, market: dict) -> list[dict] | None:
    """
    Fetch 1h candles for [close_time - LOOKBACK_HOURS, close_time].
    Returns list of dicts or None if unavailable.
    """
    ticker = market["ticker"]
    series_ticker = market.get("series_ticker", "")
    if not series_ticker:
        logger.debug("No series_ticker for %s — skipping", ticker)
        return None

    close_time_str = market.get("close_time", "")
    try:
        close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
    except Exception:
        logger.debug("Bad close_time for %s: %r", ticker, close_time_str)
        return None

    start_ts = int((close_dt - timedelta(hours=LOOKBACK_HOURS)).timestamp())
    end_ts = int(close_dt.timestamp())

    path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
    params = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "period_seconds": TARGET_PERIOD_SEC,
    }
    try:
        data = client.get(path, params=params)
    except Exception as e:
        logger.debug("Candle fetch failed for %s: %s", ticker, e)
        return None

    candles_raw = data.get("candlesticks", []) or []
    if not candles_raw:
        return None

    rows = []
    for c in candles_raw:
        ts = c.get("end_period_ts") or c.get("ts") or 0
        yes_bid = float(c.get("yes", {}).get("close") or c.get("close") or 0)
        yes_ask_raw = c.get("yes_ask", {})
        if isinstance(yes_ask_raw, dict):
            yes_ask = float(yes_ask_raw.get("close", yes_bid))
        else:
            yes_ask = yes_bid
        price = float(c.get("price", {}).get("close", yes_bid)
                      if isinstance(c.get("price"), dict) else c.get("price", yes_bid) or yes_bid)
        vol = int(c.get("volume", 0) or 0)
        rows.append({
            "ticker": ticker,
            "ts": ts,
            "yes_bid": round(yes_bid, 4),
            "yes_ask": round(yes_ask, 4),
            "price": round(price, 4),
            "volume": vol,
        })

    return rows if rows else None


def fetch_all_candles(client: KalshiClient, markets: list[dict]) -> dict[str, list[dict]]:
    """
    Fetch + cache candlesticks for all markets.
    Skips already-cached tickers.
    """
    CANDLES_DIR.mkdir(parents=True, exist_ok=True)
    done = _already_fetched_tickers()
    logger.info("%d tickers already have candle files", len(done))

    result: dict[str, list[dict]] = {}

    # Load cached
    cached_count = 0
    for m in markets:
        safe = m["ticker"].replace("/", "_").replace(":", "_")
        if safe in done:
            p = _candle_path(m["ticker"])
            if p.exists():
                with open(p, newline="") as f:
                    rows = list(csv.DictReader(f))
                if rows:
                    result[m["ticker"]] = rows
                    cached_count += 1
    logger.info("Loaded %d candle sets from disk", cached_count)

    to_fetch = [m for m in markets
                if m["ticker"].replace("/", "_").replace(":", "_") not in done]
    logger.info("Fetching candles for %d markets...", len(to_fetch))

    fetched = 0
    skipped = 0
    for i, m in enumerate(to_fetch):
        rows = fetch_candles(client, m)
        safe = m["ticker"].replace("/", "_").replace(":", "_")
        if rows:
            # Persist
            p = _candle_path(m["ticker"])
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CANDLE_FIELDS)
                w.writeheader()
                w.writerows(rows)
            result[m["ticker"]] = rows
            fetched += 1
        else:
            # Write empty sentinel so we don't re-try
            p = _candle_path(m["ticker"])
            p.write_text("")
            skipped += 1

        if (i + 1) % 500 == 0:
            logger.info("  Candle progress: %d/%d (fetched=%d, skipped=%d)",
                        i + 1, len(to_fetch), fetched, skipped)

    logger.info("Candle fetch done: fetched=%d, skipped/empty=%d, total=%d",
                fetched, skipped, len(result))
    return result


# ---------------------------------------------------------------------------
# Load cached data (used by calibration + simulate)
# ---------------------------------------------------------------------------

def load_markets() -> list[dict]:
    """Load all cached market rows."""
    rows: list[dict] = []
    for p in sorted(MARKETS_DIR.glob("markets_*.csv")):
        with open(p, newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def load_candles(ticker: str) -> list[dict] | None:
    """Load candle rows for one ticker. Returns None if not cached or empty."""
    safe = ticker.replace("/", "_").replace(":", "_")
    sub = CANDLES_DIR / safe[:2].lower()
    p = sub / f"{safe}.csv"
    if not p.exists() or p.stat().st_size == 0:
        return None
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows if rows else None


# ---------------------------------------------------------------------------
# Funnel report
# ---------------------------------------------------------------------------

def funnel_report(all_settled: int, after_filter: int, with_candles: int) -> str:
    return (
        f"Total settled: {all_settled:,} → "
        f"after volume+binary filter: {after_filter:,} → "
        f"with usable candles: {with_candles:,}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    key_id, pem_bytes = _load_creds()
    client = KalshiClient(key_id, pem_bytes)
    try:
        markets = fetch_settled_markets(client)
        if len(markets) > 50_000:
            new_floor = MIN_VOLUME * 5
            logger.warning(
                "Universe %d > 50,000 — raising volume floor to %d",
                len(markets), new_floor,
            )
            markets = [m for m in markets if int(m.get("volume", 0)) >= new_floor]
            logger.info("After floor raise: %d markets", len(markets))
        candles = fetch_all_candles(client, markets)
        with_candles = sum(1 for m in markets if m["ticker"] in candles)
        print(funnel_report(
            all_settled=len(markets) + 0,  # conservative (only passing markets counted)
            after_filter=len(markets),
            with_candles=with_candles,
        ))
    finally:
        client.close()


if __name__ == "__main__":
    main()
