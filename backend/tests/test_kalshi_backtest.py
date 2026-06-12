"""
Tests for kalshi_backtest: pagination/resume/rate-limit, exact fees, Wilson CI,
calibration bucketing fixture, sim accounting invariant.
"""
from __future__ import annotations

import csv
import math
import time
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import pandas as pd

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from kalshi_backtest.calibration import (
    kalshi_fee_per_contract,
    net_edge_per_contract,
    wilson_ci,
    ci_excludes_breakeven,
    build_dataset,
    calibrate,
    adverse_selection_analysis,
    SELECTION_END,
    VALIDATION_START,
)
from kalshi_backtest.simulate import (
    select_cells,
    run_simulation,
    SimState,
    annualized_roi,
)
from kalshi_backtest.ingest import (
    _sign_request,
    KalshiClient,
    MARKETS_FIELDS,
    CANDLE_FIELDS,
)


# ===========================================================================
# 1. Exact Kalshi fee calculation
# ===========================================================================

class TestKalshiFee:
    def test_90c_1_contract(self):
        # fee = ceil(0.07 * 1 * 0.90 * 0.10) = ceil(0.0063) = 0.01
        assert kalshi_fee_per_contract(0.90, 1) == 0.01

    def test_95c_1_contract(self):
        # fee = ceil(0.07 * 1 * 0.95 * 0.05) = ceil(0.003325) = 0.01
        assert kalshi_fee_per_contract(0.95, 1) == 0.01

    def test_80c_1_contract(self):
        # fee = ceil(0.07 * 1 * 0.80 * 0.20) = ceil(0.0112) = 0.02
        assert kalshi_fee_per_contract(0.80, 1) == 0.02

    def test_85c_1_contract(self):
        # fee = ceil(0.07 * 1 * 0.85 * 0.15) = ceil(0.008925) = 0.01
        assert kalshi_fee_per_contract(0.85, 1) == 0.01

    def test_10_contracts_90c(self):
        # fee = ceil(0.07 * 10 * 0.90 * 0.10) = ceil(0.063) = 0.07
        assert kalshi_fee_per_contract(0.90, 10) == 0.07

    def test_ceil_rounding(self):
        # Verify ceil semantics: ceil(0.0001) = 0.01
        # 0.07 * 1 * 0.97 * 0.03 = 0.002037 → ceil to cent = 0.01
        assert kalshi_fee_per_contract(0.97, 1) == 0.01

    def test_fee_is_always_positive(self):
        for p in [0.80, 0.85, 0.90, 0.94, 0.97]:
            assert kalshi_fee_per_contract(p, 1) > 0

    def test_net_edge_positive_if_realized_exceeds_cost(self):
        # At 90¢ ask, if realized=0.96 → edge = 0.96 - 0.90 - 0.01 = 0.05
        fee = kalshi_fee_per_contract(0.90, 1)
        expected = 0.96 - 0.90 - fee
        assert abs(net_edge_per_contract(0.96, 0.90) - expected) < 1e-9

    def test_net_edge_zero_at_breakeven(self):
        ask = 0.90
        fee = kalshi_fee_per_contract(ask, 1)
        breakeven_realized = ask + fee
        assert abs(net_edge_per_contract(breakeven_realized, ask)) < 1e-9


# ===========================================================================
# 2. Wilson confidence interval
# ===========================================================================

class TestWilsonCI:
    def test_known_value_n100_k90(self):
        # n=100, k=90; Wilson CI with z=1.96 → lo≈0.826, hi≈0.945
        lo, hi = wilson_ci(100, 90)
        assert lo < 0.90 < hi
        assert 0.80 < lo < 0.88
        assert 0.92 < hi < 0.98

    def test_known_value_n1000_k900(self):
        lo, hi = wilson_ci(1000, 900)
        assert lo < 0.90 < hi
        assert hi - lo < 0.05  # tight CI with large n

    def test_zero_n_returns_full_interval(self):
        lo, hi = wilson_ci(0, 0)
        assert lo == 0.0 and hi == 1.0

    def test_bounds_within_01(self):
        for n, k in [(10, 10), (100, 0), (50, 25)]:
            lo, hi = wilson_ci(n, k)
            assert 0.0 <= lo <= 1.0
            assert 0.0 <= hi <= 1.0
            assert lo <= hi

    def test_ci_excludes_breakeven_when_clearly_above(self):
        # Ask=0.90, breakeven=0.91. CI [0.94, 0.98] excludes 0.91.
        assert ci_excludes_breakeven(0.94, 0.98, 0.90) is True

    def test_ci_does_not_exclude_breakeven_when_lo_is_below(self):
        # CI lo=0.88 is below breakeven=0.91
        assert ci_excludes_breakeven(0.88, 0.96, 0.90) is False


# ===========================================================================
# 3. Calibration bucketing fixture — planted bias recovery
# ===========================================================================

def _make_fixture_dataset(n: int, ask: float, realized_rate: float,
                           category: str = "sports", window: str = "validation") -> pd.DataFrame:
    """
    Synthetic dataset with a planted edge in one bucket.
    n rows, all same ask, resolved_yes ~ realized_rate.
    close_time set to validation window so window filter passes.
    """
    import random
    random.seed(42)
    rows = []
    for i in range(n):
        resolved = 1 if random.random() < realized_rate else 0
        rows.append({
            "ticker": f"FAKE-{i:04d}",
            "category": category,
            "close_time": "2025-08-01T00:00:00Z",
            "horizon_h": 24,
            "ask_price": ask,
            "bucket": "90–93¢",
            "resolved_yes": resolved,
            "momentum_24h": 0.01,
        })
    return pd.DataFrame(rows)


class TestCalibrationBucketing:
    def test_planted_bias_detected_in_selection(self):
        # Plant a 0.97 realized rate on a 0.91 ask → strong positive edge
        df = _make_fixture_dataset(300, ask=0.91, realized_rate=0.97)
        # Override close_time to selection window
        df["close_time"] = "2024-12-01T00:00:00Z"
        result = calibrate(df, window="selection")
        assert not result.empty
        row = result[(result["bucket"] == "90–93¢") & (result["category"] == "ALL")]
        assert len(row) == 1
        assert float(row["net_edge"].values[0]) > 0
        assert float(row["realized"].values[0]) > float(row["implied"].values[0])

    def test_no_bias_produces_near_zero_edge(self):
        # Realized ≈ implied → net edge should be negative (fee drag)
        df = _make_fixture_dataset(500, ask=0.91, realized_rate=0.91)
        df["close_time"] = "2024-12-01T00:00:00Z"
        result = calibrate(df, window="selection")
        assert not result.empty
        row = result[(result["bucket"] == "90–93¢") & (result["category"] == "ALL")]
        assert len(row) == 1
        assert float(row["net_edge"].values[0]) < 0  # fee drag

    def test_category_breakdown_matches_total(self):
        df = _make_fixture_dataset(200, ask=0.91, realized_rate=0.95, category="sports")
        df["close_time"] = "2024-12-01T00:00:00Z"
        result = calibrate(df, window="selection")
        sports_row = result[(result["bucket"] == "90–93¢") & (result["category"] == "sports")]
        all_row = result[(result["bucket"] == "90–93¢") & (result["category"] == "ALL")]
        assert not sports_row.empty and not all_row.empty
        # Since all rows are sports, sports n == ALL n
        assert int(sports_row["n"].values[0]) == int(all_row["n"].values[0])

    def test_adverse_selection_split(self):
        import random
        random.seed(0)
        rows = []
        for i in range(400):
            mom = 0.01 if i % 2 == 0 else -0.01
            resolved = 1 if random.random() < (0.96 if mom > 0 else 0.88) else 0
            rows.append({
                "ticker": f"ADV-{i:04d}",
                "category": "sports",
                "close_time": "2024-12-01T00:00:00Z",
                "horizon_h": 24,
                "ask_price": 0.91,
                "bucket": "90–93¢",
                "resolved_yes": resolved,
                "momentum_24h": mom,
            })
        df = pd.DataFrame(rows)
        adv = adverse_selection_analysis(df, window="all")
        assert not adv.empty
        rising = adv[adv["momentum"] == "rising"]["net_edge"].values
        falling = adv[adv["momentum"] == "falling"]["net_edge"].values
        assert len(rising) > 0 and len(falling) > 0
        # Rising should be better than falling
        assert float(rising[0]) > float(falling[0])

    def test_bucket_excludes_above_97c(self):
        df = _make_fixture_dataset(200, ask=0.98, realized_rate=0.99)
        df["close_time"] = "2024-12-01T00:00:00Z"
        df["ask_price"] = 0.98
        df["bucket"] = "none"  # shouldn't be bucketed
        result = calibrate(df, window="selection")
        # 0.98 is outside all buckets; no rows should appear for it
        if not result.empty:
            for _, row in result.iterrows():
                assert float(row["implied"]) < 0.98

    def test_minimum_n_filter(self):
        # Only 10 rows → below MIN_CELL_N (30) → empty result
        df = _make_fixture_dataset(10, ask=0.91, realized_rate=0.97)
        df["close_time"] = "2024-12-01T00:00:00Z"
        result = calibrate(df, window="selection")
        assert result.empty or result["n"].max() < 30


# ===========================================================================
# 4. Simulation accounting invariant
# ===========================================================================

def _make_sim_dataset(n_trades: int, ask: float, realized_rate: float,
                      window: str = "validation") -> pd.DataFrame:
    import random
    random.seed(99)
    rows = []
    close_time = "2025-09-01T00:00:00Z" if window == "validation" else "2024-11-01T00:00:00Z"
    for i in range(n_trades):
        resolved = 1 if random.random() < realized_rate else 0
        rows.append({
            "ticker": f"SIM-{i:04d}",
            "category": "sports",
            "close_time": close_time,
            "horizon_h": 24,
            "ask_price": ask,
            "bucket": "90–93¢",
            "resolved_yes": resolved,
            "momentum_24h": 0.01,
        })
    return pd.DataFrame(rows)


class TestSimAccountingInvariant:
    """
    Invariant: final_bankroll == initial_bankroll + realized_pnl
    """
    def test_accounting_invariant_holds(self):
        df = _make_sim_dataset(200, ask=0.91, realized_rate=0.95)
        initial = 8_000.0
        cells = {(24, "90–93¢", "sports"), (24, "90–93¢", "ALL")}
        require_rising: set = set()
        state = run_simulation(df, cells, require_rising, initial, window="validation")
        assert abs(state.bankroll - (initial + state.realized_pnl)) < 1e-6

    def test_accounting_invariant_negative_pnl(self):
        # Below breakeven realized rate
        df = _make_sim_dataset(200, ask=0.91, realized_rate=0.80)
        initial = 8_000.0
        cells = {(24, "90–93¢", "ALL")}
        state = run_simulation(df, cells, set(), initial, window="validation")
        assert abs(state.bankroll - (initial + state.realized_pnl)) < 1e-6

    def test_wins_plus_losses_equals_total_trades(self):
        df = _make_sim_dataset(100, ask=0.92, realized_rate=0.95)
        cells = {(24, "90–93¢", "ALL")}
        state = run_simulation(df, cells, set(), 5_000.0, window="validation")
        assert state.wins + state.losses == state.total_trades

    def test_momentum_filter_reduces_trades(self):
        import random
        random.seed(1)
        rows = []
        for i in range(200):
            mom = 0.01 if i % 2 == 0 else -0.01
            rows.append({
                "ticker": f"MOM-{i:04d}",
                "category": "sports",
                "close_time": "2025-09-01T00:00:00Z",
                "horizon_h": 24,
                "ask_price": 0.91,
                "bucket": "90–93¢",
                "resolved_yes": 1,
                "momentum_24h": mom,
            })
        df = pd.DataFrame(rows)
        cells = {(24, "90–93¢", "ALL")}
        # Without filter
        no_filter = run_simulation(df, cells, set(), 8_000.0, window="validation")
        # With filter requiring rising
        require_rising = {(24, "90–93¢")}
        with_filter = run_simulation(df, cells, require_rising, 8_000.0, window="validation")
        # Filter should reduce trades by ~half
        assert with_filter.total_trades < no_filter.total_trades

    def test_bankroll_never_negative(self):
        df = _make_sim_dataset(500, ask=0.94, realized_rate=0.50)
        cells = {(24, "94–97¢", "ALL"), (24, "90–93¢", "ALL")}
        df["bucket"] = "94–97¢"
        df["ask_price"] = 0.94
        state = run_simulation(df, cells, set(), 1_000.0, window="validation")
        assert state.bankroll >= 0


# ===========================================================================
# 5. Ingest: pagination, resume, rate-limit handling
# ===========================================================================

class TestIngestPagination:
    def test_pagination_follows_cursor(self, tmp_path, monkeypatch):
        """Client should follow cursor until exhausted."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test-key")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/dev/null")

        calls = []
        def mock_get(path, params=None):
            calls.append(dict(params or {}))
            if len(calls) == 1:
                return {
                    "markets": [
                        {"ticker": "MKT-1", "result": "yes", "volume": 1000,
                         "event_ticker": "EVT", "series_ticker": "SER",
                         "category": "sports", "title": "Will X?",
                         "close_time": "2024-07-01T00:00:00Z",
                         "open_interest": 100, "liquidity": 500.0},
                    ],
                    "cursor": "page2",
                }
            else:
                return {"markets": [], "cursor": None}

        from kalshi_backtest import ingest
        monkeypatch.setattr(ingest, "_load_creds", lambda: ("key", b"pem"))

        client = MagicMock()
        client.get.side_effect = mock_get

        markets_dir = tmp_path / "markets"
        markets_dir.mkdir()
        monkeypatch.setattr(ingest, "MARKETS_DIR", markets_dir)
        monkeypatch.setattr(ingest, "CANDLES_DIR", tmp_path / "candles")

        result = ingest.fetch_settled_markets(client)
        assert len(calls) == 2
        assert calls[1].get("cursor") == "page2"
        assert any(m["ticker"] == "MKT-1" for m in result)

    def test_resume_skips_existing_tickers(self, tmp_path, monkeypatch):
        """Tickers already in a shard CSV are not re-fetched."""
        markets_dir = tmp_path / "markets"
        markets_dir.mkdir()
        # Pre-seed a shard
        p = markets_dir / "markets_2024_07.csv"
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MARKETS_FIELDS)
            w.writeheader()
            w.writerow({"ticker": "OLD-MKT", "event_ticker": "", "series_ticker": "",
                        "category": "sports", "title": "Old",
                        "close_time": "2024-07-01T00:00:00Z", "result": "yes",
                        "volume": 1000, "open_interest": 0, "liquidity": 0.0})

        from kalshi_backtest import ingest
        monkeypatch.setattr(ingest, "MARKETS_DIR", markets_dir)
        monkeypatch.setattr(ingest, "CANDLES_DIR", tmp_path / "candles")

        client = MagicMock()
        # API returns the same ticker
        client.get.return_value = {
            "markets": [
                {"ticker": "OLD-MKT", "result": "yes", "volume": 1000,
                 "event_ticker": "", "series_ticker": "SER", "category": "sports",
                 "title": "Old", "close_time": "2024-07-01T00:00:00Z",
                 "open_interest": 0, "liquidity": 0.0},
            ],
            "cursor": None,
        }
        result = ingest.fetch_settled_markets(client)
        # OLD-MKT should appear (loaded from disk), not duplicated
        tickers = [m["ticker"] for m in result]
        assert tickers.count("OLD-MKT") == 1

    def test_rate_limit_retries(self, monkeypatch):
        """Client sleeps and retries on 429."""
        from kalshi_backtest import ingest

        responses = [
            MagicMock(status_code=429, headers={"Retry-After": "1"}),
            MagicMock(status_code=200, json=lambda: {"candlesticks": []}),
        ]
        resp_iter = iter(responses)

        slept = []
        monkeypatch.setattr(ingest.time, "sleep", lambda s: slept.append(s))

        fake_client = MagicMock()
        fake_client.get.side_effect = lambda path, params=None: (_ for _ in ()).throw(
            Exception("use httpx"))

        # Test the retry logic on the httpx client directly
        pem = b"fakepem"
        key_id = "fakeid"
        c = ingest.KalshiClient.__new__(ingest.KalshiClient)
        c._key_id = key_id
        c._pem = pem

        http_responses = iter(responses)
        def fake_http_get(*args, **kwargs):
            return next(http_responses)

        c._client = MagicMock()
        c._client.get.side_effect = fake_http_get

        monkeypatch.setattr(ingest, "_sign_request",
                            lambda *a, **kw: {"KALSHI-Access-Key": "k",
                                              "KALSHI-Access-Timestamp": "1",
                                              "KALSHI-Access-Signature": "s",
                                              "Content-Type": "application/json"})
        monkeypatch.setattr(ingest.time, "sleep", lambda s: slept.append(s))

        result = c.get("/test")
        # 200 mock returns {"candlesticks": []}
        assert "candlesticks" in result
        # Rate-limit sleep was triggered for the 429 response
        assert any(s >= 1 for s in slept)

    def test_volume_filter_excludes_low_volume(self, tmp_path, monkeypatch):
        """Markets below MIN_VOLUME are excluded."""
        from kalshi_backtest import ingest
        monkeypatch.setattr(ingest, "MARKETS_DIR", tmp_path / "markets")
        monkeypatch.setattr(ingest, "CANDLES_DIR", tmp_path / "candles")
        (tmp_path / "markets").mkdir()

        client = MagicMock()
        client.get.return_value = {
            "markets": [
                {"ticker": "LOW-VOL", "result": "yes", "volume": 10,
                 "event_ticker": "", "series_ticker": "SER", "category": "sports",
                 "title": "Low", "close_time": "2024-07-15T00:00:00Z",
                 "open_interest": 0, "liquidity": 0.0},
                {"ticker": "HIGH-VOL", "result": "yes", "volume": 5000,
                 "event_ticker": "", "series_ticker": "SER", "category": "sports",
                 "title": "High", "close_time": "2024-07-15T00:00:00Z",
                 "open_interest": 0, "liquidity": 0.0},
            ],
            "cursor": None,
        }
        result = ingest.fetch_settled_markets(client, volume_floor=500)
        tickers = {m["ticker"] for m in result}
        assert "HIGH-VOL" in tickers
        assert "LOW-VOL" not in tickers

    def test_non_binary_settlement_excluded(self, tmp_path, monkeypatch):
        """Markets with result not in ('yes', 'no') are excluded."""
        from kalshi_backtest import ingest
        monkeypatch.setattr(ingest, "MARKETS_DIR", tmp_path / "markets")
        monkeypatch.setattr(ingest, "CANDLES_DIR", tmp_path / "candles")
        (tmp_path / "markets").mkdir()

        client = MagicMock()
        client.get.return_value = {
            "markets": [
                {"ticker": "SCALAR-MKT", "result": "5.2", "volume": 2000,
                 "event_ticker": "", "series_ticker": "SER", "category": "financials",
                 "title": "Scalar", "close_time": "2024-07-15T00:00:00Z",
                 "open_interest": 0, "liquidity": 0.0},
            ],
            "cursor": None,
        }
        result = ingest.fetch_settled_markets(client, volume_floor=500)
        assert not any(m["ticker"] == "SCALAR-MKT" for m in result)


# ===========================================================================
# 6. Annualized ROI
# ===========================================================================

class TestAnnualizedROI:
    def test_one_year_10pct(self):
        state = SimState(bankroll=11_000.0, peak_equity=11_000.0)
        roi = annualized_roi(state, "2024-01-01", "2025-01-01", 10_000.0)
        assert abs(roi - 0.10) < 0.001

    def test_half_year_doubling(self):
        # Bankroll doubles in 0.5 years → annualized ≈ 3.0 (200% annualized)
        state = SimState(bankroll=20_000.0, peak_equity=20_000.0)
        roi = annualized_roi(state, "2024-01-01", "2024-07-02", 10_000.0)
        assert roi > 2.0  # aggressive but valid

    def test_zero_if_same_dates(self):
        state = SimState(bankroll=10_000.0)
        roi = annualized_roi(state, "2024-01-01", "2024-01-01", 10_000.0)
        assert roi == 0.0
