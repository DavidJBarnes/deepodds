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


def slippage_by_size(positions: list[dict], buckets=(1, 2, 5, 10, 25)) -> dict:
    """The fill-at-size read: mean slippage + fill-rate bucketed by filled_size.

    The whole reason we scale beyond 1 contract is to learn whether the book
    actually absorbs size without the price moving against us. Groups live orders
    by how many contracts filled and reports mean slippage (actual-intended, signed;
    <0 = adverse) + fill ratio per bucket. If slippage stays ~0 as size climbs, the
    paper edge is capturable at size; if it degrades, we've found the ceiling.
    """
    rows = []
    for p in positions:
        ip, isz, ap, fsz = (p.get("intended_price"), p.get("intended_size"),
                            p.get("avg_fill_price"), p.get("filled_size"))
        if None in (ip, isz, ap, fsz):
            continue
        rows.append((fsz, round((ap - ip) * 100, 4), fsz / isz if isz else None))
    edges = list(buckets) + [float("inf")]
    out = []
    for lo, hi in zip(edges, edges[1:]):
        grp = [r for r in rows if lo <= r[0] < hi]
        if not grp:
            continue
        slips = [r[1] for r in grp]
        fills = [r[2] for r in grp if r[2] is not None]
        label = f"{int(lo)}" if hi == float("inf") else f"{int(lo)}-{int(hi)-1}"
        out.append({
            "size_bucket": label + ("+" if hi == float("inf") else "ct"),
            "n": len(grp),
            "mean_slip_cents": round(sum(slips) / len(slips), 4),
            "worst_adverse_cents": min(slips),
            "mean_fill_ratio": round(sum(fills) / len(fills), 4) if fills else None,
        })
    return {"n": len(rows), "buckets": out}


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


def oi_split(positions: list[dict], oi_max: float) -> dict:
    """Within-book A/B for the low-OI selection filter (backtest #209).

    Splits SETTLED positions that carry entry_oi into KEPT (entry_oi <= oi_max,
    what the filter would trade) vs DROPPED (what it would skip), and reports
    net ¢/ct + YES-rate for each. A pure-selection A/B on the same universe — no
    second container needed; the filter changes only WHICH markets are opened.
    """
    settled = [p for p in positions
               if p.get("status") == "settled" and p.get("entry_oi") is not None
               and p.get("sell_price") is not None]

    def agg(rs):
        n = len(rs)
        ct = sum(p.get("size") or 0 for p in rs)
        pnl = round(sum(p.get("pnl") or 0 for p in rs), 4)
        yes = sum(1 for p in rs if p.get("result") == "yes")
        return {
            "n": n, "contracts": ct, "pnl": pnl,
            "cents_ct": round(pnl / ct * 100, 4) if ct else None,
            "yes_rate": round(yes / n, 4) if n else None,
        }

    kept = [p for p in settled if (p.get("entry_oi") or 0) <= oi_max]
    dropped = [p for p in settled if (p.get("entry_oi") or 0) > oi_max]
    return {
        "oi_max": oi_max,
        "with_oi": len(settled),
        "all": agg(settled),
        "kept": agg(kept),       # the filtered strategy
        "dropped": agg(dropped),  # what the filter would have avoided
    }


def report(live_state: dict, paper_state: dict, oi_max: float | None = None) -> dict:
    out = {
        "live_fill_quality": live_fill_quality(live_state.get("positions", [])),
        "slippage_by_size": slippage_by_size(live_state.get("positions", [])),
        "matched": matched_diff(paper_state.get("positions", []), live_state.get("positions", [])),
    }
    if oi_max is not None:
        out["paper_oi_split"] = oi_split(paper_state.get("positions", []), oi_max)
        out["live_oi_split"] = oi_split(live_state.get("positions", []), oi_max)
    return out


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
    sz = rep.get("slippage_by_size")
    if sz and sz["buckets"]:
        print("== SLIPPAGE BY FILL SIZE (the fill-at-size read) ==")
        for b in sz["buckets"]:
            fr = f"{b['mean_fill_ratio']*100:.0f}%" if b["mean_fill_ratio"] is not None else "—"
            print(f"  {b['size_bucket']:>6}: n={b['n']:>4} mean_slip={b['mean_slip_cents']:+.3f}¢ "
                  f"worst={b['worst_adverse_cents']:+.3f}¢ fill={fr}")
    m = rep["matched"]
    print("== MATCHED LIVE vs PAPER (same markets) ==")
    print(f"  shared: {m['shared']}  paper-only: {m['paper_only']}  live-only: {m['live_only']}")
    print(f"  mean entry price delta (live−paper): {m['mean_price_delta_cents']}¢")
    print(f"  resolved-outcome agreement:          {m['outcome_agreement']}")
    for label, key in (("PAPER", "paper_oi_split"), ("LIVE", "live_oi_split")):
        s = rep.get(key)
        if not s:
            continue
        print(f"== {label} LOW-OI A/B (oi_max={s['oi_max']:.0f}, settled w/ OI={s['with_oi']}) ==")
        for sub in ("all", "kept", "dropped"):
            a = s[sub]
            yr = f"{a['yes_rate']*100:.1f}%" if a['yes_rate'] is not None else "—"
            cc = f"{a['cents_ct']:+.2f}¢" if a['cents_ct'] is not None else "—"
            print(f"  {sub:8} n={a['n']:>4} ct={a['contracts']:>5} pnl=${a['pnl']:>+8.2f} "
                  f"net={cc:>8} YES={yr}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", required=True, help="path to live state.json")
    ap.add_argument("--paper", required=True, help="path to paper state.json")
    ap.add_argument("--oi-max", type=float, default=None,
                    help="if set, also report the low-OI A/B split at this cap (e.g. 968)")
    ap.add_argument("--json", action="store_true", help="emit raw JSON instead of a summary")
    args = ap.parse_args()
    with open(args.live) as fh:
        live = json.load(fh)
    with open(args.paper) as fh:
        paper = json.load(fh)
    rep = report(live, paper, oi_max=args.oi_max)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        _print(rep)


if __name__ == "__main__":
    main()
