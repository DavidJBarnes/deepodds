"""Oracle gate: crypto-tails arm sells a Kalshi tail only when its mid exceeds the
Deribit risk-neutral fair by >= min_edge. Default OFF; fail-closed on Deribit error."""
from datetime import datetime, timezone

import pytest

from longshot.config import LongshotConfig
from longshot import paper_run
from vrp import kalshi_tail_oracle as kto

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
CLOSE = datetime(2030, 1, 2, tzinfo=timezone.utc)
CLOSE_ISO = "2030-01-02T00:00:00Z"


def _mkt(strike, bid, ticker="KXBTCD-30JAN01-Tx"):
    return {"ticker": ticker, "strike_type": "greater", "floor_strike": strike,
            "yes_bid_dollars": bid, "yes_ask_dollars": bid, "yes_bid_size_fp": 1000.0,
            "close_time": CLOSE_ISO, "open_interest_fp": 500.0}


# surface: spot 60k, iv 0.5 for the one node
SURF = {"BTC": (60000.0, {(CLOSE, 60000.0): 0.5}), "ETH": (2000.0, {(CLOSE, 2000.0): 0.5})}


def test_market_passes_overpriced_tail():
    # deep upper tail: Deribit fair is tiny; Kalshi pricing it at 5c is overpriced -> passes
    assert kto.market_passes(SURF, _mkt(72000.0, 0.05), NOW, min_edge=0.005) is True


def test_market_fails_when_kalshi_near_deribit():
    # price it at ~fair (near-zero) -> gap below min_edge -> fails
    assert kto.market_passes(SURF, _mkt(72000.0, 0.005), NOW, min_edge=0.02) is False


def test_market_fails_non_greater_and_below_spot():
    assert kto.market_passes(SURF, {**_mkt(72000.0, 0.05), "strike_type": "less"}, NOW, 0.005) is False
    assert kto.market_passes(SURF, _mkt(55000.0, 0.05), NOW, 0.005) is False   # K<=spot


def test_default_gate_off():
    assert LongshotConfig().oracle_gate_enabled is False


class _Client:
    def __init__(self, markets):
        self._m = markets
    def get(self, path, params=None):
        return {"markets": self._m}


def _cfg(gate, min_edge=0.005):
    c = LongshotConfig()
    c.whitelist = ("KXBTCD",)
    c.oracle_gate_enabled = gate
    c.oracle_min_edge = min_edge
    c.trade_fraction = 0.02
    return c


def test_discover_gates_out_fairpriced(monkeypatch):
    monkeypatch.setattr(paper_run._oracle, "build_surfaces", lambda: SURF)
    markets = [_mkt(72000.0, 0.05, "KXBTCD-a-T1"),   # overpriced -> kept
               _mkt(72000.0, 0.005, "KXBTCD-a-T2")]  # ~fair -> gated out
    cands = paper_run.discover_candidates(_cfg(True), _Client(markets), NOW, set(), 0.0, account=1000.0)
    tickers = {c["ticker"] for c in cands}
    assert "KXBTCD-a-T1" in tickers and "KXBTCD-a-T2" not in tickers


def test_discover_fail_closed_when_deribit_down(monkeypatch):
    def boom():
        raise RuntimeError("deribit down")
    monkeypatch.setattr(paper_run._oracle, "build_surfaces", boom)
    cands = paper_run.discover_candidates(_cfg(True), _Client([_mkt(72000.0, 0.05)]), NOW, set(), 0.0, account=1000.0)
    assert cands == []          # fail-closed: no oracle -> no orders


def test_discover_gate_off_ignores_oracle(monkeypatch):
    # gate off -> build_surfaces never called, all band candidates admitted
    def boom():
        raise AssertionError("should not fetch surfaces when gate off")
    monkeypatch.setattr(paper_run._oracle, "build_surfaces", boom)
    cands = paper_run.discover_candidates(_cfg(False), _Client([_mkt(72000.0, 0.05)]), NOW, set(), 0.0, account=1000.0)
    assert len(cands) == 1
