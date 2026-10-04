"""Compute the daily metric panel from the upstream sources.

Each metric family returns a list of Metric(key, value, context). `key` is a stable
namespaced string whose daily values form a time series (baseline.py); `value` is a
scalar; `context` carries the numbers a rule needs to write human framing (n, buckets,
sub-values). Families are independent — the daemon wraps each in try/except so one bad
source can't sink the tick, but each function is also internally defensive.

Every metric must be COMPARABLE DAY TO DAY, or its baseline z-score is meaningless.
Three v1 families broke that (found 2026-10-04 reviewing Aug-Oct digests):
  * oracle "last 150 resolved" — 250-780 tails settle per day, so 150 was a few hours
    of one correlated BTC/ETH move. Now: a trailing window in DAYS, with a day-clustered
    standard error so one big-move day can't masquerade as a trend.
  * longshot cumulative-since-inception totals — after 2,600 trades a 2pt drop in the
    recent hit rate barely moves the total. It flagged the $164 P&L peak and missed the
    $116 drawdown after it. Now: trailing-window deltas between history ticks.
  * deribit "nearest expiry" / "furthest expiry" — tenor changed daily (a ~17h daily
    expiry; weekend dips every Saturday), so term-slope "inversions" and skew sign flips
    were calendar artifacts. Now: constant-maturity 7d/30d via total-variance interp.
New keys (not the old ones) so the fixed series never shares a baseline with the
artifacted history; `explorer.backfill` rebuilds their history from the raw sources.

Data schemas (real, verified on the box 2026-07-15 / 2026-10-04):
  resolved tail: {ticker, result(yes/no), kalshi_bid, deribit_fair,
                  sell_ev_vs_deribit, realized_pnl, resolved_ts}   (entry-snapshot prices)
  open tail    : {ticker, close_time, strike, spot, kalshi_bid, kalshi_mid,
                  deribit_fair, gap, sell_ev_vs_deribit, captured_ts}
  longshot tick: {ts, equity, realized_pnl, settled_positions, hit_rate_no,
                  roi_on_settled_collateral, deployed_collateral, ...(+ slippage{orders,
                  fill_rate,avg_slippage_c}, balance, killed, dry_run for live)}
  deribit line : {currency, index_price, captured_ts, instruments:[{instrument_name, mark_iv, ...}]}
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from explorer import sources

_MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
           'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}

ORACLE_WINDOW_DAYS = 14   # trailing settled-tail window for the "recent" oracle metrics
CALIB_WINDOW_DAYS = 30    # 3-5c band calibration needs more n than 14d gives
GATE_MIN_EDGE = 0.005     # mirrors LONGSHOT_ORACLE_MIN_EDGE's default
LONGSHOT_WINDOW_DAYS = 14
LONGSHOT_PNL_LONG_DAYS = 30
TENOR_SHORT_D, TENOR_LONG_D = 7, 30
MIN_EXPIRY_D = 2.0        # sub-2-day expiries are gamma noise; never interpolate off them
ATM_MAX_DIST = 0.05       # ATM strike must be within 5% of spot
SKEW_STRIKE_TOL = 0.03    # 0.9/1.1 wing strikes must land within 3% of spot of target


@dataclass
class Metric:
    key: str
    value: float
    context: dict = field(default_factory=dict)


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _parse_ts(s) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _clustered_mean_se(pairs: list[tuple[str, float]]) -> tuple[float, float | None, int]:
    """Mean of x over (cluster, x) pairs, with a cluster-robust standard error.

    Tails settling on the same day are driven by the same BTC/ETH move, so treating
    them as independent understates the noise ~sqrt(tails/day)-fold. Clustering by day
    gives the honest SE. Returns (mean, se or None if <2 clusters, n_clusters)."""
    n = len(pairs)
    m = sum(x for _, x in pairs) / n
    resid: dict[str, float] = {}
    for g, x in pairs:
        resid[g] = resid.get(g, 0.0) + (x - m)
    G = len(resid)
    if G < 2:
        return m, None, G
    se = math.sqrt(sum(r * r for r in resid.values()) * G / (G - 1)) / n
    return m, se, G


# ---------------------------------------------------------------------------
# oracle — settled tails + open snapshots
# ---------------------------------------------------------------------------
def _resolved_window(res: list[dict], now: datetime, days: int) -> list[dict]:
    lo = now - timedelta(days=days)
    out = []
    for r in res:
        t = _parse_ts(r.get("resolved_ts"))
        if t is not None and lo < t <= now:
            out.append(r)
    return out


def _ev_metric(key: str, rows: list[dict], extra: dict | None = None) -> Metric | None:
    pairs = [(r["resolved_ts"][:10], r["realized_pnl"]) for r in rows
             if r.get("realized_pnl") is not None]
    if not pairs:
        return None
    m, se, g = _clustered_mean_se(pairs)
    ctx = {"n": len(pairs), "n_days": g, "se_c": round(se * 100, 3) if se is not None else None,
           "window_days": ORACLE_WINDOW_DAYS, **(extra or {})}
    return Metric(key, round(m * 100, 3), ctx)


def oracle_metrics(now: datetime | None = None, open_snaps: bool = True) -> list[Metric]:
    now = now or datetime.now(timezone.utc)
    out: list[Metric] = []
    res = sources.resolved_tails()
    recent = _resolved_window(res, now, ORACLE_WINDOW_DAYS)
    if recent:
        bids = [r.get("kalshi_bid") for r in recent]
        fairs = [r.get("deribit_fair") for r in recent]
        gap = _mean([(b - f) for b, f in zip(bids, fairs) if b is not None and f is not None])
        if gap is not None:
            out.append(Metric("oracle.tail14d.gap_settled_c", round(gap * 100, 3),
                              {"n": len(recent),
                               "kalshi_c": round((_mean([b for b in bids if b is not None]) or 0) * 100, 2),
                               "deribit_c": round((_mean([f for f in fairs if f is not None]) or 0) * 100, 2)}))
        yes = [(r["resolved_ts"][:10], 1.0 if r["result"] == "yes" else 0.0)
               for r in recent if r.get("result") in ("yes", "no")]
        if yes:
            m, se, g = _clustered_mean_se(yes)
            out.append(Metric("oracle.tail14d.yes_rate", round(m, 4),
                              {"n": len(yes), "n_days": g, "se": round(se, 4) if se is not None else None}))
        blind = _ev_metric("oracle.tail14d.blind_sell_ev_c", recent)
        if blind:
            out.append(blind)
        # Gate proxy: entry bid - Deribit fair >= min edge. Stricter than the live gate
        # (which uses mid, and bid <= mid) and without its OTM floor (resolved rows carry
        # no spot) — so this is "would the gate's core test have made money", not a
        # replica of the live arm's fills.
        gated = [r for r in recent if (r.get("sell_ev_vs_deribit") or -1) >= GATE_MIN_EDGE]
        gm = _ev_metric("oracle.tail14d.gated_ev_c", gated, {
            "min_edge_c": GATE_MIN_EDGE * 100,
            "yes_pct": round(100 * sum(1 for r in gated if r.get("result") == "yes") / len(gated), 2)
            if gated else None})
        if gm:
            out.append(gm)

    # calibration error in the 3-5c band over a trailing window (the since-inception
    # version hid the fade: 2.07c -> 0.46c in six weeks while the recent rate went ~0)
    mid = [r for r in _resolved_window(res, now, CALIB_WINDOW_DAYS)
           if r.get("kalshi_bid") is not None and 0.03 <= r["kalshi_bid"] <= 0.05 and r.get("result")]
    if len(mid) >= 20:
        actual = sum(1 for r in mid if r["result"] == "yes") / len(mid)
        charge = _mean([r["kalshi_bid"] for r in mid]) or 0
        out.append(Metric("oracle.tail30d.calib_err_mid_c", round((actual - charge) * 100, 3),
                          {"n": len(mid), "actual_yes_pct": round(actual * 100, 2),
                           "charge_c": round(charge * 100, 2)}))

    # forward (open) snapshot gap today
    if open_snaps:
        snaps = sources.open_tail_snapshots()
        gaps = [(s.get("kalshi_mid", 0) - s.get("deribit_fair", 0)) for s in snaps
                if s.get("kalshi_mid") is not None and s.get("deribit_fair") is not None]
        if gaps:
            out.append(Metric("oracle.tail.gap_open_c", round((sum(gaps) / len(gaps)) * 100, 3),
                              {"n": len(gaps)}))
    return out


# ---------------------------------------------------------------------------
# longshot — paper + live harness, trailing-window deltas between ticks
# ---------------------------------------------------------------------------
def _tick_window(hist: list[dict], now: datetime, days: int) -> dict | None:
    """Trailing-window stats from two cumulative ticks: the last at/before `now` and the
    last at/before `now - days`. None until a full window of history exists (a partial
    window would be a different, incomparable quantity)."""
    ticks = sorted(((t, r) for r in hist if (t := _parse_ts(r.get("ts"))) and t <= now),
                   key=lambda tr: tr[0])
    if not ticks:
        return None
    cutoff = now - timedelta(days=days)
    prior = [r for t, r in ticks if t <= cutoff]
    if not prior:
        return None
    a, b = prior[-1], ticks[-1][1]
    na, nb = a.get("settled_positions"), b.get("settled_positions")
    if na is None or nb is None or nb - na <= 0:
        return None
    n = nb - na
    out = {"n": n}
    ha, hb = a.get("hit_rate_no"), b.get("hit_rate_no")
    if ha is not None and hb is not None:
        out["hit_rate_no"] = min(1.0, max(0.0, (hb * nb - ha * na) / n))
    pa, pb = a.get("realized_pnl"), b.get("realized_pnl")
    if pa is not None and pb is not None:
        out["pnl"] = pb - pa
    sa, sb = a.get("slippage") or {}, b.get("slippage") or {}
    oa, ob = sa.get("orders"), sb.get("orders")
    if oa is not None and ob is not None and ob - oa > 0:
        d = ob - oa
        if sa.get("avg_slippage_c") is not None and sb.get("avg_slippage_c") is not None:
            out["slippage_c"] = (sb["avg_slippage_c"] * ob - sa["avg_slippage_c"] * oa) / d
        if sa.get("fill_rate") is not None and sb.get("fill_rate") is not None:
            out["fill_rate"] = (sb["fill_rate"] * ob - sa["fill_rate"] * oa) / d
        out["orders"] = d
    return out


def longshot_metrics(now: datetime | None = None) -> list[Metric]:
    now = now or datetime.now(timezone.utc)
    out: list[Metric] = []
    W = LONGSHOT_WINDOW_DAYS
    paper_hist = sources.longshot_history(live=False)
    live_hist = sources.longshot_history(live=True)
    paper = _tick_window(paper_hist, now, W)
    live = _tick_window(live_hist, now, W)

    if paper:
        if "hit_rate_no" in paper:
            out.append(Metric("longshot.paper.hit_rate_no_14d", round(paper["hit_rate_no"], 4), {"n": paper["n"]}))
        if "pnl" in paper:
            out.append(Metric("longshot.paper.pnl_14d", round(paper["pnl"], 2), {"n": paper["n"]}))
    if live:
        if "hit_rate_no" in live:
            out.append(Metric("longshot.live.hit_rate_no_14d", round(live["hit_rate_no"], 4), {"n": live["n"]}))
        if "pnl" in live:
            out.append(Metric("longshot.live.pnl_14d", round(live["pnl"], 2), {"n": live["n"]}))
        if "slippage_c" in live:
            out.append(Metric("longshot.live.slippage_14d_c", round(live["slippage_c"], 4),
                              {"orders": live.get("orders")}))
        if "fill_rate" in live:
            out.append(Metric("longshot.live.fill_rate_14d", round(live["fill_rate"], 4),
                              {"orders": live.get("orders")}))
    live_long = _tick_window(live_hist, now, LONGSHOT_PNL_LONG_DAYS)
    if live_long and "pnl" in live_long:
        out.append(Metric("longshot.live.pnl_30d", round(live_long["pnl"], 2),
                          {"n": live_long["n"],
                           "hit_rate_no": round(live_long["hit_rate_no"], 4) if "hit_rate_no" in live_long else None,
                           "per_trade": round(live_long["pnl"] / live_long["n"], 4)}))

    # adverse-selection proxy: do live fills resolve YES more than the paper twin?
    if paper and live and "hit_rate_no" in paper and "hit_rate_no" in live:
        diff = paper["hit_rate_no"] - live["hit_rate_no"]  # >0 => live worse (picked off)
        out.append(Metric("longshot.adverse.paper_minus_live_hit_14d", round(diff, 4),
                          {"paper_yes_pct": round((1 - paper["hit_rate_no"]) * 100, 2),
                           "live_yes_pct": round((1 - live["hit_rate_no"]) * 100, 2),
                           "n_paper": paper["n"], "n_live": live["n"]}))
    return out


# ---------------------------------------------------------------------------
# deribit — constant-maturity vol level / skew / term structure per currency
# ---------------------------------------------------------------------------
def _parse_instrument(name: str):
    """'BTC-28AUG26-46000-P' -> (expiry_dt, strike, 'C'|'P') or None."""
    p = name.split("-")
    if len(p) != 4:
        return None
    d, k, typ = p[1], p[2], p[3]
    try:
        exp = datetime(2000 + int(d[-2:]), _MONTHS[d[-5:-2]], int(d[:-5]), 8, 0, tzinfo=timezone.utc)
        return exp, float(k), typ
    except Exception:
        return None


def _surface(line: dict, now: datetime):
    """[(expiry, strike, type, iv)] for instruments with a mark_iv, iv as a fraction."""
    rows = []
    for o in line.get("instruments", []):
        iv = o.get("mark_iv")
        if iv is None:
            continue
        parsed = _parse_instrument(o.get("instrument_name", ""))
        if not parsed:
            continue
        exp, strike, typ = parsed
        if exp <= now:
            continue
        rows.append((exp, strike, typ, iv / 100.0))
    return rows


def _expiry_points(rows, spot: float, now: datetime) -> list[tuple]:
    """[(T_days, atm_iv, skew_or_None, expiry)] per usable expiry, ascending T."""
    by: dict = {}
    for e, k, t, iv in rows:
        by.setdefault(e, []).append((k, t, iv))
    pts = []
    for e in sorted(by):
        T = (e - now).total_seconds() / 86400
        if T < MIN_EXPIRY_D:
            continue
        er = by[e]
        atm_k = min({k for k, _, _ in er}, key=lambda k: abs(k - spot))
        if abs(atm_k - spot) > ATM_MAX_DIST * spot:
            continue
        atm = _mean([iv for k, _, iv in er if k == atm_k])
        skew = None
        puts = [(k, iv) for k, t, iv in er if t == "P" and k < spot]
        calls = [(k, iv) for k, t, iv in er if t == "C" and k > spot]
        if puts and calls:
            pk = min(puts, key=lambda ki: abs(ki[0] - spot * 0.9))
            ck = min(calls, key=lambda ki: abs(ki[0] - spot * 1.1))
            if (abs(pk[0] - spot * 0.9) <= SKEW_STRIKE_TOL * spot
                    and abs(ck[0] - spot * 1.1) <= SKEW_STRIKE_TOL * spot):
                skew = pk[1] - ck[1]
        pts.append((T, atm, skew, e))
    return pts


def _bracket(pts: list[tuple], tau: float):
    for lo, hi in zip(pts, pts[1:]):
        if lo[0] <= tau <= hi[0]:
            return lo, hi
    return None


def _interp_iv(pts, tau: float):
    """ATM IV at constant maturity `tau` days: linear in total variance (iv^2 * T), the
    standard no-calendar-arbitrage interpolation. No extrapolation."""
    br = _bracket(pts, tau)
    if not br:
        return None
    (t1, v1, _, e1), (t2, v2, _, e2) = br
    w1, w2 = v1 * v1 * t1, v2 * v2 * t2
    w = w1 if t2 == t1 else w1 + (w2 - w1) * (tau - t1) / (t2 - t1)
    return math.sqrt(max(w, 0.0) / tau), (e1, e2)


def _interp_skew(pts, tau: float):
    br = _bracket([p for p in pts if p[2] is not None], tau)
    if not br:
        return None
    (t1, _, s1, e1), (t2, _, s2, e2) = br
    s = s1 if t2 == t1 else s1 + (s2 - s1) * (tau - t1) / (t2 - t1)
    return s, (e1, e2)


def deribit_metrics(now: datetime | None = None, chain: list[dict] | None = None) -> list[Metric]:
    now = now or datetime.now(timezone.utc)
    chain = sources.deribit_chain_latest() if chain is None else chain
    out: list[Metric] = []
    for line in chain:
        cur = (line.get("currency") or "").upper()
        spot = line.get("index_price")
        # tenor is measured from the capture, not from when the explorer happens to run
        as_of = _parse_ts(line.get("captured_ts")) or now
        rows = _surface(line, as_of)
        if not cur or not spot or not rows:
            continue
        pts = _expiry_points(rows, spot, as_of)
        short = _interp_iv(pts, TENOR_SHORT_D)
        long_ = _interp_iv(pts, TENOR_LONG_D)
        if long_:
            out.append(Metric(f"deribit.{cur}.atm_iv_30d", round(long_[0], 4),
                              {"bracket": [e.date().isoformat() for e in long_[1]]}))
        if short and long_:
            out.append(Metric(f"deribit.{cur}.term_slope_7_30_pts", round((long_[0] - short[0]) * 100, 3),
                              {"iv_7d": round(short[0], 4), "iv_30d": round(long_[0], 4)}))
        sk = _interp_skew(pts, TENOR_LONG_D)
        if sk:
            out.append(Metric(f"deribit.{cur}.skew_30d_pts", round(sk[0] * 100, 3),
                              {"bracket": [e.date().isoformat() for e in sk[1]]}))
    return out


# ---------------------------------------------------------------------------
# data quality — surface broken / empty upstream sources
# ---------------------------------------------------------------------------
def dataquality_metrics() -> list[Metric]:
    out: list[Metric] = []
    bk = sources.bookrec_latest_stats()
    total = bk.get("total", 0)
    frac = (bk.get("populated", 0) / total) if total else 0.0
    out.append(Metric("dq.bookrec.populated_frac", round(frac, 4),
                      {"file": bk.get("file"), "total": total, "populated": bk.get("populated", 0)}))
    return out


def all_metrics(now: datetime | None = None) -> list[Metric]:
    """Compute the full panel, each family isolated so one failure can't sink the rest."""
    families = [lambda: oracle_metrics(now), lambda: longshot_metrics(now),
                lambda: deribit_metrics(now), dataquality_metrics]
    out: list[Metric] = []
    for fam in families:
        try:
            out.extend(fam())
        except Exception:
            continue
    return out
