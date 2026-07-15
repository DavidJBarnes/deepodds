"""Compute the daily metric panel from the upstream sources.

Each metric family returns a list of Metric(key, value, context). `key` is a stable
namespaced string whose daily values form a time series (baseline.py); `value` is a
scalar; `context` carries the numbers a rule needs to write human framing (n, buckets,
sub-values). Families are independent — the daemon wraps each in try/except so one bad
source can't sink the tick, but each function is also internally defensive.

Data schemas (real, verified on the box 2026-07-15):
  resolved tail: {ticker, result(yes/no), kalshi_bid, deribit_fair,
                  sell_ev_vs_deribit, realized_pnl, resolved_ts}
  open tail    : {ticker, close_time, strike, spot, kalshi_bid, kalshi_mid,
                  deribit_fair, gap, sell_ev_vs_deribit, captured_ts}
  longshot tick: {ts, equity, realized_pnl, hit_rate_no, roi_on_settled_collateral,
                  deployed_collateral, ...(+ slippage{orders,fill_rate,avg_slippage_c},
                  balance, killed, dry_run for live)}
  deribit line : {currency, index_price, instruments:[{instrument_name, mark_iv, ...}]}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from explorer import sources

_MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
           'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}

RECENT_WINDOW = 150  # trailing resolved-tails window for "recent" oracle metrics


@dataclass
class Metric:
    key: str
    value: float
    context: dict = field(default_factory=dict)


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------------------
# oracle — settled tails + open snapshots
# ---------------------------------------------------------------------------
def oracle_metrics() -> list[Metric]:
    out: list[Metric] = []
    res = sources.resolved_tails()
    recent = res[-RECENT_WINDOW:] if res else []
    if recent:
        bids = [r.get("kalshi_bid") for r in recent]
        fairs = [r.get("deribit_fair") for r in recent]
        yes = [1 if r.get("result") == "yes" else 0 for r in recent if r.get("result")]
        pnl = [r.get("realized_pnl") for r in recent]
        gap = _mean([(b - f) for b, f in zip(bids, fairs) if b is not None and f is not None])
        if gap is not None:
            out.append(Metric("oracle.tail.gap_settled_c", round(gap * 100, 3),
                              {"n": len(recent),
                               "kalshi_c": round((_mean([b for b in bids if b is not None]) or 0) * 100, 2),
                               "deribit_c": round((_mean([f for f in fairs if f is not None]) or 0) * 100, 2)}))
        if yes:
            out.append(Metric("oracle.tail.yes_rate", round(sum(yes) / len(yes), 4), {"n": len(yes)}))
        ev = _mean(pnl)
        if ev is not None:
            out.append(Metric("oracle.tail.blind_sell_ev_c", round(ev * 100, 3), {"n": len(recent)}))

    # calibration error in the 3-5c band over the FULL settled set (needs n)
    mid = [r for r in res if r.get("kalshi_bid") is not None
           and 0.03 <= r["kalshi_bid"] <= 0.05 and r.get("result")]
    if len(mid) >= 20:
        actual = sum(1 for r in mid if r["result"] == "yes") / len(mid)
        charge = _mean([r["kalshi_bid"] for r in mid]) or 0
        out.append(Metric("oracle.tail.calib_err_mid_c", round((actual - charge) * 100, 3),
                          {"n": len(mid), "actual_yes_pct": round(actual * 100, 2),
                           "charge_c": round(charge * 100, 2)}))

    # forward (open) snapshot gap today
    snaps = sources.open_tail_snapshots()
    gaps = [(s.get("kalshi_mid", 0) - s.get("deribit_fair", 0)) for s in snaps
            if s.get("kalshi_mid") is not None and s.get("deribit_fair") is not None]
    if gaps:
        out.append(Metric("oracle.tail.gap_open_c", round((sum(gaps) / len(gaps)) * 100, 3),
                          {"n": len(gaps)}))
    return out


# ---------------------------------------------------------------------------
# longshot — paper + live harness health / drift / adverse-selection proxy
# ---------------------------------------------------------------------------
def _latest_tick(hist: list[dict]) -> dict | None:
    return hist[-1] if hist else None


def longshot_metrics() -> list[Metric]:
    out: list[Metric] = []
    paper = _latest_tick(sources.longshot_history(live=False))
    live = _latest_tick(sources.longshot_history(live=True))

    if paper:
        if paper.get("hit_rate_no") is not None:
            out.append(Metric("longshot.paper.hit_rate_no", round(paper["hit_rate_no"], 4), {}))
        if paper.get("roi_on_settled_collateral") is not None:
            out.append(Metric("longshot.paper.roi_settled", round(paper["roi_on_settled_collateral"], 5), {}))
    if live:
        if live.get("hit_rate_no") is not None:
            out.append(Metric("longshot.live.hit_rate_no", round(live["hit_rate_no"], 4), {}))
        if live.get("realized_pnl") is not None:
            out.append(Metric("longshot.live.realized_pnl", round(live["realized_pnl"], 3), {}))
        slip = live.get("slippage") or {}
        if slip.get("avg_slippage_c") is not None:
            out.append(Metric("longshot.live.avg_slippage_c", round(slip["avg_slippage_c"], 4),
                              {"orders": slip.get("orders")}))
        if slip.get("fill_rate") is not None:
            out.append(Metric("longshot.live.fill_rate", round(slip["fill_rate"], 4), {}))

    # adverse-selection proxy: do live fills resolve YES more than the paper twin?
    if paper and live and paper.get("hit_rate_no") is not None and live.get("hit_rate_no") is not None:
        diff = paper["hit_rate_no"] - live["hit_rate_no"]  # >0 => live worse (picked off)
        out.append(Metric("longshot.adverse.paper_minus_live_hit", round(diff, 4),
                          {"paper_yes_pct": round((1 - paper["hit_rate_no"]) * 100, 2),
                           "live_yes_pct": round((1 - live["hit_rate_no"]) * 100, 2)}))
    return out


# ---------------------------------------------------------------------------
# deribit — vol-surface level / skew / term structure per currency
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


def deribit_metrics(now: datetime | None = None) -> list[Metric]:
    now = now or datetime.now(timezone.utc)
    out: list[Metric] = []
    for line in sources.deribit_chain_latest():
        cur = (line.get("currency") or "").upper()
        spot = line.get("index_price")
        rows = _surface(line, now)
        if not cur or not spot or not rows:
            continue
        exps = sorted({e for e, _, _, _ in rows})
        near = exps[0]
        # ATM IV at nearest expiry: avg of the call & put nearest to spot
        near_rows = [(k, t, iv) for e, k, t, iv in rows if e == near]
        atm_k = min({k for k, _, _ in near_rows}, key=lambda k: abs(k - spot))
        atm_ivs = [iv for k, _, iv in near_rows if k == atm_k]
        if atm_ivs:
            out.append(Metric(f"deribit.{cur}.atm_iv", round(sum(atm_ivs) / len(atm_ivs), 4),
                              {"expiry": near.date().isoformat(), "strike": atm_k}))
        # skew: OTM put IV (~0.9*spot) minus OTM call IV (~1.1*spot) at nearest expiry
        puts = [(k, iv) for k, t, iv in near_rows if t == "P" and k < spot]
        calls = [(k, iv) for k, t, iv in near_rows if t == "C" and k > spot]
        if puts and calls:
            pk = min(puts, key=lambda ki: abs(ki[0] - spot * 0.9))
            ck = min(calls, key=lambda ki: abs(ki[0] - spot * 1.1))
            out.append(Metric(f"deribit.{cur}.skew_pts", round((pk[1] - ck[1]) * 100, 3),
                              {"put_iv": round(pk[1], 4), "call_iv": round(ck[1], 4)}))
        # term slope: ATM IV at a ~far expiry minus near
        if len(exps) >= 2:
            far = exps[-1]
            far_rows = [(k, iv) for e, k, t, iv in rows if e == far]
            if far_rows:
                fk = min({k for k, _ in far_rows}, key=lambda k: abs(k - spot))
                fivs = [iv for k, iv in far_rows if k == fk]
                if fivs and atm_ivs:
                    slope = sum(fivs) / len(fivs) - sum(atm_ivs) / len(atm_ivs)
                    out.append(Metric(f"deribit.{cur}.term_slope_pts", round(slope * 100, 3),
                                      {"near": near.date().isoformat(), "far": far.date().isoformat()}))
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
    families = [oracle_metrics, longshot_metrics,
                lambda: deribit_metrics(now), dataquality_metrics]
    out: list[Metric] = []
    for fam in families:
        try:
            out.extend(fam())
        except Exception:
            continue
    return out
