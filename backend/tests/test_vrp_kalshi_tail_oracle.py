"""Unit tests for the Kalshi-tail vs Deribit-fair oracle math + scan filtering.
No network — Deribit surface + Kalshi client are faked."""
import math
from datetime import datetime, timezone

import vrp.kalshi_tail_oracle as o

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CLOSE = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_norm_cdf_basics():
    assert abs(o._norm_cdf(0) - 0.5) < 1e-9
    assert o._norm_cdf(3) > 0.99 and o._norm_cdf(-3) < 0.01


def test_deribit_fair_prob_far_tail_is_small():
    # deep OTM upper tail (K well above spot) -> small risk-neutral prob
    calls = {(CLOSE, 60000.0): 0.5}
    p = o.deribit_fair_prob(60000.0, calls, 72000.0, CLOSE, NOW)
    assert 0.0 < p < 0.1


def test_deribit_fair_prob_atm_near_half():
    calls = {(CLOSE, 60000.0): 0.5}
    p = o.deribit_fair_prob(60000.0, calls, 60000.0, CLOSE, NOW)
    assert 0.4 < p < 0.55        # ATM ~0.5 (minus small drift)


def test_deribit_fair_prob_guards():
    assert o.deribit_fair_prob(60000, {}, 70000, CLOSE, NOW) is None       # no surface
    assert o.deribit_fair_prob(60000, {(CLOSE, 60000.0): 0.5}, 70000, NOW, NOW) is None  # tau<=0


class _FakeClient:
    def __init__(self, markets):
        self._m = markets

    def get(self, path, params=None):
        return {"markets": self._m}


def test_scan_filters_to_cheap_upper_tails(monkeypatch):
    monkeypatch.setattr(o, "deribit_call_surface", lambda cur="BTC": (60000.0, {(CLOSE, 60000.0): 0.5}))
    markets = [
        # cheap upper tail (K>spot, mid in band) -> KEPT
        {"strike_type": "greater", "yes_bid_dollars": "0.03", "yes_ask_dollars": "0.05",
         "floor_strike": 72000.0, "ticker": "T72k", "close_time": "2026-01-02T00:00:00Z"},
        # deep ITM (mid ~0.9) -> dropped (out of band)
        {"strike_type": "greater", "yes_bid_dollars": "0.89", "yes_ask_dollars": "0.91",
         "floor_strike": 50000.0, "ticker": "T50k", "close_time": "2026-01-02T00:00:00Z"},
        # below spot (K<spot) -> dropped (not an upper tail)
        {"strike_type": "greater", "yes_bid_dollars": "0.05", "yes_ask_dollars": "0.06",
         "floor_strike": 55000.0, "ticker": "T55k", "close_time": "2026-01-02T00:00:00Z"},
    ]
    rows = o.scan(_FakeClient(markets), now=NOW)
    assert len(rows) == 1 and rows[0]["ticker"] == "T72k"
    row = rows[0]
    assert row["deribit_fair"] < row["kalshi_mid"]          # Kalshi richer than Deribit here
    assert row["sell_ev_vs_deribit"] == round(row["kalshi_bid"] - row["deribit_fair"], 4)
