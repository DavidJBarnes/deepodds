"""
Kalshi data ingestion — settled markets + candlesticks.

Markets are partitioned into two API tiers:
  - Historical  (settled before /historical/cutoff): GET /historical/markets
  - Live        (settled after cutoff):               GET /markets

Candlesticks follow the same split:
  - Historical: GET /historical/markets/{ticker}/candlesticks
  - Live:       GET /series/{series}/markets/{ticker}/candlesticks

Both tiers are fetched transparently; the rest of the pipeline sees one merged list.

Credentials required (env vars):
    KALSHI_API_KEY_ID        — your Kalshi API key ID
    KALSHI_PRIVATE_KEY_PATH  — path to the RSA private key PEM file
"""
from __future__ import annotations

import base64
import csv
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("kalshi_backtest.ingest")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
_API_PATH_PREFIX = "/trade-api/v2"
HIST_PREFIX = "/historical"      # relative to BASE_URL; no trailing slash

DATA_DIR = Path(__file__).parent / "data"
MARKETS_DIR = DATA_DIR / "markets"
CANDLES_DIR = DATA_DIR / "candles"

INGEST_START = datetime(2024, 6, 1, tzinfo=timezone.utc)
MIN_VOLUME = 500          # contracts — initial floor; raised if universe too large
LOOKBACK_HOURS = 72       # hours of candles to fetch before close
TARGET_PERIOD_MIN = 60    # 1h in minutes (Kalshi period_interval is in minutes)

# Rate-limit safety
_REQUEST_DELAY_SEC = 0.25   # between successful requests
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
        )
    pem_bytes = Path(key_path).read_bytes()
    return key_id, pem_bytes


def _sign_request(method: str, path: str, ts_ms: int, key_id: str,
                  pem_bytes: bytes) -> dict[str, str]:
    """Build KALSHI-ACCESS-* headers using RSA-PSS.

    Signed message: timestamp_ms + METHOD_UPPER + /trade-api/v2 + path_suffix.
    The full /trade-api/v2 prefix must be present — Kalshi 401s without it.
    """
    ts_str = str(ts_ms)
    full_path = path if path.startswith(_API_PATH_PREFIX) else _API_PATH_PREFIX + path
    msg = ts_str + method.upper() + full_path
    private_key = serialization.load_pem_private_key(pem_bytes, password=None)
    sig = private_key.sign(
        msg.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(sig).decode()
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts_str,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "Content-Type": "application/json",
        "Accept": "application/json",
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
        headers = _sign_request("GET", path, ts_ms, self._key_id, self._pem)
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
                headers = _sign_request("GET", path, ts_ms, self._key_id, self._pem)
                continue
            if resp.status_code >= 500:
                logger.warning("Server error %d on %s", resp.status_code, path)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Failed after retries: GET {path}")

    def close(self):
        self._client.close()


# ---------------------------------------------------------------------------
# Historical tier — cutoff discovery
# ---------------------------------------------------------------------------

def fetch_historical_cutoff(client: KalshiClient) -> datetime:
    """
    Return the UTC datetime that separates the historical API tier from live.

    Markets settled *before* this timestamp come from GET /historical/markets.
    Markets settled *after* it come from GET /markets (live window, ~3 months).
    """
    data = client.get(f"{HIST_PREFIX}/cutoff")
    raw = (data.get("market_settled_ts")
           or data.get("cutoff_ts")
           or data.get("cutoff"))
    if raw is None:
        raise RuntimeError(f"Unexpected /historical/cutoff response shape: {data!r}")
    if isinstance(raw, str):
        cutoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        cutoff = datetime.fromtimestamp(int(raw), tz=timezone.utc)
    logger.info("Historical cutoff: %s", cutoff.isoformat())
    return cutoff


# ---------------------------------------------------------------------------
# Market universe
# ---------------------------------------------------------------------------

MARKETS_FIELDS = [
    "ticker", "event_ticker", "series_ticker", "category",
    "title", "close_time", "result", "volume", "open_interest", "liquidity",
]

# Best-effort prefix → category for tickers where Kalshi omits the field
_TICKER_PREFIX_TO_CATEGORY: dict[str, str] = {
    "KXNBA": "sports",        "KXNFL": "sports",      "KXMLB": "sports",
    "KXNHL": "sports",        "KXNCAAF": "sports",    "KXNCAAB": "sports",
    "KXSOCCER": "sports",     "KXMMA": "sports",      "KXTENNIS": "sports",
    "KXUFC": "sports",        "KXGOLF": "sports",     "KXNASCAR": "sports",
    "KXMLBHRR": "sports",     "KXMLBTB": "sports",
    "KXMVESPORTS": "sports",  "KXMVECROSS": "sports",
    "KXBTC": "financials",    "KXETH": "financials",  "KXSPY": "financials",
    "KXNASDAQ": "financials", "KXSP": "financials",   "KXDOW": "financials",
    "KXGOLD": "financials",   "KXOIL": "financials",
    "KXFED": "economics",     "KXFOMC": "economics",  "KXCPI": "economics",
    "KXGDP": "economics",     "KXUNEMPLOYMENT": "economics", "KXJOBS": "economics",
    "KXPRES": "politics",     "KXELECTION": "politics", "KXCONGRESS": "politics",
    "KXSENATE": "politics",   "KXHOUSE": "politics",  "KXGOV": "politics",
    "KXCLIMATE": "climate",   "KXWEATHER": "climate",
}


def _derive_category(ticker: str) -> str:
    upper = ticker.upper()
    for prefix, cat in _TICKER_PREFIX_TO_CATEGORY.items():
        if upper.startswith(prefix):
            return cat
    return "other"


def _derive_series_ticker(event_ticker: str) -> str:
    """'KXNBA-24-BOS' → 'KXNBA'."""
    if not event_ticker:
        return ""
    return event_ticker.split("-")[0]


def _month_shard_path(year: int, month: int) -> Path:
    return MARKETS_DIR / f"markets_{year:04d}_{month:02d}.csv"


def _existing_tickers() -> set[str]:
    tickers: set[str] = set()
    for p in MARKETS_DIR.glob("markets_*.csv"):
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                tickers.add(row["ticker"])
    return tickers


def _normalise_market(m: dict) -> dict | None:
    """
    Extract + normalise a raw API market dict.
    Returns None if it fails the binary/volume filters (caller sets volume_floor).
    Does NOT apply the volume_floor — caller checks vol_fp against it.
    """
    ticker = m.get("ticker", "")
    result = m.get("result", "")
    if result not in ("yes", "no"):
        return None
    vol_fp = float(m.get("volume_fp") or m.get("volume") or 0)
    event_ticker = m.get("event_ticker", "")
    series_ticker = m.get("series_ticker") or _derive_series_ticker(event_ticker)
    category = ((m.get("category") or "").lower().strip()
                or _derive_category(ticker))
    return {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "series_ticker": series_ticker,
        "category": category,
        "title": m.get("title", "")[:200],
        "close_time": m.get("close_time", ""),
        "result": result,
        "volume": round(vol_fp, 2),
        "open_interest": float(m.get("open_interest_fp") or m.get("open_interest") or 0),
        "liquidity": float(m.get("liquidity_dollars") or m.get("liquidity") or 0),
        "_vol_fp": vol_fp,   # scratch field for caller's volume check; stripped before saving
    }


def _fetch_tier(client: KalshiClient,
                markets_path: str,
                start: datetime,
                end: datetime,
                existing: set[str],
                volume_floor: int,
                out: list[dict]) -> tuple[int, int]:
    """
    Page through `markets_path` (either /markets or /historical/markets)
    for the [start, end] window. Appends passing rows to `out`.
    Returns (total_seen, total_kept) for logging.
    """
    cursor: str | None = None
    total_seen = 0
    total_kept = 0
    params: dict = {
        "status": "settled",
        "min_close_ts": int(start.timestamp()),
        "max_close_ts": int(end.timestamp()),
        "limit": 200,
    }
    logger.info("Tier %s: %s → %s", markets_path, start.date(), end.date())
    while True:
        if cursor:
            params["cursor"] = cursor
        elif "cursor" in params:
            del params["cursor"]

        data = client.get(markets_path, params=params)
        markets = data.get("markets", [])
        total_seen += len(markets)

        for m in markets:
            ticker = m.get("ticker", "")
            if ticker in existing:
                continue
            row = _normalise_market(m)
            if row is None:
                continue
            if row["_vol_fp"] < volume_floor:
                continue
            del row["_vol_fp"]
            out.append(row)
            existing.add(ticker)
            total_kept += 1

        cursor = data.get("cursor")
        if not cursor or not markets:
            break

        if total_seen % 2000 == 0:
            logger.info("  %s: scanned %d, kept %d", markets_path, total_seen, total_kept)

    logger.info("  done %s: scanned=%d kept=%d", markets_path, total_seen, total_kept)
    return total_seen, total_kept


def fetch_settled_markets(client: KalshiClient,
                          start: datetime = INGEST_START,
                          end: datetime | None = None,
                          volume_floor: int = MIN_VOLUME,
                          cutoff_dt: datetime | None = None) -> list[dict]:
    """
    Fetch all settled markets from [start, end], merging historical + live tiers.

    `cutoff_dt` partitions requests:
      - [start, cutoff_dt) → GET /historical/markets
      - [cutoff_dt, end]   → GET /markets

    Pass cutoff_dt=None to skip historical routing and use the live endpoint only
    (backward-compatible for unit tests that don't need the split).
    """
    MARKETS_DIR.mkdir(parents=True, exist_ok=True)

    now = end or datetime.now(timezone.utc)
    existing = _existing_tickers()
    logger.info("Found %d already-cached tickers", len(existing))

    all_markets: list[dict] = []
    for p in sorted(MARKETS_DIR.glob("markets_*.csv")):
        with open(p, newline="") as f:
            all_markets.extend(csv.DictReader(f))
    logger.info("Loaded %d cached markets", len(all_markets))

    fetched: list[dict] = []
    total_seen = total_kept = 0

    if cutoff_dt is None:
        # Backward-compat: live tier only
        s, k = _fetch_tier(client, "/markets", start, now, existing, volume_floor, fetched)
        total_seen += s
        total_kept += k
    else:
        # Historical tier: [start, min(cutoff_dt, now)]
        if start < cutoff_dt:
            hist_end = min(cutoff_dt, now)
            s, k = _fetch_tier(client, f"{HIST_PREFIX}/markets", start, hist_end,
                               existing, volume_floor, fetched)
            total_seen += s
            total_kept += k
        # Live tier: [max(start, cutoff_dt), now]
        if now > cutoff_dt:
            live_start = max(start, cutoff_dt)
            s, k = _fetch_tier(client, "/markets", live_start, now,
                               existing, volume_floor, fetched)
            total_seen += s
            total_kept += k

    logger.info("Fetch complete: scanned=%d passed=%d", total_seen, total_kept)

    # Shard newly-fetched by close_time month
    shards: dict[tuple[int, int], list[dict]] = {}
    for row in fetched:
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

    all_markets.extend(fetched)

    by_cat: dict[str, int] = {}
    for m in all_markets:
        c = m.get("category", "other")
        by_cat[c] = by_cat.get(c, 0) + 1
    logger.info("Universe: %d markets total", len(all_markets))
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        logger.info("  %-20s %d", cat, n)

    return all_markets


# ---------------------------------------------------------------------------
# Per-month × category histogram (sanity gate before candlestick fetch)
# ---------------------------------------------------------------------------

def print_month_histogram(markets: list[dict]) -> None:
    """
    Print a per-month × per-category count table to stdout.
    Run this after fetch_settled_markets to verify the universe includes
    election/financial/economics categories before committing to candle fetch.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cats: set[str] = set()

    for m in markets:
        ct = m.get("close_time", "")
        try:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            month = f"{dt.year}-{dt.month:02d}"
        except Exception:
            month = "unknown"
        cat = (m.get("category") or "other").lower()
        counts[month][cat] += 1
        cats.add(cat)

    sorted_cats = sorted(cats)
    col_w = 12
    header = f"{'Month':<10}" + "".join(f"  {c:>{col_w}}" for c in sorted_cats) + f"  {'TOTAL':>7}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    grand: dict[str, int] = defaultdict(int)
    for month in sorted(counts):
        row_data = counts[month]
        total = sum(row_data.values())
        row = f"{month:<10}" + "".join(f"  {row_data.get(c, 0):>{col_w}}" for c in sorted_cats) + f"  {total:>7}"
        print(row)
        for c in sorted_cats:
            grand[c] += row_data.get(c, 0)

    grand_total = sum(grand.values())
    print(sep)
    total_row = f"{'TOTAL':<10}" + "".join(f"  {grand[c]:>{col_w}}" for c in sorted_cats) + f"  {grand_total:>7}"
    print(total_row)
    print(sep)
    print()

    # Sanity gate: warn if expected categories are absent
    expected = {"economics", "financials", "politics"}
    missing = expected - set(cats)
    if missing:
        logger.warning("SANITY GATE: expected categories absent from universe: %s", missing)
        logger.warning("Historical tier may not be routing correctly — check cutoff_dt.")
    else:
        logger.info("SANITY GATE OK: economics + financials + politics all present")


# ---------------------------------------------------------------------------
# Candlesticks
# ---------------------------------------------------------------------------

CANDLE_FIELDS = ["ticker", "ts", "yes_bid", "yes_ask", "price", "volume"]


def _candle_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace(":", "_")
    sub = CANDLES_DIR / safe[:2].lower()
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{safe}.csv"


def _already_fetched_tickers() -> set[str]:
    fetched: set[str] = set()
    for p in CANDLES_DIR.rglob("*.csv"):
        fetched.add(p.stem)
    return fetched


def _price_from_nested(obj: object, fallback: float) -> float:
    """Parse Kalshi price field: dict with close_dollars (string) or close (numeric)."""
    if not isinstance(obj, dict):
        return float(obj or fallback) if obj is not None else fallback
    val = obj.get("close_dollars") or obj.get("close")
    return float(val) if val is not None else fallback


def fetch_candles(client: KalshiClient, market: dict,
                  cutoff_dt: datetime | None = None) -> list[dict] | None:
    """
    Fetch 1h candles for [close_time - LOOKBACK_HOURS, close_time].

    Routing:
      - market settled before cutoff_dt → GET /historical/markets/{ticker}/candlesticks
      - otherwise                        → GET /series/{series}/markets/{ticker}/candlesticks

    Returns list of dicts or None if unavailable.
    """
    ticker = market["ticker"]
    close_time_str = market.get("close_time", "")
    try:
        close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
    except Exception:
        logger.debug("Bad close_time for %s: %r", ticker, close_time_str)
        return None

    start_ts = int((close_dt - timedelta(hours=LOOKBACK_HOURS)).timestamp())
    end_ts = int(close_dt.timestamp())

    if cutoff_dt is not None and close_dt < cutoff_dt:
        path = f"{HIST_PREFIX}/markets/{ticker}/candlesticks"
    else:
        series_ticker = market.get("series_ticker", "")
        if not series_ticker:
            logger.debug("No series_ticker for %s — skipping", ticker)
            return None
        path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"

    params = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "period_interval": TARGET_PERIOD_MIN,
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
        yes_bid = _price_from_nested(c.get("yes_bid") or c.get("yes"), 0.0)
        yes_ask = _price_from_nested(c.get("yes_ask"), yes_bid)
        price = _price_from_nested(c.get("price"), yes_bid)
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


def fetch_all_candles(client: KalshiClient, markets: list[dict],
                      cutoff_dt: datetime | None = None) -> dict[str, list[dict]]:
    """Fetch + cache candlesticks for all markets. Skips already-cached tickers."""
    CANDLES_DIR.mkdir(parents=True, exist_ok=True)
    done = _already_fetched_tickers()
    logger.info("%d tickers already have candle files", len(done))

    result: dict[str, list[dict]] = {}

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
        rows = fetch_candles(client, m, cutoff_dt=cutoff_dt)
        if rows:
            p = _candle_path(m["ticker"])
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CANDLE_FIELDS)
                w.writeheader()
                w.writerows(rows)
            result[m["ticker"]] = rows
            fetched += 1
        else:
            _candle_path(m["ticker"]).write_text("")
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
    rows: list[dict] = []
    for p in sorted(MARKETS_DIR.glob("markets_*.csv")):
        with open(p, newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def load_candles(ticker: str) -> list[dict] | None:
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
        # Step 1: discover historical/live partition
        cutoff_dt = fetch_historical_cutoff(client)

        # Step 2: fetch market universe across both tiers
        markets = fetch_settled_markets(client, cutoff_dt=cutoff_dt)

        # Step 3: per-month × category histogram — sanity gate before candles
        print("\n=== Market Universe: per-month × category ===")
        print_month_histogram(markets)

        if len(markets) < 5_000:
            print(f"STOP: only {len(markets):,} usable markets (threshold: 5,000)")
            print("Universe too small — check historical tier routing and volume filter.")
            return

        if len(markets) > 50_000:
            new_floor = MIN_VOLUME * 5
            logger.warning("Universe %d > 50,000 — raising volume floor to %d",
                           len(markets), new_floor)
            markets = [m for m in markets if float(m.get("volume", 0)) >= new_floor]
            logger.info("After floor raise: %d markets", len(markets))

        # Step 4: candlesticks (routed by cutoff_dt)
        candles = fetch_all_candles(client, markets, cutoff_dt=cutoff_dt)
        with_candles = sum(1 for m in markets if m["ticker"] in candles)
        print(funnel_report(
            all_settled=len(markets),
            after_filter=len(markets),
            with_candles=with_candles,
        ))
    finally:
        client.close()


if __name__ == "__main__":
    main()
