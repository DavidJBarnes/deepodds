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


def _f(x) -> float | None:
    """Kalshi's *_fp / *_dollars fields are decimal STRINGS ('0.4800'), not numbers."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _levels(raw) -> list[list[float]] | None:
    """[['0.0100','68366.88'], ...] -> [[0.01, 68366.88], ...]. None if absent/empty."""
    if not raw:
        return None
    out = []
    for lvl in raw:
        if not lvl or len(lvl) < 2:
            continue
        p, q = _f(lvl[0]), _f(lvl[1])
        if p is not None and q is not None:
            out.append([p, q])
    return out or None


def top_oi_markets(client, series, top_n: int) -> list[dict]:
    """Top-N open-interest open markets across the given series, richest first.

    Returns the market rows (not bare tickers) so the snapshot can carry top-of-book
    and OI for free — we already paid for them here, and they are the only fields
    that survive if the depth endpoint ever does go dark.
    """
    rows = []
    for s in series:
        try:
            r = client.get("/markets", params={"series_ticker": s, "status": "open", "limit": 200})
        except Exception as e:
            logger.debug("%s: %s", s, e)
            continue
        for m in r.get("markets", []):
            oi = _f(m.get("open_interest_fp")) or _f(m.get("open_interest")) or 0.0
            if m.get("ticker"):
                rows.append((oi, m))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in rows[:top_n]]


def snapshot(client, market: dict) -> dict:
    """Full depth + top-of-book for one market.

    The depth response is {"orderbook_fp": {"yes_dollars": [...], "no_dollars": [...]}}.
    It was ONCE {"orderbook": {"yes": ..., "no": ...}}; reading the old key silently
    banked nulls for weeks (the endpoint was fine all along), so accept both and keep
    the stored field names stable across the rename.
    """
    ticker = market["ticker"]
    r = client.get(f"/markets/{ticker}/orderbook")
    ob = r.get("orderbook_fp") or r.get("orderbook") or {}
    return {
        "ticker": ticker,
        "yes": _levels(ob.get("yes_dollars") if "yes_dollars" in ob else ob.get("yes")),
        "no": _levels(ob.get("no_dollars") if "no_dollars" in ob else ob.get("no")),
        # top-of-book from the market row — free, and independent of the depth endpoint
        "yes_bid": _f(market.get("yes_bid_dollars")),
        "yes_ask": _f(market.get("yes_ask_dollars")),
        "yes_bid_size": _f(market.get("yes_bid_size_fp")),
        "yes_ask_size": _f(market.get("yes_ask_size_fp")),
        "oi": _f(market.get("open_interest_fp")),
    }


def run_once(client, out_dir: str, series=DEFAULT_SERIES, top_n: int = 30, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    os.makedirs(out_dir, exist_ok=True)
    recs = []
    for m in top_oi_markets(client, series, top_n):
        try:
            s = snapshot(client, m)
            s["ts"] = now.isoformat()
            recs.append(s)
        except Exception as e:
            logger.debug("book %s: %s", m.get("ticker"), e)
    if recs:
        with open(os.path.join(out_dir, f"book_{now:%Y%m%d}.jsonl"), "a") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
    # Populated count is the health signal: an all-null tick means the response shape
    # moved again. Log it every tick so it shows up in `docker logs`, not weeks later.
    pop = sum(1 for r in recs if r.get("yes") or r.get("no"))
    if recs and not pop:
        logger.error("book tick: %d markets snapshotted but 0 have depth — response "
                     "shape may have changed; check /markets/{ticker}/orderbook keys", len(recs))
    else:
        logger.info("book tick: %d markets snapshotted, %d with depth", len(recs), pop)
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
