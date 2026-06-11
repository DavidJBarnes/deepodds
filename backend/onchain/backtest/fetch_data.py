"""
Download historical BTC price + exchange flow data. Run once; backtest never hits the network.

Sources (no API key, no account required):
  - Bitfinex public API for daily BTC/USD OHLCV (6yr history, single call)
  - Coin Metrics Community API for BTC exchange flows (6yr history, single call)

Usage:
    cd backend
    uv run python -m onchain.backtest.fetch_data
"""
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
PRICES_CSV = DATA_DIR / "btc_prices.csv"
FLOWS_CSV = DATA_DIR / "btc_flows.csv"

# 2020-01-01 in milliseconds — gives full 2021–2025 backtest window + 90d signal warmup.
_START_MS = 1577836800000
_CANDLE_LIMIT = 5000

BITFINEX_URL = f"https://api-pub.bitfinex.com/v2/candles/trade:1D:tBTCUSD/hist"
COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


def _get(url: str, params: dict, timeout: int = 45) -> dict | list:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_btc_prices() -> list[dict]:
    """
    Fetch daily BTC/USD closes from Bitfinex.
    Response format: [timestamp_ms, open, close, high, low, volume]
    """
    logger.info("Fetching BTC daily prices from Bitfinex...")
    data = _get(BITFINEX_URL, {
        "limit": str(_CANDLE_LIMIT),
        "start": str(_START_MS),
        "sort": "1",  # ascending
    })
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"Unexpected Bitfinex response: {data!r}")

    rows = []
    seen: set[str] = set()
    for candle in data:
        ts_ms, _open, close, _high, _low, _vol = candle[:6]
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d")
        if date_str not in seen:
            seen.add(date_str)
            rows.append({"date": date_str, "close": round(float(close), 2)})

    logger.info("  %d rows  [%s → %s]", len(rows), rows[0]["date"], rows[-1]["date"])
    return rows


def fetch_btc_flows() -> list[dict]:
    """
    Fetch BTC exchange inflow + outflow from Coin Metrics Community API.

    FlowInExUSD  = USD value of BTC transferred into exchanges (selling pressure indicator)
    FlowOutExUSD = USD value of BTC transferred out of exchanges (accumulation indicator)

    No API key or account required.
    """
    logger.info("Fetching BTC exchange flows from Coin Metrics Community API...")
    data = _get(COINMETRICS_URL, {
        "assets": "btc",
        "metrics": "FlowInExUSD,FlowOutExUSD",
        "frequency": "1d",
        "start_time": "2020-01-01",
        "page_size": "10000",
    })

    rows = []
    for item in data.get("data", []):
        date_str = item["time"][:10]
        inflow = item.get("FlowInExUSD")
        outflow = item.get("FlowOutExUSD")
        if inflow is not None and outflow is not None:
            rows.append({
                "date": date_str,
                "exchange_inflow_usd": float(inflow),
                "exchange_outflow_usd": float(outflow),
            })

    if not rows:
        raise RuntimeError(
            "Coin Metrics returned no flow data. Check connectivity and try again."
        )

    rows.sort(key=lambda r: r["date"])
    logger.info("  %d rows  [%s → %s]", len(rows), rows[0]["date"], rows[-1]["date"])
    return rows


def _write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys())
    with open(path, "w") as f:
        f.write(",".join(headers) + "\n")
        for row in rows:
            f.write(",".join(str(row[h]) for h in headers) + "\n")
    logger.info("Wrote %d rows → %s", len(rows), path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    prices = fetch_btc_prices()
    _write_csv(prices, PRICES_CSV)

    flows = fetch_btc_flows()
    _write_csv(flows, FLOWS_CSV)

    print(f"\n✓ Data saved to {DATA_DIR}")
    print(f"  {PRICES_CSV.name}: {len(prices)} rows  [{prices[0]['date']} → {prices[-1]['date']}]")
    print(f"  {FLOWS_CSV.name}: {len(flows)} rows  [{flows[0]['date']} → {flows[-1]['date']}]")
    print("\nNext: uv run python -m onchain.backtest.backtest")


if __name__ == "__main__":
    main()
