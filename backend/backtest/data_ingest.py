"""
Download and cache historical market data for the carry backtest.

Sources (no API key required):
  - Binance Vision bulk archives: funding rates + 1h klines (perp + spot)
  - Hyperliquid info API: hourly funding history from 2023-07 onward (cross-check only)

Fallback for funding rates: Bybit v5 REST if Binance Vision is unreachable.

All data is cached under backtest/data/. Re-running is idempotent: cached files
are returned immediately without hitting the network.

Usage:
    cd backend
    uv run python -m backtest.data_ingest
"""
import csv
import io
import json
import logging
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger("backtest.data_ingest")

DATA_DIR = Path(__file__).parent / "data"
BINANCE_VISION = "https://data.binance.vision"
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
BYBIT_URL = "https://api.bybit.com/v5/market/funding/history"

# Binance perpetual symbol -> engine coin name
SYMBOL_MAP = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
COIN_TO_SYMBOL = {v: k for k, v in SYMBOL_MAP.items()}
COINS = ["BTC", "ETH"]

PERIODS_PER_YEAR = 24 * 365  # hourly, matching engine convention


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _complete_months(start_year: int = 2020, start_month: int = 1) -> list[tuple[int, int]]:
    """All (year, month) pairs from start through the last fully-complete month."""
    today = date.today()
    last = date(today.year, today.month, 1) - timedelta(days=1)
    result: list[tuple[int, int]] = []
    y, m = start_year, start_month
    while (y, m) <= (last.year, last.month):
        result.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def _fetch_bytes(url: str, timeout: int = 90) -> bytes:
    """Download a URL, return raw bytes."""
    logger.debug("GET %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _extract_csv_rows(zip_bytes: bytes) -> list[list[str]]:
    """
    Extract the first file from a zip and return all non-empty rows as lists of strings.
    Does NOT assume a header row — uses purely positional parsing.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            text = f.read().decode("utf-8", errors="replace")
    rows = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        rows.append(next(csv.reader([raw])))
    return rows


def _is_header(row: list[str]) -> bool:
    """Return True if this row looks like a CSV header (first cell is non-numeric)."""
    try:
        float(row[0].replace(",", ""))
        return False
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Task 1a — Funding rates
# ---------------------------------------------------------------------------

def _download_funding_binance(binance_symbol: str) -> pd.DataFrame:
    """
    Download monthly funding rate archives from Binance Vision for `binance_symbol`.

    Binance settles every 8 hours; returns a DataFrame with columns:
      ts (UTC datetime), funding_rate_8h (raw 8h rate), funding_hourly (rate / 8).

    CRITICAL UNIT CONVERSION: Binance rate is per 8h settlement.
    The engine's accrue_funding() expects an HOURLY rate.
    Therefore: funding_hourly = funding_rate_8h / 8.0
    Proof: constant rate of 0.0001/8h → hourly = 0.000_0125 → annualized = 0.0000125 × 8760 ≈ 0.1096 (10.96%).
    """
    months = _complete_months()
    rows: list[dict] = []
    for y, m in months:
        url = (f"{BINANCE_VISION}/data/futures/um/monthly/fundingRate/"
               f"{binance_symbol}/{binance_symbol}-fundingRate-{y:04d}-{m:02d}.zip")
        try:
            data = _fetch_bytes(url)
            all_rows = _extract_csv_rows(data)
        except Exception as e:
            logger.warning("Binance Vision funding %s %04d-%02d: %s", binance_symbol, y, m, e)
            continue

        for row in all_rows:
            if _is_header(row):
                continue
            # CSV format: calc_time, funding_interval_hours, last_funding_rate
            # (3 columns; older files may have 2 columns: calc_time, last_funding_rate)
            if len(row) < 2:
                continue
            try:
                ts_ms = int(row[0])
                if len(row) >= 3:
                    rate = float(row[2])   # funding_interval_hours at [1], rate at [2]
                else:
                    rate = float(row[1])   # legacy 2-column format
                rows.append({"ts_ms": ts_ms, "funding_rate_8h": rate})
            except (ValueError, IndexError):
                continue

    if not rows:
        raise RuntimeError(
            f"No Binance Vision funding data for {binance_symbol}. Will try Bybit fallback."
        )

    df = pd.DataFrame(rows)
    df = df.sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["funding_hourly"] = df["funding_rate_8h"] / 8.0
    return df[["ts", "funding_rate_8h", "funding_hourly"]]


def _download_funding_bybit(bybit_symbol: str) -> pd.DataFrame:
    """
    Fallback: pull funding rate history from Bybit v5 API, paginating backwards.
    Returns same schema as _download_funding_binance.
    """
    logger.info("Using Bybit fallback for %s funding rates", bybit_symbol)
    rows: list[dict] = []
    end_time = int(time.time() * 1000)
    # 2020-01-01 00:00 UTC in ms
    start_ms = 1577836800000

    while end_time > start_ms:
        params = (f"category=linear&symbol={bybit_symbol}&limit=200"
                  f"&endTime={end_time}")
        url = f"{BYBIT_URL}?{params}"
        try:
            raw = _fetch_bytes(url)
            resp = json.loads(raw)
        except Exception as e:
            logger.warning("Bybit funding fetch failed: %s", e)
            break

        result = resp.get("result", {})
        items = result.get("list", [])
        if not items:
            break

        for item in items:
            ts_ms = int(item["fundingRateTimestamp"])
            rate = float(item["fundingRate"])
            rows.append({"ts_ms": ts_ms, "funding_rate_8h": rate})

        oldest = min(int(i["fundingRateTimestamp"]) for i in items)
        if oldest <= start_ms or oldest >= end_time:
            break
        end_time = oldest - 1

    if not rows:
        raise RuntimeError(f"Bybit fallback also failed for {bybit_symbol}")

    df = pd.DataFrame(rows)
    df = df.sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["funding_hourly"] = df["funding_rate_8h"] / 8.0
    return df[["ts", "funding_rate_8h", "funding_hourly"]]


def download_funding_rates(coin: str) -> tuple[pd.DataFrame, str]:
    """
    Download funding rates for `coin` (e.g. 'BTC'), trying Binance Vision first.

    Returns (df, source_label) where df has columns:
      ts, funding_rate_8h, funding_hourly

    Cached to data/{coin}_funding.csv after first download.
    """
    cache = DATA_DIR / f"{coin}_funding.csv"
    if cache.exists():
        logger.info("Loading cached %s", cache.name)
        df = pd.read_csv(cache)
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
        return df, "cache"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    binance_sym = COIN_TO_SYMBOL[coin]

    try:
        df = _download_funding_binance(binance_sym)
        source = "binance_vision"
    except RuntimeError as e:
        logger.warning("%s — trying Bybit fallback", e)
        df = _download_funding_bybit(binance_sym)
        source = "bybit"

    df.to_csv(cache, index=False)
    logger.info("  %s: %d settlements [%s → %s] source=%s",
                coin, len(df), df["ts"].iloc[0].date(), df["ts"].iloc[-1].date(), source)
    return df, source


# ---------------------------------------------------------------------------
# Task 1b — Klines (perp + spot)
# ---------------------------------------------------------------------------

def _download_klines_binance(binance_symbol: str, market_path: str) -> pd.DataFrame:
    """
    Download monthly 1h kline ZIPs from Binance Vision.

    market_path: 'futures/um' for perp mark, 'spot' for spot.
    Returns DataFrame with columns: ts (UTC datetime), close (float).

    Kline CSV format (no header): open_time, open, high, low, close, volume, ...
    We take column 0 (timestamp ms) and column 4 (close price).
    """
    months = _complete_months()
    rows: list[dict] = []
    for y, m in months:
        url = (f"{BINANCE_VISION}/data/{market_path}/monthly/klines/"
               f"{binance_symbol}/1h/{binance_symbol}-1h-{y:04d}-{m:02d}.zip")
        try:
            data = _fetch_bytes(url)
            all_rows = _extract_csv_rows(data)
        except Exception as e:
            logger.warning("Binance Vision kline %s %s %04d-%02d: %s",
                           market_path, binance_symbol, y, m, e)
            continue

        for row in all_rows:
            if _is_header(row) or len(row) < 5:
                continue
            try:
                ts_raw = int(row[0])
                close = float(row[4])
                # Binance Vision spot klines switched from milliseconds to
                # microseconds in 2025. Detect by magnitude: valid ms timestamps
                # for 2014-2033 are < 2e12; microsecond timestamps are ~1000×
                # larger. Convert microseconds → milliseconds automatically.
                if ts_raw > 2_000_000_000_000:
                    ts_ms = ts_raw // 1000
                else:
                    ts_ms = ts_raw
                rows.append({"ts_ms": ts_ms, "close": close})
            except (ValueError, IndexError):
                continue

    if not rows:
        raise RuntimeError(f"No kline data for {binance_symbol} ({market_path})")

    df = pd.DataFrame(rows)
    df = df.sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df[["ts", "close"]]


def download_perp_prices(coin: str) -> pd.DataFrame:
    """
    Download 1h perpetual mark prices (close) for `coin` from Binance Vision.
    Cached to data/{coin}_perp_1h.csv.
    """
    cache = DATA_DIR / f"{coin}_perp_1h.csv"
    if cache.exists():
        logger.info("Loading cached %s", cache.name)
        df = pd.read_csv(cache)
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
        return df

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sym = COIN_TO_SYMBOL[coin]
    df = _download_klines_binance(sym, "futures/um")
    df.to_csv(cache, index=False)
    logger.info("  %s perp: %d rows [%s → %s]",
                coin, len(df), df["ts"].iloc[0].date(), df["ts"].iloc[-1].date())
    return df


def download_spot_prices(coin: str) -> pd.DataFrame:
    """
    Download 1h spot prices (close) for `coin` from Binance Vision.
    Cached to data/{coin}_spot_1h.csv.
    """
    cache = DATA_DIR / f"{coin}_spot_1h.csv"
    if cache.exists():
        logger.info("Loading cached %s", cache.name)
        df = pd.read_csv(cache)
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
        return df

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sym = COIN_TO_SYMBOL[coin]
    df = _download_klines_binance(sym, "spot")
    df.to_csv(cache, index=False)
    logger.info("  %s spot: %d rows [%s → %s]",
                coin, len(df), df["ts"].iloc[0].date(), df["ts"].iloc[-1].date())
    return df


# ---------------------------------------------------------------------------
# Task 1c — Hyperliquid cross-check (2023-07 onward)
# ---------------------------------------------------------------------------

def _hl_post(payload: dict, timeout: float = 30.0) -> object:
    """POST to the HL info API."""
    req = urllib.request.Request(
        HL_INFO_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def download_hl_funding(coin: str) -> pd.DataFrame:
    """
    Fetch hourly HL funding rates for `coin` from 2023-07-01 to present.

    HL funding is HOURLY (unlike Binance's 8h). No conversion needed.
    The rate field `fundingRate` is already an hourly fraction, matching engine convention.

    Cached to data/{coin}_hl_funding.csv.
    """
    cache = DATA_DIR / f"{coin}_hl_funding.csv"
    if cache.exists():
        logger.info("Loading cached %s", cache.name)
        df = pd.read_csv(cache)
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
        return df

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Fetching HL funding history for %s from 2023-07-01...", coin)

    # 2023-07-01 00:00 UTC in ms
    start_ms = 1688169600000
    rows: dict[int, float] = {}
    cur = start_ms

    while True:
        try:
            data = _hl_post({"type": "fundingHistory", "coin": coin, "startTime": cur})
        except Exception as e:
            logger.warning("HL fundingHistory failed for %s at %d: %s", coin, cur, e)
            break

        if not data:
            break

        for item in data:
            ts_ms = int(item["time"])
            rate = float(item["fundingRate"])
            rows[ts_ms] = rate

        last_ts = max(int(d["time"]) for d in data)
        if last_ts <= cur:
            break
        cur = last_ts + 1

        # Brief delay to be polite to the HL API
        time.sleep(0.1)

    if not rows:
        logger.warning("No HL funding history returned for %s — cross-check will be skipped", coin)
        return pd.DataFrame(columns=["ts", "funding_hourly"])

    df = pd.DataFrame([{"ts_ms": k, "funding_hourly": v} for k, v in sorted(rows.items())])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df[["ts", "funding_hourly"]]
    df.to_csv(cache, index=False)
    logger.info("  %s HL: %d hours [%s → %s]",
                coin, len(df), df["ts"].iloc[0].date(), df["ts"].iloc[-1].date())
    return df


# ---------------------------------------------------------------------------
# Task 1d — Assemble canonical hourly DataFrame per symbol
# ---------------------------------------------------------------------------

def _expand_funding_to_hourly(funding_df: pd.DataFrame) -> pd.DataFrame:
    """
    Expand 8h-settlement funding rates into an hourly series via forward-fill.

    Each settlement at time T covers the 8 hours ending at T.
    We assign the hourly rate to the exact settlement timestamp and forward-fill
    into a dense hourly index (which is how accrue_funding receives it).
    """
    # Create dense hourly index spanning the full funding period
    start = funding_df["ts"].min().floor("h")
    end = funding_df["ts"].max().ceil("h")
    hourly_idx = pd.date_range(start, end, freq="1h", tz="UTC")

    # Reindex funding to hourly, forward-fill within each 8h window
    f = funding_df.set_index("ts")["funding_hourly"]
    f = f.reindex(hourly_idx, method="ffill")
    return f.reset_index().rename(columns={"index": "ts", 0: "funding_hourly"})


def assemble_hourly(coin: str) -> pd.DataFrame:
    """
    Assemble the canonical hourly DataFrame for `coin`.

    Columns: ts (UTC), funding_hourly, perp_close, spot_close.
    Hours with missing price data are dropped and counted.
    Cached to data/{coin}_hourly.csv.
    """
    cache = DATA_DIR / f"{coin}_hourly.csv"
    if cache.exists():
        logger.info("Loading cached %s", cache.name)
        df = pd.read_csv(cache, parse_dates=["ts"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df

    logger.info("Assembling hourly frame for %s...", coin)
    funding_df, source = download_funding_rates(coin)
    perp_df = download_perp_prices(coin)
    spot_df = download_spot_prices(coin)

    # Expand funding to hourly
    funding_hourly = _expand_funding_to_hourly(funding_df)
    funding_hourly = funding_hourly.set_index("ts")

    # Merge on hour-truncated timestamps
    perp = perp_df.copy()
    perp["ts"] = perp["ts"].dt.floor("h")
    spot = spot_df.copy()
    spot["ts"] = spot["ts"].dt.floor("h")

    perp = perp.set_index("ts")["close"].rename("perp_close")
    spot = spot.set_index("ts")["close"].rename("spot_close")

    merged = funding_hourly.join(perp, how="left").join(spot, how="left")

    # Drop hours with missing price data
    before = len(merged)
    merged = merged.dropna(subset=["perp_close", "spot_close"])
    after = len(merged)
    dropped = before - after
    if dropped:
        logger.info("  %s: dropped %d hours with missing price data", coin, dropped)

    merged = merged.reset_index().rename(columns={"index": "ts"})
    merged = merged[["ts", "funding_hourly", "perp_close", "spot_close"]].sort_values("ts")

    logger.info("  %s: %d hourly rows [%s → %s]  (funding source: %s)",
                coin, len(merged), merged["ts"].iloc[0].date(), merged["ts"].iloc[-1].date(), source)

    merged.to_csv(cache, index=False)
    return merged


def load_all(coins: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """
    Load (or download + assemble) canonical hourly DataFrames for all coins.
    Returns {coin: df} where df has columns: ts, funding_hourly, perp_close, spot_close.
    """
    if coins is None:
        coins = COINS
    return {coin: assemble_hourly(coin) for coin in coins}


def compare_hl_vs_binance(coins: list[str] | None = None) -> pd.DataFrame:
    """
    Per-calendar-quarter comparison of mean annualized funding: Binance vs Hyperliquid.
    Used in Task 1c cross-check section of the report.
    Returns a DataFrame with columns: quarter, coin, binance_ann, hl_ann, diff_pp.
    """
    if coins is None:
        coins = COINS
    records = []
    for coin in coins:
        try:
            hourly_df, _ = download_funding_rates(coin)
            hl_df = download_hl_funding(coin)
        except Exception as e:
            logger.warning("HL cross-check failed for %s: %s", coin, e)
            continue

        if hl_df.empty:
            continue

        # Binance: reconstruct hourly from 8h rates
        b = _expand_funding_to_hourly(hourly_df)
        b["ts"] = pd.to_datetime(b["ts"], utc=True)
        b["q"] = b["ts"].dt.to_period("Q")

        hl = hl_df.copy()
        hl["q"] = hl["ts"].dt.to_period("Q")

        # Overlap from 2023-Q3 onward
        overlap_start = pd.Period("2023Q3")
        b = b[b["q"] >= overlap_start]
        hl = hl[hl["q"] >= overlap_start]

        bq = b.groupby("q")["funding_hourly"].mean() * PERIODS_PER_YEAR
        hq = hl.groupby("q")["funding_hourly"].mean() * PERIODS_PER_YEAR

        for q in sorted(set(bq.index) & set(hq.index)):
            records.append({
                "quarter": str(q),
                "coin": coin,
                "binance_ann": round(bq[q], 4),
                "hl_ann": round(hq[q], 4),
                "diff_pp": round((hq[q] - bq[q]) * 100, 2),
            })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Download all data and print a summary."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    print("=== Carry Backtest — Data Ingest ===\n")
    frames = load_all()
    for coin, df in frames.items():
        print(f"  {coin}: {len(df):,} hourly rows  [{df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()}]")
        print(f"       funding range: [{df['funding_hourly'].min()*100:.4f}%, {df['funding_hourly'].max()*100:.4f}%] per hour")

    print("\nHL cross-check (2023-Q3 onward):")
    comp = compare_hl_vs_binance()
    if not comp.empty:
        print(comp.to_string(index=False))
    else:
        print("  (no HL data available)")

    print(f"\nData cached to: {DATA_DIR}")
    print("\nNext: uv run python -m backtest.sweep")


if __name__ == "__main__":
    main()
