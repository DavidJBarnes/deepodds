"""Kalshi crypto tail vs Deribit fair-value oracle — the '#4 with oracle' engine.

The idea (credit: user pushback, 2026-07-08): Deribit is the sharp crypto vol venue;
its risk-neutral prob for "BTC >= K by T" is the best free estimate of the true tail
probability. Kalshi retail systematically OVERPRICES those same tails. So instead of
selling Kalshi tails blindly (whose YES rate can run high when crypto gaps), sell ONLY
when Kalshi-implied exceeds Deribit-implied by a threshold. That's "rent the sharper
venue's price" applied to our surviving archetype (sell overpriced tail premium) — not
forecasting.

Validated as a LIVE SNAPSHOT (2026-07-08, BTC ~$62k): across 27 KXBTCD upper-tail
markets in the 1-12c band, Kalshi-implied 2.87c vs Deribit-fair 0.79c, Kalshi richer on
100%, mean gap +2.08c, EV of selling at Kalshi bid vs Deribit-fair +1.18c/contract, and
Kalshi fee ~0 at tail prices. STRONG but a single snapshot — must be forward-validated
through settlement across regimes (this module is the capture that builds that dataset).

CAVEATS baked in: (1) N(d2) with nearest Deribit expiry/strike is an approximation;
(2) upper-tail-only 'greater' markets are a DIRECTIONAL short-BTC-upside book, not
delta-neutral -> a per-underlying correlation cap is mandatory before any live use;
(3) Deribit-fair is a strong prior, not ground truth.

Run against the live Kalshi client (has creds); Deribit is public.
"""
from __future__ import annotations

import math
import urllib.request
import json
from datetime import datetime, timezone

DERIBIT = "https://www.deribit.com/api/v2/public"
_MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
          'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}


def _dget(path: str):
    with urllib.request.urlopen(f"{DERIBIT}/{path}", timeout=20) as r:
        return json.load(r)["result"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def deribit_call_surface(currency: str = "BTC"):
    """Returns (spot, {(expiry_dt, strike): iv}) for calls with a mark IV."""
    spot = _dget(f"get_index_price?index_name={currency.lower()}_usd")["index_price"]
    summ = _dget(f"get_book_summary_by_currency?currency={currency}&kind=option")
    calls = {}
    for o in summ:
        nm = o["instrument_name"].split("-")
        if len(nm) != 4 or nm[3] != "C" or o.get("mark_iv") is None:
            continue
        d = nm[1]
        try:
            exp = datetime(2000 + int(d[-2:]), _MONTHS[d[-5:-2]], int(d[:-5]), 8, 0, tzinfo=timezone.utc)
        except Exception:
            continue
        calls[(exp, float(nm[2]))] = o["mark_iv"] / 100.0
    return spot, calls


def deribit_fair_prob(spot: float, calls: dict, K: float, close_dt: datetime, now: datetime) -> float | None:
    """Risk-neutral P(S_T >= K) from the nearest Deribit expiry/strike IV (r=0)."""
    tau = (close_dt - now).total_seconds() / 3600 / 8760
    if tau <= 0 or not calls:
        return None
    exps = sorted({e for e, _ in calls})
    exp = min(exps, key=lambda e: abs((e - close_dt).total_seconds()))
    ks = [k for (e, k) in calls if e == exp]
    iv = calls[(exp, min(ks, key=lambda k: abs(k - K)))]
    if iv <= 0:
        return None
    d2 = (math.log(spot / K) - 0.5 * iv * iv * tau) / (iv * math.sqrt(tau))
    return _norm_cdf(d2)


def build_surfaces(currencies=("BTC", "ETH")) -> dict:
    """Pre-fetch Deribit call surfaces once per discovery tick (network)."""
    return {cur: deribit_call_surface(cur) for cur in currencies}


def _currency_of(ticker: str) -> str | None:
    t = (ticker or "").upper()
    if t.startswith("KXBTC"):
        return "BTC"
    if t.startswith("KXETH"):
        return "ETH"
    return None


def market_passes(surfaces: dict, m: dict, now: datetime, min_edge: float, min_otm: float = 0.0) -> bool:
    """Oracle gate: True only for an upper-tail 'greater' market that is (a) at least
    `min_otm` fraction OTM (strike vs spot — a MODEL-FREE floor that excludes near-money
    short-horizon tails our BS fair can't price), AND (b) whose Kalshi mid exceeds
    Deribit's risk-neutral fair by >= min_edge. Everything else is skipped."""
    if m.get("strike_type") != "greater":
        return False
    cur = _currency_of(m.get("ticker", ""))
    if cur not in surfaces:
        return False
    K, yb, ya, ct = (m.get("floor_strike"), m.get("yes_bid_dollars"),
                     m.get("yes_ask_dollars"), m.get("close_time"))
    if None in (K, yb, ya, ct):
        return False
    K, mid = float(K), (float(yb) + float(ya)) / 2
    spot, calls = surfaces[cur]
    if K <= spot * (1.0 + min_otm):           # near-money exclusion (and K>spot)
        return False
    fair = deribit_fair_prob(spot, calls, K, datetime.fromisoformat(ct.replace("Z", "+00:00")), now)
    if fair is None:
        return False
    return (mid - fair) >= min_edge


def scan(client, series="KXBTCD", currency="BTC", band=(0.01, 0.12), now=None) -> list[dict]:
    """One snapshot: for each cheap upper-tail Kalshi threshold, the Kalshi price,
    the Deribit-fair prob, the gap, and the sell-EV vs Deribit. Mutates nothing."""
    now = now or datetime.now(timezone.utc)
    spot, calls = deribit_call_surface(currency)
    out = []
    r = client.get("/markets", params={"series_ticker": series, "status": "open", "limit": 1000})
    for m in r.get("markets", []):
        if m.get("strike_type") != "greater":
            continue
        yb, ya, K = m.get("yes_bid_dollars"), m.get("yes_ask_dollars"), m.get("floor_strike")
        if None in (yb, ya, K):
            continue
        yb, ya, K = float(yb), float(ya), float(K)
        mid = (yb + ya) / 2
        if not (band[0] <= mid <= band[1]) or K <= spot:
            continue
        ct = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        fair = deribit_fair_prob(spot, calls, K, ct, now)
        if fair is None:
            continue
        out.append({
            "ticker": m["ticker"], "close_time": m["close_time"], "strike": K, "spot": spot,
            "kalshi_bid": yb, "kalshi_mid": round(mid, 4), "deribit_fair": round(fair, 4),
            "gap": round(mid - fair, 4), "sell_ev_vs_deribit": round(yb - fair, 4),
            "captured_ts": now.isoformat(),
        })
    return out
