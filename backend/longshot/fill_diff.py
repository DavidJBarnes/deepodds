"""Read-only fill-quality report for the live longshot canary.

The aggregate ¢/ct blends two different things — which markets each book selected
*and* how well live executed — so it can't answer the Phase-4 gate question on its
own. This module separates them with two pure views over the state files:

  1. LIVE FILL QUALITY (intended vs actual) — self-contained from live records:
     did we fill at the price/size we intended, and at the fee we modelled? This is
     the favorites-killer detector (ghost liquidity / slippage / fee drift).
  2. MATCHED LIVE vs PAPER — on markets BOTH books touched: do live and paper agree
     on entry price and on the resolved outcome? Surfaces coverage/selection gaps.

NEVER mutates state and places no orders — safe to run against prod copies anytime.

    python -m longshot.fill_diff --live /data/state.json --paper /paper/state.json
"""
from __future__ import annotations

import argparse
import json


def live_fill_quality(positions: list[dict]) -> dict:
    """Intended-vs-actual on every live order that carries fill data.

    We SELL YES at the bid, so a *lower* actual price than intended is adverse
    slippage; `slip_cents` is signed (actual − intended), negative = worse for us.
    """
    rows = []
    for p in positions:
        ip, isz = p.get("intended_price"), p.get("intended_size")
        ap, fsz = p.get("avg_fill_price"), p.get("filled_size")
        if None in (ip, isz, ap, fsz):
            continue
        rows.append({
            "ticker": p.get("ticker"),
            "intended_price": ip, "fill_price": ap,
            "slip_cents": round((ap - ip) * 100, 4),
            "intended_size": isz, "filled_size": fsz,
            "fill_ratio": round(fsz / isz, 4) if isz else None,
        })
    n = len(rows)
    if not n:
        return {"n": 0, "rows": []}
    full = sum(1 for r in rows if r["fill_ratio"] is not None and r["fill_ratio"] >= 1.0)
    partial = sum(1 for r in rows if r["fill_ratio"] is not None and 0 < r["fill_ratio"] < 1.0)
    zero = sum(1 for r in rows if r["fill_ratio"] == 0)
    tot_int = sum(r["intended_size"] for r in rows)
    tot_fill = sum(r["filled_size"] for r in rows)
    return {
        "n": n,
        "fill_rate_orders": round(full / n, 4),
        "fill_rate_contracts": round(tot_fill / tot_int, 4) if tot_int else None,
        "partial_orders": partial,
        "zero_fill_orders": zero,
        "mean_slip_cents": round(sum(r["slip_cents"] for r in rows) / n, 4),
        "worst_adverse_slip_cents": min((r["slip_cents"] for r in rows), default=0.0),
        "rows": rows,
    }


def matched_diff(paper_positions: list[dict], live_positions: list[dict]) -> dict:
    """Compare the two books on markets both touched (matched by ticker)."""
    paper = {p["ticker"]: p for p in paper_positions if p.get("ticker")}
    live = {p["ticker"]: p for p in live_positions if p.get("ticker")}
    shared = sorted(set(paper) & set(live))
    rows, price_deltas = [], []
    agree = total = 0
    for t in shared:
        pp, lp = paper[t], live[t]
        dp = None
        if pp.get("sell_price") is not None and lp.get("sell_price") is not None:
            dp = round((lp["sell_price"] - pp["sell_price"]) * 100, 4)
            price_deltas.append(dp)
        pr, lr = pp.get("result"), lp.get("result")
        if pr in ("yes", "no") and lr in ("yes", "no"):
            total += 1
            if pr == lr:
                agree += 1
        rows.append({
            "ticker": t, "paper_sp": pp.get("sell_price"), "live_sp": lp.get("sell_price"),
            "dprice_cents": dp, "paper_result": pr, "live_result": lr,
        })
    return {
        "shared": len(shared),
        "paper_only": len(set(paper) - set(live)),
        "live_only": len(set(live) - set(paper)),
        "mean_price_delta_cents": round(sum(price_deltas) / len(price_deltas), 4) if price_deltas else None,
        "outcome_agreement": f"{agree}/{total}" if total else None,
        "rows": rows,
    }


def report(live_state: dict, paper_state: dict) -> dict:
    return {
        "live_fill_quality": live_fill_quality(live_state.get("positions", [])),
        "matched": matched_diff(paper_state.get("positions", []), live_state.get("positions", [])),
    }


def _print(rep: dict) -> None:
    fq = rep["live_fill_quality"]
    print("== LIVE FILL QUALITY (intended vs actual) — the gate signal ==")
    if fq.get("n"):
        print(f"  orders with fill data:   {fq['n']}")
        print(f"  fully-filled order rate: {fq['fill_rate_orders']:.1%}")
        print(f"  contract fill rate:      {fq['fill_rate_contracts']:.1%}")
        print(f"  partial / zero-fill:     {fq['partial_orders']} / {fq['zero_fill_orders']}")
        print(f"  mean slippage:           {fq['mean_slip_cents']:+.3f}¢  (>0 better; we sell)")
        print(f"  worst adverse slippage:  {fq['worst_adverse_slip_cents']:+.3f}¢")
    else:
        print("  (no live records carry intended/actual fill data yet)")
    m = rep["matched"]
    print("== MATCHED LIVE vs PAPER (same markets) ==")
    print(f"  shared: {m['shared']}  paper-only: {m['paper_only']}  live-only: {m['live_only']}")
    print(f"  mean entry price delta (live−paper): {m['mean_price_delta_cents']}¢")
    print(f"  resolved-outcome agreement:          {m['outcome_agreement']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", required=True, help="path to live state.json")
    ap.add_argument("--paper", required=True, help="path to paper state.json")
    ap.add_argument("--json", action="store_true", help="emit raw JSON instead of a summary")
    args = ap.parse_args()
    with open(args.live) as fh:
        live = json.load(fh)
    with open(args.paper) as fh:
        paper = json.load(fh)
    rep = report(live, paper)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        _print(rep)


if __name__ == "__main__":
    main()
