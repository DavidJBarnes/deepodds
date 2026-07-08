"""Deribit-oracle capture daemon — the forward dataset that proves the edge.

Each run:
  1. SNAPSHOT every cheap KXBTCD/KXETHD tail with its Deribit risk-neutral fair
     value (vrp.kalshi_tail_oracle.scan) -> append to a dated JSONL.
  2. RESOLVE any previously captured tail whose market has since closed, by looking
     up its Kalshi result -> append to resolved.jsonl with the entry price + fair.

Over time this is an UNBIASED forward record: for each tail, the Kalshi price we
could have sold at, the sharp-market (Deribit) fair prob at entry, and the realized
YES/NO. That's what turns the +1.18c/ct SNAPSHOT into a settlement-proven edge (or
kills it) across regimes. Read-only vs Kalshi/Deribit; places no orders.

    python -m vrp.oracle_daemon --loop --interval 3600 --out /data
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import time
from datetime import datetime, timezone

from longshot.config import load_kalshi_creds
from longshot.kalshi_client import KalshiClient
from vrp.kalshi_tail_oracle import scan

logger = logging.getLogger("vrp.oracle_daemon")
SERIES = {"KXBTCD": "BTC", "KXETHD": "ETH"}


def _append(path: str, records: list) -> None:
    if not records:
        return
    with open(path, "a") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def capture(client, out_dir: str, now: datetime) -> int:
    """Append current tail snapshots to the dated file. Returns count."""
    os.makedirs(out_dir, exist_ok=True)
    snaps = []
    for series, cur in SERIES.items():
        try:
            snaps += scan(client, series=series, currency=cur, now=now)
        except Exception as e:  # one venue/series failing must not sink the tick
            logger.warning("scan %s failed: %s", series, e)
    _append(os.path.join(out_dir, f"oracle_{now:%Y%m%d}.jsonl"), snaps)
    return len(snaps)


def _load_resolved(out_dir: str) -> set:
    done = set()
    p = os.path.join(out_dir, "resolved.jsonl")
    if os.path.exists(p):
        for line in open(p):
            try:
                done.add(json.loads(line)["ticker"])
            except Exception:
                pass
    return done


def resolve_pending(client, out_dir: str, now: datetime, cap: int = 300) -> int:
    """Look up the outcome of captured tails that have since closed. Idempotent
    (skips tickers already in resolved.jsonl). Returns count newly resolved."""
    done = _load_resolved(out_dir)
    pending: dict = {}
    for f in sorted(glob.glob(os.path.join(out_dir, "oracle_*.jsonl"))):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            t, ct = r.get("ticker"), r.get("close_time")
            if not t or not ct or t in done or t in pending:
                continue
            try:
                if datetime.fromisoformat(ct.replace("Z", "+00:00")) < now:
                    pending[t] = r
            except Exception:
                continue
    out = []
    for t in list(pending)[:cap]:
        try:
            m = client.get(f"/markets/{t}").get("market", {})
        except Exception as e:
            logger.debug("resolve %s: %s", t, e)
            continue
        res = (m.get("result") or "").lower()
        if res not in ("yes", "no"):
            continue
        e = pending[t]
        bid = e.get("kalshi_bid")
        # realized short-YES pnl per contract (sold at bid; NO=win, YES=loss), fee~0 at tails
        pnl = bid if res == "no" else (-(1 - bid) if bid is not None else None)
        out.append({"ticker": t, "result": res, "kalshi_bid": bid,
                    "deribit_fair": e.get("deribit_fair"),
                    "sell_ev_vs_deribit": e.get("sell_ev_vs_deribit"),
                    "realized_pnl": pnl, "resolved_ts": now.isoformat()})
    _append(os.path.join(out_dir, "resolved.jsonl"), out)
    return len(out)


def run_once(client, out_dir: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    n_snap = capture(client, out_dir, now)
    n_res = resolve_pending(client, out_dir, now)
    logger.info("oracle tick: captured=%d resolved=%d", n_snap, n_res)
    return {"captured": n_snap, "resolved": n_res}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.environ.get("ORACLE_DATA_DIR", "/data"))
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=3600)
    args = ap.parse_args()
    key_id, pem = load_kalshi_creds()
    while True:
        client = KalshiClient(key_id, pem)
        try:
            run_once(client, args.out)
        except Exception as e:
            logger.error("oracle run failed: %s", e)
        finally:
            client.close()
        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
