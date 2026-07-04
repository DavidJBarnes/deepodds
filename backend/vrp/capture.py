"""Deribit option-chain daily snapshot collector — the UNBIASED data foundation
for the variance-risk-premium (VRP) backtest.

The lesson from longshot (VERDICT_BACKTEST_BIAS.md) is that a cheap/survivor-selected
data source silently inflates edge. So we capture the FULL live chain every run —
every strike and expiry, including the deep-OTM options that will later expire
worthless — and never delete. A forward-built dataset from complete snapshots has
NO survivorship bias by construction: the options that expire worthless are already
in the record, timestamped, at the price we could have sold them.

One `get_book_summary_by_currency` call per currency returns, per instrument:
mark_price, mark_iv, bid/ask, open_interest, volume, underlying_price — everything
needed to price and fill a VRP short. `instrument_name` (e.g. BTC-28AUG26-105000-C)
encodes expiry/strike/type, so no join is required.

    python -m vrp.capture --currencies BTC,ETH --out /data/vrp

Idempotent per day: appends one snapshot record per currency; safe to run hourly or
daily. Public endpoint, no auth, read-only — captures nothing but public market data.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone

API = "https://www.deribit.com/api/v2/public"
logger = logging.getLogger("vrp.capture")


def _get(path: str, **params) -> dict | list:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API}/{path}?{q}"
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)["result"]
        except Exception as e:  # transient network / rate limit
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"deribit {path} failed after retries: {last}")


def snapshot_currency(cur: str) -> dict:
    """Full option-chain snapshot for one currency."""
    summary = _get("get_book_summary_by_currency", currency=cur, kind="option")
    try:
        idx = _get("get_index_price", index_name=f"{cur.lower()}_usd").get("index_price")
    except Exception:
        idx = None
    # keep only the fields the backtest needs, to bound file growth
    keep = ("instrument_name", "mark_price", "mark_iv", "bid_price", "ask_price",
            "mid_price", "open_interest", "volume", "underlying_price", "underlying_index")
    instruments = [{k: r.get(k) for k in keep} for r in summary]
    return {"currency": cur, "index_price": idx, "n_instruments": len(instruments),
            "instruments": instruments}


def capture(currencies: list[str], out_dir: str) -> tuple[str, int]:
    """Append one snapshot record per currency to a dated JSONL file. Returns
    (path, total_instruments_captured)."""
    ts = datetime.now(timezone.utc)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"chain_{ts:%Y%m%d}.jsonl")
    total = 0
    with open(path, "a") as fh:
        for cur in currencies:
            snap = snapshot_currency(cur)
            snap["captured_ts"] = ts.isoformat()
            fh.write(json.dumps(snap) + "\n")
            total += snap["n_instruments"]
            logger.info("captured %s: %d instruments, underlying=%s",
                        cur, snap["n_instruments"], snap.get("index_price"))
    return path, total


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Deribit option-chain snapshot collector")
    ap.add_argument("--currencies", default="BTC,ETH", help="comma-separated, e.g. BTC,ETH")
    ap.add_argument("--out", default=os.environ.get("VRP_DATA_DIR", "/data/vrp"),
                    help="output directory for dated JSONL snapshots")
    args = ap.parse_args()
    curs = [c.strip().upper() for c in args.currencies.split(",") if c.strip()]
    path, n = capture(curs, args.out)
    logger.info("snapshot written: %s (%d instruments across %d currencies)", path, n, len(curs))


if __name__ == "__main__":
    main()
