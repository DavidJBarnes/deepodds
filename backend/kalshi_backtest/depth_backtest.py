"""
Depth-as-safety backtest — does liquidity at entry predict longshot-short safety?

Live finding (canary n=133, 2026-06-29): on IDENTICAL markets, flat 1-contract
sizing ran -1.89c/ct while the paper twin's depth-proportional sizing ran +0.57c
-- because the 9 YES losers all had THIN bid depth and got sized small in paper.
Hypothesis: thin-book longshots resolve YES more often (informed money thins the
bid when a bracket is genuinely live); deep-book ones are safe NO.

Instantaneous bid depth isn't in the historical shards, but entry-day VOLUME and
OPEN INTEREST are the liquidity proxies that should carry the same signal. We
stratify the cheap-band (1-12c) 1-day shorting opportunities by each proxy and
measure realized YES-rate + net-of-fee c/ct per bucket. If thin buckets are worse
and a min-depth filter lifts net edge, the live finding is confirmed and a depth
filter (or depth-weighted sizing) is the actionable lever.

Validation window only (settle >= 2025-07-01), daily-low (pessimistic) fill,
deduped per ticker. Reuses ingest_s3 + the canonical short P&L.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import date

import kalshi_backtest.ingest_s3 as I
from kalshi_backtest.calibration import kalshi_fee_per_contract as _fee
from kalshi_backtest.short_sim import VAL_START_ISO

BAND = (1, 12)
VOL_FLOOR = 500.0


def build_records(horizon_d=1):
    """One deduped shorting opportunity per ticker, carrying both depth proxies."""
    I.SHARD_DIR = I.DATA_DIR / "s3_markets_low"
    rows = I.load_s3_shards(start=date(2025, 7, 1))
    settle = I.load_settlement_cache()
    try:
        sc = json.loads((I.DATA_DIR / "series_cache.json").read_text())
    except Exception:
        sc = {}
    hists = I.build_market_histories(rows)
    vol = {t: sum(float(r.get("daily_volume") or 0) for r in h) for t, h in hists.items()}
    recs, seen = [], set()
    for t, h in hists.items():
        rt = h[0].get("report_ticker", "")
        if t in seen or I._is_parlay(rt) or vol.get(t, 0) < VOL_FLOOR:
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
        if not (0.0 < sell_px < 1.0) or active[-1]["date"] < VAL_START_ISO:
            continue
        seen.add(t)
        recs.append({
            "ticker": t,
            "category": I.assign_category(rt, sc),
            "entry_date": er["date"],
            "settle_date": active[-1]["date"],
            "sell_px": sell_px,
            "resolved_yes": settle[t] == "yes",
            "entry_vol": float(er.get("daily_volume") or 0),
            "entry_oi": float(er.get("open_interest") or 0),
        })
    return recs


def _pnl(r):
    fee = _fee(r["sell_px"], 1)
    return (r["sell_px"] - fee) if not r["resolved_yes"] else (-(1 - r["sell_px"]) - fee)


def _agg(rs):
    """net c/ct (mean pnl*100), 95% CI half-width, YES-rate, avg sell, avg proxy."""
    pnls = [_pnl(r) * 100 for r in rs]
    n = len(rs)
    m = statistics.mean(pnls)
    sem = statistics.stdev(pnls) / math.sqrt(n) if n > 1 else float("nan")
    yes = sum(r["resolved_yes"] for r in rs)
    return {
        "n": n, "cents_ct": m, "ci": 1.96 * sem,
        "yes_rate": yes / n, "yes": yes,
        "avg_sell": statistics.mean(r["sell_px"] for r in rs) * 100,
    }


def _quantile_buckets(recs, key, nb=5):
    """Split into nb equal-count buckets by `key` (ascending = thin->thick)."""
    s = sorted(recs, key=lambda r: r[key])
    out = []
    for i in range(nb):
        a = i * len(s) // nb
        b = (i + 1) * len(s) // nb
        chunk = s[a:b]
        if chunk:
            lo, hi = chunk[0][key], chunk[-1][key]
            out.append((f"{key} [{lo:.0f},{hi:.0f}]", chunk))
    return out


def _spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        for pos, i in enumerate(order):
            rk[i] = pos
        return rk
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def _report_buckets(title, recs, key):
    print(f"\n=== {title} (thin -> thick) ===")
    print(f"  {'bucket':28} {'n':>4} {'YES%':>6} {'avg_sell':>8} {'net c/ct':>9} {'95% CI':>9}")
    for label, chunk in _quantile_buckets(recs, key):
        a = _agg(chunk)
        clean = "CLEAN+" if a["cents_ct"] - a["ci"] > 0 else ("CLEAN-" if a["cents_ct"] + a["ci"] < 0 else "")
        print(f"  {label:28} {a['n']:>4} {a['yes_rate']*100:>5.1f}% {a['avg_sell']:>7.2f}c "
              f"{a['cents_ct']:>+8.2f}c +/-{a['ci']:>5.2f} {clean}")


def main():
    logging.basicConfig(level=logging.WARNING)
    recs = build_records()
    base = _agg(recs)
    print(f"validation cheap-band(1-12c) @1d shorting records: n={base['n']}")
    print(f"BASELINE (all): net {base['cents_ct']:+.2f}c/ct +/-{base['ci']:.2f}  "
          f"YES={base['yes_rate']*100:.1f}%  avg_sell={base['avg_sell']:.2f}c")

    _report_buckets("Stratified by ENTRY VOLUME", recs, "entry_vol")
    _report_buckets("Stratified by OPEN INTEREST", recs, "entry_oi")

    # Spearman: does more depth => safer (lower YES) / higher pnl?
    vols = [r["entry_vol"] for r in recs]
    ois = [r["entry_oi"] for r in recs]
    yesf = [1.0 if r["resolved_yes"] else 0.0 for r in recs]
    pnls = [_pnl(r) for r in recs]
    print("\n=== Spearman (rank correlation) ===")
    print(f"  volume vs YES : {_spearman(vols, yesf):+.3f}   volume vs pnl: {_spearman(vols, pnls):+.3f}")
    print(f"  OI     vs YES : {_spearman(ois, yesf):+.3f}   OI     vs pnl: {_spearman(ois, pnls):+.3f}")
    print("  (negative vol-vs-YES / positive vol-vs-pnl => depth = safety, live finding holds)")

    # Min-depth FILTER sweep: net edge of keeping only records above a vol threshold.
    print("\n=== Min-VOLUME filter sweep (keep entries with entry_vol >= thr) ===")
    print(f"  {'thr':>8} {'kept':>5} {'%kept':>6} {'YES%':>6} {'net c/ct':>9} {'95% CI':>9}")
    for thr in (0, 500, 1000, 2000, 5000, 10000, 20000, 50000):
        kept = [r for r in recs if r["entry_vol"] >= thr]
        if len(kept) < 30:
            continue
        a = _agg(kept)
        clean = "CLEAN+" if a["cents_ct"] - a["ci"] > 0 else ""
        print(f"  {thr:>8} {a['n']:>5} {a['n']/base['n']*100:>5.0f}% {a['yes_rate']*100:>5.1f}% "
              f"{a['cents_ct']:>+8.2f}c +/-{a['ci']:>5.2f} {clean}")


if __name__ == "__main__":
    main()


def by_category_oi():
    """Does the OI signal hold WITHIN the canary's traded categories?"""
    from collections import defaultdict
    recs = build_records()
    by_cat = defaultdict(list)
    for r in recs:
        by_cat[r["category"]].append(r)
    print(f"\n########## OI signal WITHIN category (canary trades climate=temp + sports) ##########")
    for cat in sorted(by_cat, key=lambda c: -len(by_cat[c])):
        rs = by_cat[cat]
        if len(rs) < 150:
            continue
        a_all = _agg(rs)
        s = sorted(rs, key=lambda r: r["entry_oi"])
        lo = s[:len(s)//2]; hi = s[len(s)//2:]
        al, ah = _agg(lo), _agg(hi)
        print(f"\n  {cat}  (n={len(rs)}, all={a_all['cents_ct']:+.2f}c YES={a_all['yes_rate']*100:.1f}%)")
        print(f"    LOW-OI half : n={al['n']:4} YES={al['yes_rate']*100:4.1f}% sell={al['avg_sell']:.2f}c net={al['cents_ct']:+.2f}c +/-{al['ci']:.2f}")
        print(f"    HIGH-OI half: n={ah['n']:4} YES={ah['yes_rate']*100:4.1f}% sell={ah['avg_sell']:.2f}c net={ah['cents_ct']:+.2f}c +/-{ah['ci']:.2f}")


def end_to_end():
    """End-to-end collateral-aware bankroll sim: baseline vs low-OI selection filter.

    Runs the same canonical run_short_sim used in VERDICT_LONGSHOT, but pre-filters
    the entry universe by open interest. Tests whether 'prefer low-OI' survives the
    full calendar-concurrency / capital / depth-cap sim, not just per-contract edge.
    """
    import pandas as pd
    from kalshi_backtest.short_sim import run_short_sim, annualized, VAL_START_ISO

    recs = build_records()
    df = pd.DataFrame(recs)
    # OI thresholds from the cross-category quantiles (thin = fat premium)
    variants = [
        ("ALL (baseline)", df),
        ("OI <= median", df[df["entry_oi"] <= df["entry_oi"].median()]),
        ("OI bottom 40%", df[df["entry_oi"] <= df["entry_oi"].quantile(0.40)]),
        ("OI bottom 20%", df[df["entry_oi"] <= df["entry_oi"].quantile(0.20)]),
        ("OI <= 968 (abs)", df[df["entry_oi"] <= 968]),
    ]
    end_iso = "2025-12-03"
    print(f"\n######### END-TO-END bankroll sim (cap=$8k, hz=1d, low-OI filter) #########")
    print(f"  {'variant':18} {'trades':>6} {'hit(NO)':>7} {'final$':>10} {'annROI':>8} {'MaxDD':>7} {'skip c/d':>10}")
    for name, sub in variants:
        if sub.empty:
            continue
        st = run_short_sim(sub.copy(), 8_000.0)
        roi = annualized(st, VAL_START_ISO, end_iso, 8_000.0)
        hr = st.wins / st.total_trades if st.total_trades else 0
        print(f"  {name:18} {st.total_trades:>6} {hr*100:>6.1f}% ${st.bankroll:>9,.0f} "
              f"{roi*100:>+7.1f}% {abs(st.max_drawdown)*100:>6.1f}% "
              f"{st.skipped_capital}/{st.skipped_depth}")

    # Per-contract edge of each variant (size-independent), for honesty vs the sim optics
    print(f"\n  per-contract net edge (size-independent):")
    for name, sub in variants:
        if sub.empty:
            continue
        rs = sub.to_dict("records")
        a = _agg(rs)
        clean = "CLEAN+" if a["cents_ct"] - a["ci"] > 0 else ("CLEAN-" if a["cents_ct"] + a["ci"] < 0 else "")
        print(f"    {name:18} n={a['n']:5} YES={a['yes_rate']*100:4.1f}% sell={a['avg_sell']:.2f}c "
              f"net={a['cents_ct']:+.2f}c +/-{a['ci']:.2f} {clean}")


def reconcile_temp():
    """Why does live-forward temp say HIGH-OI wins while #209 said low-OI wins?
    Slice the historical shards to KXHIGH temp, at the SAME oi_max=968 used live,
    and by season (summer Jul-Aug vs fall Sep-Nov)."""
    recs = [r for r in build_records() if r["ticker"].startswith("KXHIGH")]

    def agg(rs):
        pnls = [_pnl(r) * 100 for r in rs]
        n = len(rs)
        if not n:
            return "n=0"
        m = statistics.mean(pnls)
        sem = statistics.stdev(pnls) / math.sqrt(n) if n > 1 else float("nan")
        yes = sum(r["resolved_yes"] for r in rs)
        sell = statistics.mean(r["sell_px"] for r in rs) * 100
        clean = "CLEAN+" if m - 1.96 * sem > 0 else ("CLEAN-" if m + 1.96 * sem < 0 else "")
        return f"n={n:4} net={m:+.2f}c +/-{1.96*sem:4.2f} YES={yes/n*100:4.1f}% sell={sell:.2f}c {clean}"

    def season(r):
        mo = int(r["entry_date"][5:7])
        return "summer(JJA)" if mo in (6, 7, 8) else "fall(SON)"

    print(f"\n############ RECONCILE: historical KXHIGH temp, oi_max=968 (live threshold) ############")
    print(f"total KXHIGH n={len(recs)}")
    for label, sub in (("ALL SEASONS", recs),
                       ("SUMMER (Jul-Aug)", [r for r in recs if season(r) == "summer(JJA)"]),
                       ("FALL (Sep-Nov)", [r for r in recs if season(r) == "fall(SON)"])):
        kept = [r for r in sub if r["entry_oi"] <= 968]      # low-OI = what live filter TRADES
        drop = [r for r in sub if r["entry_oi"] > 968]       # high-OI = what live filter SKIPS
        print(f"\n  == {label} ==")
        print(f"    KEPT  low-OI (<=968): {agg(kept)}")
        print(f"    DROP  high-OI (>968): {agg(drop)}")

    # finer: quintiles on KXHIGH only
    print(f"\n  == KXHIGH OI quintiles (thin->thick) ==")
    s = sorted(recs, key=lambda r: r["entry_oi"])
    for i in range(5):
        chunk = s[i*len(s)//5:(i+1)*len(s)//5]
        lo, hi = chunk[0]["entry_oi"], chunk[-1]["entry_oi"]
        print(f"    OI[{lo:7.0f},{hi:8.0f}]: {agg(chunk)}")
