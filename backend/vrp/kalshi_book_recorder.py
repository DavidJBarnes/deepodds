"""Kalshi order-book recorder — free MM optionality (strategy parked, data isn't).

Kalshi market-making is un-backtestable today because no public historical order
book exists; the only way it ever becomes evaluable is to start capturing now. Each
tick snapshots the depth of the top open-interest markets on high-volume series ->
dated JSONL.

COARSE v1 by design: REST depth snapshots at a modest interval. A websocket / tick
recorder is the real instrument for adverse-selection analysis (getting picked off
around news) and is the follow-up; this just starts banking the optionality cheaply.
Read-only; places no orders.

    python -m vrp.kalshi_book_recorder --loop --interval 300 --out /data
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone

from longshot.config import load_kalshi_creds
from longshot.kalshi_client import KalshiClient

logger = logging.getLogger("vrp.kalshi_book_recorder")

# High-volume series where MM spread-capture would plausibly live.
DEFAULT_SERIES = ("KXMLBGAME", "KXNBA", "KXWNBAGAME", "KXBTCD", "KXETHD", "KXATPMATCH")


def top_oi_markets(client, series, top_n: int) -> list[str]:
    """Tickers of the top-N open-interest open markets across the given series."""
    rows = []
    for s in series:
        try:
            r = client.get("/markets", params={"series_ticker": s, "status": "open", "limit": 200})
        except Exception as e:
            logger.debug("%s: %s", s, e)
            continue
        for m in r.get("markets", []):
            oi = float(m.get("open_interest_fp") or m.get("open_interest") or 0)
            t = m.get("ticker")
            if t:
                rows.append((oi, t))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in rows[:top_n]]


def snapshot(client, ticker: str) -> dict:
    ob = client.get(f"/markets/{ticker}/orderbook").get("orderbook", {})
    return {"ticker": ticker, "yes": ob.get("yes"), "no": ob.get("no")}


def run_once(client, out_dir: str, series=DEFAULT_SERIES, top_n: int = 30, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    os.makedirs(out_dir, exist_ok=True)
    recs = []
    for t in top_oi_markets(client, series, top_n):
        try:
            s = snapshot(client, t)
            s["ts"] = now.isoformat()
            recs.append(s)
        except Exception as e:
            logger.debug("book %s: %s", t, e)
    if recs:
        with open(os.path.join(out_dir, f"book_{now:%Y%m%d}.jsonl"), "a") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
    logger.info("book tick: %d markets snapshotted", len(recs))
    return len(recs)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.environ.get("BOOKREC_DATA_DIR", "/data"))
    ap.add_argument("--top-n", type=int, default=int(os.environ.get("BOOKREC_TOPN", "30")))
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()
    key_id, pem = load_kalshi_creds()
    while True:
        client = KalshiClient(key_id, pem)
        try:
            run_once(client, args.out, top_n=args.top_n)
        except Exception as e:
            logger.error("book recorder run failed: %s", e)
        finally:
            client.close()
        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
