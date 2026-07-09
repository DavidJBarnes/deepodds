"""Oracle gate report — quantifies the gate from the daemon's settled dataset.

Joins each settled tail (resolved.jsonl) to its entry snapshot (oracle_*.jsonl) and
splits by whether the oracle gate would have sold it (kalshi_mid - deribit_fair >=
min_edge). Emits ALL / GATED / REJECTED with n, YES%, avg bid/fair, net c/ct — the
one-glance proof that the gate turns a losing blind strategy into a winning gated one
(2026-07-09: ungated -1.26c, gated +2.17c, rejected -4.51c over n=72).

    python -m vrp.oracle_report --dir /data --min-edge 0.005
"""
from __future__ import annotations

import argparse
import glob
import json
import os


def _pnl(bid: float, result: str) -> float:
    """Realized short-YES pnl/contract: sold at bid; NO=win(+bid), YES=loss(-(1-bid))."""
    return bid if result == "no" else -(1 - bid)


def load(data_dir: str) -> list[dict]:
    """Settled tails joined to their FIRST entry snapshot (gap/bid/fair at capture)."""
    resolved = {}
    rp = os.path.join(data_dir, "resolved.jsonl")
    if os.path.exists(rp):
        for line in open(rp):
            try:
                r = json.loads(line)
                resolved[r["ticker"]] = r
            except Exception:
                pass
    entry = {}
    for f in sorted(glob.glob(os.path.join(data_dir, "oracle_*.jsonl"))):
        for line in open(f):
            try:
                s = json.loads(line)
            except Exception:
                continue
            t = s.get("ticker")
            if t in resolved and t not in entry:
                entry[t] = s
    rows = []
    for t, r in resolved.items():
        s = entry.get(t)
        if not s:
            continue
        rows.append({"gap": s.get("gap") or 0.0, "bid": s.get("kalshi_bid") or 0.0,
                     "fair": s.get("deribit_fair") or 0.0, "result": r.get("result")})
    return rows


def _agg(rs: list[dict]) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0}
    yes = sum(1 for x in rs if x["result"] == "yes")
    tp = sum(_pnl(x["bid"], x["result"]) for x in rs)
    return {"n": n, "yes": yes, "yes_pct": round(yes / n * 100, 1),
            "avg_bid_c": round(sum(x["bid"] for x in rs) / n * 100, 2),
            "avg_fair_c": round(sum(x["fair"] for x in rs) / n * 100, 2),
            "net_c": round(tp / n * 100, 2)}


def summarize(rows: list[dict], min_edge: float = 0.005) -> dict:
    return {"all": _agg(rows),
            "gated": _agg([x for x in rows if x["gap"] >= min_edge]),
            "rejected": _agg([x for x in rows if x["gap"] < min_edge])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=os.environ.get("ORACLE_DATA_DIR", "/data"))
    ap.add_argument("--min-edge", type=float, default=0.005)
    args = ap.parse_args()
    rep = summarize(load(args.dir), args.min_edge)
    print(f"oracle gate report (min_edge={args.min_edge}):")
    for k in ("all", "gated", "rejected"):
        a = rep[k]
        if a["n"]:
            print(f"  {k:9} n={a['n']:3} YES={a['yes_pct']:>4}% avg_bid={a['avg_bid_c']:>5}c "
                  f"avg_fair={a['avg_fair_c']:>5}c net={a['net_c']:+.2f}c/ct")
        else:
            print(f"  {k:9} n=0")


if __name__ == "__main__":
    main()
