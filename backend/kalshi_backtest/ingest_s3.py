"""
Kalshi S3 bulk ingest — daily market-data files.

S3 URL pattern:
  https://kalshi-public-docs.s3.amazonaws.com/reporting/market_data_{YYYY-MM-DD}.json

Schema (confirmed via Task 1 schema discovery, 2026-06-12):
  date          str  "YYYY-MM-DD"
  ticker_name   str  full market ticker, e.g. "KXPRES-24-DEM"
  report_ticker str  series prefix, e.g. "KXPRES"
  payout_type   str  "Binary Option" (or scalar variant — we keep Binary Only)
  open_interest float/str (type varies by vintage)
  daily_volume  int/str
  block_volume  int/str
  high          int  daily high price in cents (1–100)
  low           int  daily low price in cents (1–100)
  status        str  "active" | "finalized" | "closed"

No explicit close or result field. Close is approximated as (high+low)/2 / 100.
Settlement outcomes are resolved via per-ticker API lookup (GET /historical/markets/{ticker}).

Usage:
  cd backend
  uv run python -m kalshi_backtest.ingest_s3

Credentials (for settlement lookup only):
  KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
"""
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("kalshi_backtest.ingest_s3")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

S3_BASE = "https://kalshi-public-docs.s3.amazonaws.com/reporting"
ARCHIVE_START = date(2021, 7, 2)   # first file with real data
STUDY_START   = date(2024, 6, 1)   # study window start

DATA_DIR   = Path(__file__).parent / "data"
SHARD_DIR  = DATA_DIR / "s3_markets"
MANIFEST   = DATA_DIR / "s3_manifest.json"
SETTLE_DIR = DATA_DIR / "settlements"

# Price range kept regardless of category (superset of 80–97 study band)
PRICE_FLOOR_CENTS = 75
PRICE_CEIL_CENTS  = 99

# Filter: only Binary Option payout type
PAYOUT_KEEP = {"Binary Option"}

# Parlay series prefixes — excluded from the study universe
# Identified via series metadata (GET /series/{ticker}) in Task 3.
# Parlays are multi-leg bundles; single-outcome sports markets stay in.
PARLAY_PREFIXES: frozenset[str] = frozenset({
    "KXMVESPORTSMULTIGAMEEXTENDED",
    "KXMVECROSSCATEGORY",
    "KXMVESPORTS",
    "KXMVECROSS",
})

SHARD_FIELDS = [
    "ticker_name", "report_ticker", "date",
    "high_cents", "low_cents", "daily_volume",
    "open_interest", "status",
]

# Settlement cache fields
SETTLE_FIELDS = ["ticker_name", "result"]

# Concurrency for S3 downloads
N_WORKERS = 4

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _trading_days(start: date, end: date) -> list[date]:
    """All calendar days in [start, end] — we probe each and skip 404s (weekends/holidays)."""
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def _load_manifest() -> dict[str, str]:
    """Load completed-date manifest. Values: 'ok', 'empty', '404'."""
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# S3 download
# ---------------------------------------------------------------------------

def _day_url(d: date) -> str:
    return f"{S3_BASE}/market_data_{d.isoformat()}.json"


def _download_day_records(d: date) -> list[dict] | None:
    """
    Download one day's JSON to a temp file, parse, delete.
    Returns None on 404 (weekend/holiday), list of dicts otherwise.
    """
    url = _day_url(d)
    tmp = Path(tempfile.mktemp(suffix=".json"))
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=300) as resp:
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1 << 18)  # 256KB chunks
                    if not chunk:
                        break
                    f.write(chunk)
        size_kb = tmp.stat().st_size // 1024
        logger.debug("%s: downloaded %dKB", d, size_kb)
        with open(tmp) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Per-record filtering
# ---------------------------------------------------------------------------

def _mid_cents(record: dict) -> float:
    h = record.get("high", 0) or 0
    lo = record.get("low", 0) or 0
    return (int(h) + int(lo)) / 2.0


def _is_parlay(report_ticker: str) -> bool:
    rt = report_ticker.upper()
    for p in PARLAY_PREFIXES:
        if rt.startswith(p.upper()):
            return True
    return False


def _should_keep(record: dict, series_keep: set[str] | None = None) -> bool:
    """
    Keep a row if:
    (a) Binary Option payout type
    (b) daily_volume >= 1 OR open_interest > 0  (some volume ever)
    (c) series_prefix on keep-list  OR  mid price in [PRICE_FLOOR, PRICE_CEIL]
    """
    if record.get("payout_type") not in PAYOUT_KEEP:
        return False
    vol = float(record.get("daily_volume") or 0)
    oi  = float(record.get("open_interest") or 0)
    if vol < 1 and oi <= 0:
        return False
    mid = _mid_cents(record)
    rt  = record.get("report_ticker", "")
    if series_keep and rt in series_keep:
        return True
    return PRICE_FLOOR_CENTS <= mid <= PRICE_CEIL_CENTS


def _normalise(record: dict, d: date) -> dict:
    """Normalise raw API dict to flat shard row."""
    return {
        "ticker_name":   record.get("ticker_name", ""),
        "report_ticker": record.get("report_ticker", ""),
        "date":          d.isoformat(),
        "high_cents":    int(record.get("high") or 0),
        "low_cents":     int(record.get("low") or 0),
        "daily_volume":  float(record.get("daily_volume") or 0),
        "open_interest": float(record.get("open_interest") or 0),
        "status":        record.get("status", ""),
    }


# ---------------------------------------------------------------------------
# Monthly shard I/O
# ---------------------------------------------------------------------------

def _shard_path(yr: int, mo: int) -> Path:
    return SHARD_DIR / f"markets_s3_{yr:04d}_{mo:02d}.csv"


def _append_to_shard(rows: list[dict]) -> None:
    if not rows:
        return
    from collections import defaultdict
    by_month: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rows:
        try:
            d = date.fromisoformat(r["date"])
            by_month[(d.year, d.month)].append(r)
        except Exception:
            pass

    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    for (yr, mo), group in by_month.items():
        p = _shard_path(yr, mo)
        write_header = not p.exists()
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SHARD_FIELDS)
            if write_header:
                w.writeheader()
            w.writerows(group)


def load_s3_shards(start: date = STUDY_START,
                   end: date | None = None) -> list[dict]:
    """Load all shard rows in [start, end] into memory."""
    if end is None:
        end = date.today()
    rows = []
    for p in sorted(SHARD_DIR.glob("markets_s3_*.csv")):
        # Extract year/month from filename
        parts = p.stem.split("_")
        if len(parts) < 4:
            continue
        try:
            yr, mo = int(parts[-2]), int(parts[-1])
        except ValueError:
            continue
        # Quick month-range filter
        file_start = date(yr, mo, 1)
        file_end = date(yr, mo, 28) + timedelta(days=4)
        if file_end < start or file_start > end:
            continue
        with open(p, newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


# ---------------------------------------------------------------------------
# Per-day ingest worker
# ---------------------------------------------------------------------------

def _ingest_one_day(args: tuple) -> tuple[str, str, int]:
    """
    Worker: download + filter + shard one day.
    Returns (date_str, status, rows_kept).
    """
    d, series_keep = args
    date_str = d.isoformat()
    try:
        records = _download_day_records(d)
        if records is None:
            return (date_str, "404", 0)
        if not records:
            return (date_str, "empty", 0)
        kept = []
        for rec in records:
            if _should_keep(rec, series_keep):
                kept.append(_normalise(rec, d))
        _append_to_shard(kept)
        return (date_str, "ok", len(kept))
    except Exception as e:
        logger.error("Error ingesting %s: %s", date_str, e)
        return (date_str, f"error:{e}", 0)


# ---------------------------------------------------------------------------
# Main ingest loop
# ---------------------------------------------------------------------------

def run_ingest(
    start: date = STUDY_START,
    end: date | None = None,
    n_workers: int = N_WORKERS,
    series_keep: set[str] | None = None,
) -> dict[str, int]:
    """
    Iterate trading days in [start, end], download S3 files in parallel,
    filter, and append to monthly shards. Resumable via manifest.

    Returns funnel counters: {total_days, ok, not_found, rows_kept}.
    """
    if end is None:
        end = date.today()

    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()

    all_days = _trading_days(start, end)
    pending = [d for d in all_days if d.isoformat() not in manifest]

    logger.info("Ingest: %d days total, %d already done, %d to fetch",
                len(all_days), len(all_days) - len(pending), len(pending))

    counters = {"total_days": len(all_days), "ok": 0, "not_found": 0,
                "rows_kept": 0, "errors": 0}

    args_list = [(d, series_keep) for d in pending]

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(_ingest_one_day, a): a[0] for a in args_list}
        done = 0
        for fut in as_completed(futures):
            date_str, status, rows = fut.result()
            manifest[date_str] = status
            done += 1
            if status == "ok":
                counters["ok"] += 1
                counters["rows_kept"] += rows
            elif status == "404":
                counters["not_found"] += 1
            elif status == "empty":
                pass
            else:
                counters["errors"] += 1

            if done % 50 == 0 or done == len(pending):
                # Disk usage
                used_mb = sum(p.stat().st_size for p in SHARD_DIR.glob("*.csv")) / 1_048_576
                logger.info(
                    "Progress: %d/%d days | rows_kept=%d | disk=%.1fMB | status=%s",
                    done, len(pending), counters["rows_kept"], used_mb, status,
                )
                _save_manifest(manifest)

    _save_manifest(manifest)
    used_mb = sum(p.stat().st_size for p in SHARD_DIR.glob("*.csv")) / 1_048_576
    logger.info(
        "Ingest complete: ok=%d not_found=%d errors=%d rows_kept=%d disk=%.1fMB",
        counters["ok"], counters["not_found"], counters["errors"],
        counters["rows_kept"], used_mb,
    )
    return counters


# ---------------------------------------------------------------------------
# Task 3 — Series metadata + parlay exclusion
# ---------------------------------------------------------------------------

SERIES_CACHE: Path = DATA_DIR / "series_cache.json"

# Category derived from known series prefixes (fallback when API is unavailable)
_PREFIX_TO_CATEGORY: dict[str, str] = {
    "KXPRES": "politics",      "KXELECTION": "politics", "KXSENATE": "politics",
    "KXHOUSE": "politics",     "KXGOV": "politics",      "KXCONGRESS": "politics",
    "KXBTC": "financials",     "KXBTCD": "financials",   "KXETH": "financials",
    "KXSPY": "financials",     "KXNASDAQ": "financials", "KXSP": "financials",
    "KXDOW": "financials",     "KXGOLD": "financials",   "KXOIL": "financials",
    "KXFED": "economics",      "KXFOMC": "economics",    "KXCPI": "economics",
    "KXGDP": "economics",      "KXJOBS": "economics",    "KXUNEMPLOYMENT": "economics",
    "KXTEMPNYC": "climate",    "KXTEMPCHI": "climate",   "KXTEMPLA": "climate",
    "KXCLIMATE": "climate",    "KXWEATHER": "climate",   "KXHURRICANE": "climate",
    "KXNBA": "sports",         "KXNFL": "sports",        "KXMLB": "sports",
    "KXNHL": "sports",         "KXNCAAF": "sports",      "KXNCAAB": "sports",
    "KXUFC": "sports",         "KXTENNIS": "sports",     "KXSOCCER": "sports",
    "KXNASCAR": "sports",      "KXGOLF": "sports",
    "SCOURT": "politics",      "MOON": "other",          "AMAZONFTC": "politics",
}

# Patterns in series title/description that identify parlays
_PARLAY_TITLE_PATTERNS = (
    "parlay", "multi-game", "multi-leg", "multileg", "multi game",
    "multievent", "multi-event",
)


def _category_from_prefix(report_ticker: str) -> str:
    upper = report_ticker.upper()
    for prefix, cat in _PREFIX_TO_CATEGORY.items():
        if upper.startswith(prefix.upper()):
            return cat
    return "other"


def _is_parlay_from_meta(meta: dict) -> bool:
    """Return True if series metadata indicates a multi-leg parlay."""
    ticker = (meta.get("ticker") or "").upper()
    title  = (meta.get("title") or meta.get("category") or "").lower()
    for pat in _PARLAY_TITLE_PATTERNS:
        if pat in title:
            return True
    # Also check known parlay prefixes
    for p in PARLAY_PREFIXES:
        if ticker.startswith(p.upper()):
            return True
    return False


def fetch_series_metadata(
    report_tickers: list[str],
    client,  # KalshiClient
    cache_path: Path = SERIES_CACHE,
) -> dict[str, dict]:
    """
    Fetch series metadata for each distinct report_ticker.
    Results cached in series_cache.json. Returns {report_ticker: meta}.
    """
    # Load cache
    cache: dict[str, dict] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            pass

    needed = [t for t in report_tickers if t not in cache]
    logger.info("Series metadata: %d cached, %d to fetch", len(cache), len(needed))

    for i, ticker in enumerate(needed):
        try:
            data = client.get(f"/series/{ticker}")
            meta = data.get("series") or data  # unwrap if nested
            cache[ticker] = meta
        except Exception as e:
            logger.debug("Series %s: %s", ticker, e)
            cache[ticker] = {"ticker": ticker, "_fetch_error": str(e)}
        if (i + 1) % 100 == 0:
            logger.info("  Series metadata: %d/%d done", i + 1, len(needed))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=2))

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2))
    return cache


def assign_category(report_ticker: str, series_cache: dict[str, dict]) -> str:
    """Derive category from series metadata or prefix fallback."""
    meta = series_cache.get(report_ticker, {})
    # Check API-provided category
    api_cat = (meta.get("category") or "").lower().strip()
    if api_cat and api_cat not in ("", "unknown"):
        return api_cat
    return _category_from_prefix(report_ticker)


# ---------------------------------------------------------------------------
# Task 4 — Settlement resolution
# ---------------------------------------------------------------------------

def _settle_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace(":", "_")
    sub = SETTLE_DIR / safe[:2].lower()
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{safe}.json"


def load_settlement_cache() -> dict[str, str]:
    """Return {ticker_name: result} from disk cache."""
    cache: dict[str, str] = {}
    if not SETTLE_DIR.exists():
        return cache
    for p in SETTLE_DIR.rglob("*.json"):
        try:
            obj = json.loads(p.read_text())
            ticker = obj.get("ticker_name", p.stem)
            result = obj.get("result", "")
            if result in ("yes", "no"):
                cache[ticker] = result
        except Exception:
            pass
    return cache


def resolve_settlements(
    tickers: list[str],
    client,            # KalshiClient
    cutoff_dt,         # datetime
    batch_size: int = 500,
) -> dict[str, str]:
    """
    For each ticker not yet in the settlement cache, do a direct keyed lookup.
    Uses /historical/markets/{ticker} for old markets, /markets/{ticker} for recent.

    Returns {ticker_name: "yes"|"no"}.
    """
    from datetime import datetime, timezone

    SETTLE_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_settlement_cache()
    needed = [t for t in tickers if t not in cache and t]

    logger.info("Settlement resolution: %d cached, %d to fetch", len(cache), len(needed))

    fetched = 0
    failed  = 0
    for i, ticker in enumerate(needed):
        # Route: use historical endpoint for older tickers
        # We infer age from the ticker name (look for year digits) — conservative fallback
        try:
            # Try historical first (works for settled markets)
            data = client.get(f"/historical/markets/{ticker}")
            mkt = (data.get("market") or data)
            result = (mkt.get("result") or "").lower()
            if result not in ("yes", "no"):
                # Try live endpoint
                data = client.get(f"/markets/{ticker}")
                mkt = (data.get("market") or data)
                result = (mkt.get("result") or "").lower()
        except Exception:
            try:
                data = client.get(f"/markets/{ticker}")
                mkt = (data.get("market") or data)
                result = (mkt.get("result") or "").lower()
            except Exception as e:
                logger.debug("Settlement lookup failed for %s: %s", ticker, e)
                result = ""

        if result in ("yes", "no"):
            obj = {"ticker_name": ticker, "result": result}
            _settle_path(ticker).write_text(json.dumps(obj))
            cache[ticker] = result
            fetched += 1
        else:
            failed += 1

        if (i + 1) % 200 == 0:
            logger.info("  Settlement: %d/%d done (%d fetched, %d failed)",
                        i + 1, len(needed), fetched, failed)
        time.sleep(0.1)  # gentle rate-limit

    logger.info("Settlement resolution complete: fetched=%d failed=%d", fetched, failed)
    return cache


# ---------------------------------------------------------------------------
# Task 4 — Funnel report
# ---------------------------------------------------------------------------

def build_funnel_report(
    rows: list[dict],
    settlements: dict[str, str],
    series_cache: dict[str, dict],
    volume_floor: float = 500.0,
) -> str:
    """
    Returns a multi-line funnel report string.
    """
    from collections import defaultdict

    total_row_days = len(rows)
    tickers = {r["ticker_name"] for r in rows}
    distinct_markets = len(tickers)

    # After parlay exclusion
    non_parlay = [r for r in rows if not _is_parlay(r["report_ticker"])]
    tickers_non_parlay = {r["ticker_name"] for r in non_parlay}

    # Lifetime volume per ticker
    vol_by_ticker: dict[str, float] = defaultdict(float)
    for r in rows:
        vol_by_ticker[r["ticker_name"]] += float(r.get("daily_volume") or 0)

    # After volume floor
    high_vol = {t for t, v in vol_by_ticker.items() if v >= volume_floor}
    after_vol = [r for r in non_parlay if r["ticker_name"] in high_vol]
    tickers_after_vol = {r["ticker_name"] for r in after_vol}

    # After settlement resolved
    settled = {t for t in tickers_after_vol if settlements.get(t) in ("yes", "no")}

    # Per-category breakdown
    by_cat_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in after_vol:
        if r["ticker_name"] not in settled:
            continue
        cat = assign_category(r["report_ticker"], series_cache)
        try:
            d = date.fromisoformat(r["date"])
            mo = f"{d.year}-{d.month:02d}"
        except Exception:
            mo = "unknown"
        by_cat_month[mo][cat] += 1

    lines = [
        "=" * 60,
        "KALSHI FAVORITES — INGEST FUNNEL",
        "=" * 60,
        f"Total market-day rows ingested: {total_row_days:,}",
        f"Distinct markets seen:          {distinct_markets:,}",
        f"After parlay exclusion:         {len(tickers_non_parlay):,}",
        f"After lifetime vol ≥ {volume_floor:.0f}:      {len(tickers_after_vol):,}",
        f"With resolved settlement:       {len(settled):,}",
        "",
        "Per-month × category (settled markets only):",
    ]

    cats = sorted({c for mo_cats in by_cat_month.values() for c in mo_cats})
    col_w = 11
    hdr = f"  {'Month':<9}" + "".join(f"  {c:>{col_w}}" for c in cats) + f"  {'TOTAL':>6}"
    lines.append(hdr)
    lines.append("  " + "-" * (len(hdr) - 2))

    grand: dict[str, int] = defaultdict(int)
    for mo in sorted(by_cat_month):
        mc = by_cat_month[mo]
        total = sum(mc.values())
        row = f"  {mo:<9}" + "".join(f"  {mc.get(c, 0):>{col_w}}" for c in cats) + f"  {total:>6}"
        lines.append(row)
        for c in cats:
            grand[c] += mc.get(c, 0)

    grand_total = sum(grand.values())
    lines.append("  " + "-" * (len(hdr) - 2))
    lines.append(f"  {'TOTAL':<9}" + "".join(f"  {grand[c]:>{col_w}}" for c in cats) + f"  {grand_total:>6}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Task 5 — Assemble per-market histories for calibration
# ---------------------------------------------------------------------------

HORIZONS_D  = [1, 2, 7]          # trading days before final trading day
FILL_HAIRCUT_CENTS = 1            # default entry-price haircut (¢)

def build_market_histories(rows: list[dict]) -> dict[str, list[dict]]:
    """
    Group shard rows by ticker into sorted daily histories.
    Returns {ticker_name: [row, ...]} sorted by date ascending.
    """
    from collections import defaultdict
    hist: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        hist[r["ticker_name"]].append(r)
    for t in hist:
        hist[t].sort(key=lambda r: r["date"])
    return dict(hist)


def build_dataset_s3(
    rows: list[dict],
    settlements: dict[str, str],
    series_cache: dict[str, dict],
    haircut_cents: int = FILL_HAIRCUT_CENTS,
    volume_floor: float = 500.0,
) -> "pd.DataFrame":
    """
    Build calibration dataset from S3 shards.

    Entry horizons: 1, 2, 7 trading days before the final trading day.
    Close price = (high_cents + low_cents) / 2 / 100.
    Entry price  = close + haircut_cents / 100.
    Momentum     = change in close over prior 5 trading days.

    Returns a DataFrame with columns matching calibration.build_dataset() output.
    """
    import pandas as pd

    # Build per-ticker histories
    hists = build_market_histories(rows)

    # Lifetime volume filter
    vol_by_ticker = {
        t: sum(float(r.get("daily_volume") or 0) for r in hist)
        for t, hist in hists.items()
    }

    records = []
    skipped_no_settle = 0
    skipped_vol       = 0
    skipped_parlay    = 0

    for ticker, hist in hists.items():
        # Parlay exclusion
        rt = hist[0].get("report_ticker", "") if hist else ""
        if _is_parlay(rt):
            skipped_parlay += 1
            continue

        # Volume floor
        if vol_by_ticker.get(ticker, 0) < volume_floor:
            skipped_vol += 1
            continue

        # Settlement
        result = settlements.get(ticker, "")
        if result not in ("yes", "no"):
            skipped_no_settle += 1
            continue

        resolved_yes = int(result == "yes")
        category = assign_category(rt, series_cache)

        # Trading days with volume > 0 (or at minimum open interest > 0)
        active_days = [r for r in hist
                       if float(r.get("daily_volume") or 0) > 0
                       or float(r.get("open_interest") or 0) > 0]
        if not active_days:
            continue

        # Final trading day = last active day
        final_day_date = active_days[-1]["date"]

        # For each horizon
        for horizon_d in HORIZONS_D:
            idx = len(active_days) - 1 - horizon_d
            if idx < 0:
                continue
            entry_row = active_days[idx]

            h = int(entry_row.get("high_cents") or 0)
            lo = int(entry_row.get("low_cents") or 0)
            if h <= 0 and lo <= 0:
                continue

            close_price = (h + lo) / 2.0 / 100.0
            entry_price = close_price + haircut_cents / 100.0
            entry_price = min(entry_price, 0.99)  # cap at 99¢

            if entry_price <= 0 or entry_price >= 1.0:
                continue

            # Bucket label
            from kalshi_backtest.calibration import _bucket_label, BUCKETS
            bucket = _bucket_label(entry_price)
            if bucket is None:
                continue

            # Momentum: change in close over prior 5 trading days
            momentum_idx = idx - 5
            if momentum_idx >= 0:
                r5 = active_days[momentum_idx]
                h5 = int(r5.get("high_cents") or 0)
                l5 = int(r5.get("low_cents") or 0)
                prior_close = (h5 + l5) / 2.0 / 100.0
                momentum = close_price - prior_close
            else:
                momentum = 0.0

            records.append({
                "ticker":        ticker,
                "category":      category,
                "close_time":    final_day_date,   # used for window splits
                "horizon_h":     horizon_d * 24,    # map to hours for compat w/ calibrate()
                "ask_price":     round(entry_price, 4),
                "bucket":        bucket,
                "resolved_yes":  resolved_yes,
                "momentum_24h":  round(momentum, 4),
            })

    logger.info(
        "Dataset: %d rows from %d tickers "
        "(skipped: parlay=%d vol=%d no_settle=%d)",
        len(records), len(hists),
        skipped_parlay, skipped_vol, skipped_no_settle,
    )
    if not records:
        import pandas as pd
        return pd.DataFrame(columns=[
            "ticker", "category", "close_time", "horizon_h",
            "ask_price", "bucket", "resolved_yes", "momentum_24h",
        ])
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import sys
    from datetime import datetime, timezone

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # ── Task 2: ingest ────────────────────────────────────────────────────
    logger.info("Starting S3 ingest: %s → %s", STUDY_START, date.today())
    counters = run_ingest()
    logger.info("Ingest counters: %s", counters)

    rows = load_s3_shards()
    if not rows:
        logger.error("No rows in shards — aborting")
        sys.exit(1)

    # ── Task 3: series metadata + category ───────────────────────────────
    from kalshi_backtest.ingest import KalshiClient, fetch_historical_cutoff, _load_creds
    key_id, pem_bytes = _load_creds()
    client = KalshiClient(key_id, pem_bytes)

    report_tickers = list({r["report_ticker"] for r in rows})
    series_cache = fetch_series_metadata(report_tickers, client)
    logger.info("Series cache: %d entries", len(series_cache))

    # ── Task 4: settlement resolution ────────────────────────────────────
    cutoff_dt = fetch_historical_cutoff(client)
    all_tickers = list({r["ticker_name"] for r in rows
                        if not _is_parlay(r["report_ticker"])})
    settlements = resolve_settlements(all_tickers, client, cutoff_dt)

    # Print funnel report
    report = build_funnel_report(rows, settlements, series_cache)
    print(report)

    settled_tickers = {t for t, v in settlements.items() if v in ("yes","no")}
    if len(settled_tickers) < 5_000:
        print(f"\nSTOP: only {len(settled_tickers):,} markets with settled outcome "
              f"(threshold: 5,000). Universe too small.")
        client.close()
        return

    # ── Task 5: calibration + simulation ─────────────────────────────────
    from kalshi_backtest.calibration import (
        calibrate, adverse_selection_analysis, run_calibration
    )
    from kalshi_backtest.simulate import select_cells, run_simulation

    df = build_dataset_s3(rows, settlements, series_cache)
    if df.empty:
        print("STOP: empty dataset after filtering")
        client.close()
        return

    df_sel   = calibrate(df, window="selection")
    df_val   = calibrate(df, window="validation")
    df_adv   = adverse_selection_analysis(df, window="selection")

    logger.info("Calibration done: sel=%d rows, val=%d rows", len(df_sel), len(df_val))

    # ── Task 6: kill criteria ─────────────────────────────────────────────
    from kalshi_backtest.report import evaluate_kcs, generate_report_s3
    kc_results = evaluate_kcs(df_sel, df_val, df_adv, df)

    # ── Task 7: reports ───────────────────────────────────────────────────
    generate_report_s3(
        df, df_sel, df_val, df_adv, kc_results,
        rows, settlements, series_cache,
        haircut_1c=True,
    )
    # Re-run KCs at 2¢ haircut for sensitivity
    df_2c = build_dataset_s3(rows, settlements, series_cache, haircut_cents=2)
    df_sel_2c = calibrate(df_2c, window="selection")
    df_val_2c = calibrate(df_2c, window="validation")
    df_adv_2c = adverse_selection_analysis(df_2c, window="selection")
    kc_2c = evaluate_kcs(df_sel_2c, df_val_2c, df_adv_2c, df_2c)
    generate_report_s3(
        df_2c, df_sel_2c, df_val_2c, df_adv_2c, kc_2c,
        rows, settlements, series_cache,
        haircut_1c=False,
    )

    client.close()


if __name__ == "__main__":
    main()
