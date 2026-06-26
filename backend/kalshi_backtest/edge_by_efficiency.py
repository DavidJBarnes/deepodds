"""
Edge-by-inefficiency — where is the longshot-short premium fattest?

Thesis (from the #1 finding that temp markets are razor-efficient, Brier 0.014):
the seller premium on cheap longshots should be LARGEST in the least-efficient,
most retail-driven categories (thin MMs, low volume) and SMALLEST where MMs are
sharp. If true, redirect canary capital to high-edge categories — fattening the
edge AND attacking the capacity ceiling (KC-6 was only 4/10 series).

Non-circular design: we correlate per-category longshot EDGE against INDEPENDENT
efficiency proxies that are not the edge itself —
  - avg entry-day volume (liquidity / retail-thinness)
  - avg entry-day intraday range hi-lo cents (MM tightness / uncertainty proxy)
Edge itself = net-of-fee per-contract P&L of selling cheap YES (1-12c) @1-day,
daily-low (pessimistic) fill. Validation window only (2025-07+).
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from collections import defaultdict
from datetime import date

import kalshi_backtest.ingest_s3 as I
from kalshi_backtest.calibration import kalshi_fee_per_contract as _fee
from kalshi_backtest.short_sim import VAL_START_ISO

logger = logging.getLogger("kalshi_backtest.edge_by_efficiency")

BAND = (1, 12)
VOL_FLOOR = 500.0


def build_records(horizon_d=1):
    I.SHARD_DIR = I.DATA_DIR / "s3_markets_low"
    rows = I.load_s3_shards(start=date(2025, 7, 1))
    settle = I.load_settlement_cache()
    try:
        sc = json.loads((I.DATA_DIR / "series_cache.json").read_text())
    except Exception:
        sc = {}
    hists = I.build_market_histories(rows)
    vol = {t: sum(float(r.get("daily_volume") or 0) for r in h) for t, h in hists.items()}
    recs = []
    for t, h in hists.items():
        rt = h[0].get("report_ticker", "")
        if I._is_parlay(rt) or vol.get(t, 0) < VOL_FLOOR:
            continue
        if settle.get(t) not in ("yes", "no"):
            continue
        active = [r for r in h if float(r.get("daily_volume") or 0) > 0
                  or float(r.get("open_interest") or 0) > 0]
        if len(active) < horizon_d + 1:
            continue
        er = active[len(active) - 1 - horizon_d]
        hi, lo = int(er.get("high_cents") or 0), int(er.get("low_cents") or 0)
        if hi <= 0 and lo <= 0:
            continue
        mid = (hi + lo) / 2
        if not (BAND[0] <= mid <= BAND[1]):
            continue
        sell_px = lo / 100.0
        if not (0.0 < sell_px < 1.0):
            continue
        if active[-1]["date"] < VAL_START_ISO:
            continue
        recs.append({
            "ticker": t,
            "category": I.assign_category(rt, sc),
            "sell_px": sell_px,
            "resolved_yes": settle[t] == "yes",
            "entry_vol": float(er.get("daily_volume") or 0),
            "spread": hi - lo,
        })
    # dedup per ticker (first opportunity)
    seen, out = set(), []
    for r in recs:
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"]); out.append(r)
    return out


def _pnl(r):
    fee = _fee(r["sell_px"], 1)
    return (r["sell_px"] - fee) if not r["resolved_yes"] else (-(1 - r["sell_px"]) - fee)


def _spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        for pos, i in enumerate(order):
            rk[i] = pos
        return rk
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    recs = build_records()
    print(f"validation cheap-band(1-12c) shorting records: n={len(recs)}")
    by_cat = defaultdict(list)
    for r in recs:
        by_cat[r["category"]].append(r)

    rows = []
    for cat, rs in by_cat.items():
        if len(rs) < 30:
            continue
        pnls = [_pnl(r) for r in rs]
        n = len(rs)
        edge = statistics.mean(pnls) * 100
        ci = 1.96 * statistics.pstdev(pnls) / math.sqrt(n) * 100
        rows.append({
            "cat": cat, "n": n,
            "edge_c": edge, "ci_lo": edge - ci, "ci_hi": edge - ci + 2 * ci,
            "yes_rate": statistics.mean([r["resolved_yes"] for r in rs]) * 100,
            "avg_sell_c": statistics.mean([r["sell_px"] for r in rs]) * 100,
            "med_vol": statistics.median([r["entry_vol"] for r in rs]),
            "avg_spread": statistics.mean([r["spread"] for r in rs]),
            "capacity_vol": sum(r["entry_vol"] for r in rs),
        })
    rows.sort(key=lambda x: -x["edge_c"])

    print(f"\n{'category':<22}{'n':>5}{'edge¢':>8}{'CI95':>16}{'yes%':>6}"
          f"{'sell¢':>7}{'medVol':>9}{'spread':>8}{'cap_vol':>10}")
    for r in rows:
        ci = f"[{r['ci_lo']:+.2f},{r['ci_hi']:+.2f}]"
        clean = "*" if r["ci_lo"] > 0 else (" " if r["ci_hi"] > 0 else "x")
        print(f"{clean}{r['cat']:<21}{r['n']:>5}{r['edge_c']:>+8.2f}{ci:>16}{r['yes_rate']:>6.1f}"
              f"{r['avg_sell_c']:>7.1f}{r['med_vol']:>9.0f}{r['avg_spread']:>8.1f}{r['capacity_vol']:>10.0f}")

    # thesis test: edge vs INDEPENDENT efficiency proxies
    print("\nThesis — is edge larger where markets are less efficient (thinner)?")
    edges = [r["edge_c"] for r in rows]
    print(f"  Spearman(edge, -log medVol)  = {_spearman(edges, [-math.log(r['med_vol']+1) for r in rows]):+.3f}  "
          f"(positive => fatter edge in THINNER markets)")
    print(f"  Spearman(edge, avg_spread)   = {_spearman(edges, [r['avg_spread'] for r in rows]):+.3f}  "
          f"(positive => fatter edge in WIDER/looser markets)")
    print(f"  * = CI excludes 0 (real edge); x = CI below 0 (negative)")


if __name__ == "__main__":
    main()
