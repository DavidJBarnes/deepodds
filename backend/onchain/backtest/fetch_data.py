"""
Download historical BTC price + exchange flow data. Run once; backtest never hits the network.

Usage:
    cd backend
    GLASSNODE_API_KEY=<key> uv run python -m onchain.backtest.fetch_data

Glassnode Studio (free) plan includes basic exchange flow metrics at daily resolution.
If you get a 403, the metric may require a paid tier — see https://glassnode.com/pricing.
"""
import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
PRICES_CSV = DATA_DIR / "btc_prices.csv"
FLOWS_CSV = DATA_DIR / "btc_flows.csv"

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
GLASSNODE_BASE = "https://api.glassnode.com/v1/metrics/transactions"

# 6 years covers 2020-01 → now, giving the full 2021–2025 backtest window plus warmup.
DAYS_HISTORY = 2190


def _get(url: str, params: dict, timeout: int = 30) -> dict | list:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_btc_prices() -> list[dict]:
    logger.info("Fetching BTC prices from CoinGecko (%d days)...", DAYS_HISTORY)
    data = _get(COINGECKO_URL, {"vs_currency": "usd", "days": str(DAYS_HISTORY), "interval": "daily"})
    rows = []
    for ts_ms, price in data["prices"]:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        rows.append({"date": dt.strftime("%Y-%m-%d"), "close": round(price, 2)})
    # CoinGecko sometimes emits a duplicate final row with today's partial candle — deduplicate.
    seen: set[str] = set()
    deduped = []
    for r in rows:
        if r["date"] not in seen:
            seen.add(r["date"])
            deduped.append(r)
    logger.info("  %d price rows (%s → %s)", len(deduped), deduped[0]["date"], deduped[-1]["date"])
    return deduped


def _fetch_glassnode(metric: str, api_key: str) -> dict[str, float]:
    """Fetch a daily Glassnode metric for BTC. Returns {date_str: value}."""
    data = _get(
        f"{GLASSNODE_BASE}/{metric}",
        {"a": "BTC", "i": "24h", "c": "usd", "api_key": api_key},
    )
    out: dict[str, float] = {}
    for item in data:
        dt = datetime.fromtimestamp(item["t"], tz=timezone.utc)
        out[dt.strftime("%Y-%m-%d")] = float(item["v"])
    return out


def fetch_btc_flows(api_key: str) -> list[dict]:
    logger.info("Fetching BTC exchange inflows from Glassnode...")
    inflows = _fetch_glassnode("transfers_volume_to_exchanges_sum", api_key)
    logger.info("  %d inflow rows", len(inflows))

    time.sleep(1.5)  # stay under Glassnode rate limit

    logger.info("Fetching BTC exchange outflows from Glassnode...")
    outflows = _fetch_glassnode("transfers_volume_from_exchanges_sum", api_key)
    logger.info("  %d outflow rows", len(outflows))

    dates = sorted(set(inflows) & set(outflows))
    if not dates:
        raise RuntimeError(
            "No overlapping dates between inflow and outflow series.\n"
            "Check your Glassnode API key and that the free tier includes these metrics."
        )
    rows = [
        {"date": d, "exchange_inflow_usd": inflows[d], "exchange_outflow_usd": outflows[d]}
        for d in dates
    ]
    logger.info("  %d flow rows (%s → %s)", len(rows), rows[0]["date"], rows[-1]["date"])
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

    api_key = os.environ.get("GLASSNODE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "\nGLASSNODE_API_KEY not set.\n"
            "1. Create a free account at https://glassnode.com\n"
            "2. Go to Account → API → generate key\n"
            "3. Re-run: GLASSNODE_API_KEY=<key> uv run python -m onchain.backtest.fetch_data\n"
        )

    prices = fetch_btc_prices()
    _write_csv(prices, PRICES_CSV)

    flows = fetch_btc_flows(api_key)
    _write_csv(flows, FLOWS_CSV)

    print(f"\n✓ Data saved to {DATA_DIR}")
    print(f"  {PRICES_CSV.name}: {len(prices)} rows  [{prices[0]['date']} → {prices[-1]['date']}]")
    print(f"  {FLOWS_CSV.name}: {len(flows)} rows  [{flows[0]['date']} → {flows[-1]['date']}]")
    print("\nNext: uv run python -m onchain.backtest.backtest")


if __name__ == "__main__":
    main()
