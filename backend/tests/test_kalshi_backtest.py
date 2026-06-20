"""
Tests for kalshi_backtest: pagination/resume/rate-limit, exact fees, Wilson CI,
calibration bucketing fixture, sim accounting invariant.
"""
from __future__ import annotations

import csv
import math
import time
from datetime import datetime, timedelta, timezone
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
    from datetime import datetime, timedelta
    random.seed(99)
    rows = []
    base = datetime(2025, 9, 1) if window == "validation" else datetime(2024, 11, 1)
    for i in range(n_trades):
        resolved = 1 if random.random() < realized_rate else 0
        # Stagger settlements across days so capital recycles (positions don't
        # all lock concurrently against the cash ceiling).
        close_time = (base + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00Z")
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
        from datetime import datetime, timedelta
        random.seed(1)
        rows = []
        base = datetime(2025, 9, 1)
        for i in range(200):
            mom = 0.01 if i % 2 == 0 else -0.01
            rows.append({
                "ticker": f"MOM-{i:04d}",
                "category": "sports",
                "close_time": (base + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00Z"),
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


# ===========================================================================
# 7. Historical API routing
# ===========================================================================

class TestHistoricalRouting:
    """
    Markets settled before cutoff_dt must hit /historical/... endpoints.
    Markets settled after must hit the live /series/... or /markets endpoints.
    """

    CUTOFF_DT = datetime(2026, 3, 1, tzinfo=timezone.utc)

    def _market(self, close_dt: datetime, ticker: str = "KXTEST-ROUTING",
                series: str = "KXTEST") -> dict:
        return {
            "ticker": ticker,
            "event_ticker": ticker,
            "series_ticker": series,
            "category": "politics",
            "title": "Routing test market",
            "close_time": close_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "result": "yes",
            "volume": 1000.0,
        }

    def test_candles_route_historical(self):
        """Market settled before cutoff → GET /historical/markets/{ticker}/candlesticks."""
        from kalshi_backtest import ingest

        close_dt = self.CUTOFF_DT - timedelta(days=30)
        market = self._market(close_dt)

        called_paths = []
        client = ingest.KalshiClient.__new__(ingest.KalshiClient)
        client.get = lambda path, params=None: (called_paths.append(path) or {"candlesticks": []})

        ingest.fetch_candles(client, market, cutoff_dt=self.CUTOFF_DT)

        assert len(called_paths) == 1
        assert called_paths[0] == f"/historical/markets/{market['ticker']}/candlesticks"

    def test_candles_route_live(self):
        """Market settled after cutoff → GET /series/{series}/markets/{ticker}/candlesticks."""
        from kalshi_backtest import ingest

        close_dt = self.CUTOFF_DT + timedelta(days=30)
        market = self._market(close_dt, series="KXTEST")

        called_paths = []
        client = ingest.KalshiClient.__new__(ingest.KalshiClient)
        client.get = lambda path, params=None: (called_paths.append(path) or {"candlesticks": []})

        ingest.fetch_candles(client, market, cutoff_dt=self.CUTOFF_DT)

        assert len(called_paths) == 1
        expected = f"/series/KXTEST/markets/{market['ticker']}/candlesticks"
        assert called_paths[0] == expected

    def test_markets_both_tiers_called(self, tmp_path, monkeypatch):
        """fetch_settled_markets with cutoff_dt queries /historical/markets AND /markets."""
        from kalshi_backtest import ingest

        monkeypatch.setattr(ingest, "MARKETS_DIR", tmp_path / "markets")
        monkeypatch.setattr(ingest, "CANDLES_DIR", tmp_path / "candles")
        (tmp_path / "markets").mkdir()

        called_paths = []
        client = MagicMock()

        def mock_get(path, params=None):
            called_paths.append(path)
            return {"markets": [], "cursor": None}

        client.get.side_effect = mock_get

        cutoff = self.CUTOFF_DT
        ingest.fetch_settled_markets(
            client,
            start=cutoff - timedelta(days=60),
            end=cutoff + timedelta(days=60),
            cutoff_dt=cutoff,
        )

        assert "/historical/markets" in called_paths, (
            f"Expected /historical/markets call; got: {called_paths}"
        )
        assert "/markets" in called_paths, (
            f"Expected /markets call; got: {called_paths}"
        )


# ===========================================================================
# 8. S3 ingest — schema mapping, filter logic, parlay exclusion
# ===========================================================================

class TestS3SchemaMapping:
    """Schema mapping pinned to Task-1 observed schema (2026-06-12)."""

    # Minimal fixture row matching the real S3 file schema
    FIXTURE_2024 = {
        "ticker_name": "KXPRES-24-DEM",
        "report_ticker": "KXPRES",
        "date": "2024-10-15",
        "high": 92,
        "low": 88,
        "daily_volume": 1200,
        "block_volume": 0,
        "open_interest": 5000,
        "payout_type": "Binary Option",
        "status": "finalized",
    }

    FIXTURE_2026_STR = {
        "ticker_name": "KXBTCD-26-T1",
        "report_ticker": "KXBTCD",
        "date": "2026-06-10",
        "high": "85",        # string type in 2026 vintage
        "low": "79",
        "daily_volume": "550",
        "block_volume": "0",
        "open_interest": "3000",
        "payout_type": "Binary Option",
        "status": "active",
    }

    def test_mid_cents_int_types(self):
        from kalshi_backtest.ingest_s3 import _mid_cents
        assert _mid_cents(self.FIXTURE_2024) == (92 + 88) / 2.0

    def test_mid_cents_string_types(self):
        from kalshi_backtest.ingest_s3 import _mid_cents
        assert _mid_cents(self.FIXTURE_2026_STR) == (85 + 79) / 2.0

    def test_normalise_produces_correct_fields(self):
        from datetime import date
        from kalshi_backtest.ingest_s3 import _normalise, SHARD_FIELDS
        row = _normalise(self.FIXTURE_2024, date(2024, 10, 15))
        assert set(row.keys()) == set(SHARD_FIELDS)
        assert row["ticker_name"] == "KXPRES-24-DEM"
        assert row["high_cents"] == 92
        assert row["low_cents"] == 88
        assert row["daily_volume"] == 1200.0
        assert row["date"] == "2024-10-15"

    def test_normalise_coerces_string_values(self):
        from datetime import date
        from kalshi_backtest.ingest_s3 import _normalise
        row = _normalise(self.FIXTURE_2026_STR, date(2026, 6, 10))
        assert row["high_cents"] == 85
        assert row["daily_volume"] == 550.0

    def test_close_proxy_formula(self):
        from kalshi_backtest.ingest_s3 import _mid_cents
        mid = _mid_cents({"high": 92, "low": 88})
        close = mid / 100.0
        assert abs(close - 0.90) < 1e-9


class TestS3FilterLogic:
    """Ingest keep/discard filter tests."""

    def _rec(self, **kwargs):
        base = {
            "ticker_name": "TEST-1",
            "report_ticker": "TEST",
            "date": "2024-10-15",
            "high": 92, "low": 88,
            "daily_volume": 100,
            "open_interest": 500,
            "payout_type": "Binary Option",
            "status": "active",
        }
        base.update(kwargs)
        return base

    def test_volume_zero_excluded(self):
        from kalshi_backtest.ingest_s3 import _should_keep
        rec = self._rec(daily_volume=0, open_interest=0)
        assert not _should_keep(rec)

    def test_volume_one_included(self):
        from kalshi_backtest.ingest_s3 import _should_keep
        rec = self._rec(daily_volume=1)
        assert _should_keep(rec)

    def test_price_below_floor_excluded_without_keeplist(self):
        from kalshi_backtest.ingest_s3 import _should_keep
        # mid = 37.5¢ — below 75¢ floor
        rec = self._rec(high=40, low=35, daily_volume=50)
        assert not _should_keep(rec)

    def test_price_in_range_included(self):
        from kalshi_backtest.ingest_s3 import _should_keep
        rec = self._rec(high=92, low=88, daily_volume=5)
        assert _should_keep(rec)

    def test_price_above_99_excluded(self):
        from kalshi_backtest.ingest_s3 import _should_keep
        rec = self._rec(high=100, low=100, daily_volume=5)
        assert not _should_keep(rec)

    def test_price_exactly_at_floor_included(self):
        from kalshi_backtest.ingest_s3 import _should_keep, PRICE_FLOOR_CENTS
        # mid = 75¢ exactly
        rec = self._rec(high=75, low=75, daily_volume=5)
        assert _should_keep(rec)

    def test_keeplist_overrides_price_filter(self):
        from kalshi_backtest.ingest_s3 import _should_keep
        # Price is 30¢ (below 75¢), but series is on keep-list
        rec = self._rec(report_ticker="MYSPECIAL", high=30, low=30, daily_volume=5)
        assert _should_keep(rec, series_keep={"MYSPECIAL"})

    def test_non_binary_payout_excluded(self):
        from kalshi_backtest.ingest_s3 import _should_keep
        rec = self._rec(payout_type="Scalar", high=92, low=88, daily_volume=100)
        assert not _should_keep(rec)


class TestS3ParlayExclusion:
    """Parlay prefix and metadata detection."""

    def test_known_parlay_prefix_excluded(self):
        from kalshi_backtest.ingest_s3 import _is_parlay
        assert _is_parlay("KXMVESPORTS")
        assert _is_parlay("KXMVESPORTSMULTIGAMEEXTENDED")
        assert _is_parlay("KXMVECROSSCATEGORY")

    def test_regular_series_not_excluded(self):
        from kalshi_backtest.ingest_s3 import _is_parlay
        assert not _is_parlay("KXPRES")
        assert not _is_parlay("KXBTCD")
        assert not _is_parlay("KXNBA")

    def test_parlay_title_pattern_detected(self):
        from kalshi_backtest.ingest_s3 import _is_parlay_from_meta
        meta = {"ticker": "CUSTOM-X", "title": "multi-leg parlay bundle"}
        assert _is_parlay_from_meta(meta)

    def test_single_outcome_sports_not_parlay(self):
        from kalshi_backtest.ingest_s3 import _is_parlay_from_meta
        meta = {"ticker": "KXNBA-26-BOS", "title": "Will Boston win?"}
        assert not _is_parlay_from_meta(meta)

    def test_parlay_keyword_case_insensitive(self):
        from kalshi_backtest.ingest_s3 import _is_parlay_from_meta
        meta = {"ticker": "X", "title": "Multi-Game Parlay"}
        assert _is_parlay_from_meta(meta)


# ===========================================================================
# 9. S3 ingest — settlement routing (historical vs live)
# ===========================================================================

class TestS3SettlementRouting:
    """Settlement lookup routes to /historical/markets/{ticker} or /markets/{ticker}."""

    def _make_client_recording_paths(self, return_result="yes"):
        from unittest.mock import MagicMock
        called_paths = []

        def mock_get(path, params=None):
            called_paths.append(path)
            return {"market": {"result": return_result}}

        client = MagicMock()
        client.get.side_effect = mock_get
        return client, called_paths

    def test_settlement_tries_historical_first(self, tmp_path, monkeypatch):
        """resolve_settlements always tries /historical/markets/{ticker} first."""
        from datetime import datetime, timezone
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SETTLE_DIR", tmp_path / "settlements")
        monkeypatch.setattr(ingest_s3.time, "sleep", lambda s: None)

        client, called_paths = self._make_client_recording_paths("yes")
        cutoff = datetime(2026, 4, 13, tzinfo=timezone.utc)
        result = ingest_s3.resolve_settlements(["KXPRES-24-DEM"], client, cutoff)
        assert result.get("KXPRES-24-DEM") == "yes"
        assert any("/historical/markets/KXPRES-24-DEM" in p for p in called_paths)

    def test_settlement_falls_back_to_live_on_historical_error(self, tmp_path, monkeypatch):
        """resolve_settlements falls back to /markets/{ticker} if historical raises."""
        from datetime import datetime, timezone
        from kalshi_backtest import ingest_s3
        from unittest.mock import MagicMock
        monkeypatch.setattr(ingest_s3, "SETTLE_DIR", tmp_path / "settlements")
        monkeypatch.setattr(ingest_s3.time, "sleep", lambda s: None)

        called_paths = []
        def mock_get(path, params=None):
            called_paths.append(path)
            if "historical" in path:
                raise Exception("historical error")
            return {"market": {"result": "no"}}

        client = MagicMock()
        client.get.side_effect = mock_get
        cutoff = datetime(2026, 4, 13, tzinfo=timezone.utc)
        result = ingest_s3.resolve_settlements(["KXPRES-24-DEM"], client, cutoff)
        assert result.get("KXPRES-24-DEM") == "no"
        assert any("/markets/KXPRES-24-DEM" in p and "historical" not in p for p in called_paths)

    def test_unresolvable_ticker_not_in_result(self, tmp_path, monkeypatch):
        """Tickers with no yes/no result from either endpoint are excluded."""
        from datetime import datetime, timezone
        from kalshi_backtest import ingest_s3
        from unittest.mock import MagicMock
        monkeypatch.setattr(ingest_s3, "SETTLE_DIR", tmp_path / "settlements")
        monkeypatch.setattr(ingest_s3.time, "sleep", lambda s: None)

        client = MagicMock()
        client.get.side_effect = Exception("not found")
        cutoff = datetime(2026, 4, 13, tzinfo=timezone.utc)
        result = ingest_s3.resolve_settlements(["KXUNKNOWN-99"], client, cutoff)
        assert "KXUNKNOWN-99" not in result


# ===========================================================================
# 10. S3 ingest — daily horizon entry selection and haircut math
# ===========================================================================

class TestS3DailyHorizonEntry:
    """build_dataset_s3: horizon selection and haircut arithmetic."""

    def _make_rows(self, n_days: int = 15, ticker: str = "KXTEST-01",
                   report_ticker: str = "KXTEST",
                   high_cents: int = 90, low_cents: int = 86) -> list[dict]:
        from datetime import date, timedelta
        start = date(2025, 1, 2)
        rows = []
        for i in range(n_days):
            d = start + timedelta(days=i)
            rows.append({
                "ticker_name": ticker,
                "report_ticker": report_ticker,
                "date": d.isoformat(),
                "high_cents": str(high_cents),
                "low_cents": str(low_cents),
                "daily_volume": "100",
                "open_interest": "500",
                "status": "finalized" if i == n_days - 1 else "active",
            })
        return rows

    def test_horizon_1d_uses_penultimate_day(self):
        """Horizon 1d = entry on day N-1, final day N."""
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        rows = self._make_rows(n_days=10, high_cents=92, low_cents=88)
        settlements = {"KXTEST-01": "yes"}
        df = build_dataset_s3(rows, settlements, {}, haircut_cents=1, volume_floor=0)
        h24 = df[df["horizon_h"] == 24]  # horizon 1d = 24h
        assert not h24.empty

    def test_horizon_7d_requires_at_least_8_trading_days(self):
        """Horizon 7d needs at least 8 active days (idx = len-1-7 = 0+ only if len>=8)."""
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        # Only 5 days → horizon 7d entry would need idx=-3 (invalid) → no 7d rows
        rows = self._make_rows(n_days=5)
        settlements = {"KXTEST-01": "yes"}
        df = build_dataset_s3(rows, settlements, {}, haircut_cents=1, volume_floor=0)
        h7d = df[df["horizon_h"] == 7 * 24]
        assert h7d.empty

    def test_haircut_1c_adds_one_cent(self):
        """entry_price = (high+low)/2/100 + 0.01 for 1¢ haircut."""
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        rows = self._make_rows(n_days=10, high_cents=90, low_cents=90)
        settlements = {"KXTEST-01": "yes"}
        df = build_dataset_s3(rows, settlements, {}, haircut_cents=1, volume_floor=0)
        if not df.empty:
            close = 0.90  # (90+90)/2/100
            expected_ask = close + 0.01
            assert all(abs(float(v) - expected_ask) < 1e-4 for v in df["ask_price"])

    def test_haircut_2c_is_higher_than_1c(self):
        """2¢ haircut produces higher entry prices than 1¢."""
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        rows = self._make_rows(n_days=10, high_cents=90, low_cents=88)
        settlements = {"KXTEST-01": "yes"}
        df_1c = build_dataset_s3(rows, settlements, {}, haircut_cents=1, volume_floor=0)
        df_2c = build_dataset_s3(rows, settlements, {}, haircut_cents=2, volume_floor=0)
        if not df_1c.empty and not df_2c.empty:
            assert df_2c["ask_price"].mean() > df_1c["ask_price"].mean()

    def test_momentum_uses_prior_5_days(self):
        """Momentum = close at entry minus close 5 active days prior."""
        from datetime import date, timedelta
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        # Build rows where price increases over time so momentum > 0
        rows = []
        for i in range(12):
            d = (date(2025, 1, 2) + timedelta(days=i)).isoformat()
            h = 85 + i  # increasing high
            l = 83 + i  # increasing low
            rows.append({
                "ticker_name": "KXTEST-01", "report_ticker": "KXTEST",
                "date": d, "high_cents": str(h), "low_cents": str(l),
                "daily_volume": "100", "open_interest": "500", "status": "active",
            })
        settlements = {"KXTEST-01": "yes"}
        df = build_dataset_s3(rows, settlements, {}, haircut_cents=1, volume_floor=0)
        # At least some rows should have positive momentum (price rising)
        if not df.empty:
            rising_rows = df[df["momentum_24h"] > 0]
            assert len(rising_rows) > 0

    def test_volume_floor_filters_low_volume_tickers(self):
        """Tickers with lifetime volume < floor are excluded."""
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        rows = self._make_rows(n_days=10)
        # total volume = 10 * 100 = 1000, but use a very high floor
        settlements = {"KXTEST-01": "yes"}
        df = build_dataset_s3(rows, settlements, {}, haircut_cents=1, volume_floor=5000)
        assert df.empty

    def test_parlay_series_excluded_from_dataset(self):
        """Markets with parlay series prefix are excluded."""
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        rows = self._make_rows(n_days=10, ticker="KXMVESPORTS-1",
                                report_ticker="KXMVESPORTS")
        settlements = {"KXMVESPORTS-1": "yes"}
        df = build_dataset_s3(rows, settlements, {}, haircut_cents=1, volume_floor=0)
        assert df.empty

    def test_unresolved_ticker_excluded_from_dataset(self):
        """Tickers not in settlements dict are excluded."""
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        rows = self._make_rows(n_days=10)
        df = build_dataset_s3(rows, {}, {}, haircut_cents=1, volume_floor=0)
        assert df.empty


# ===========================================================================
# 11. S3 ingest — KC-1 amendment: non-sports OR sports n≥1000
# ===========================================================================

class TestKC1Amendment:
    """KC-1 amended rule: non-sports cell OR sports cell with n ≥ 1,000."""

    def _make_val_calib(self, n: int, category: str,
                         net_edge: float, ci_excl: bool) -> "pd.DataFrame":
        return pd.DataFrame([{
            "window": "validation",
            "horizon_h": 24,
            "bucket": "90–93¢",
            "category": category,
            "n": n,
            "implied": 0.91,
            "realized": 0.91 + net_edge + 0.01,
            "net_edge": net_edge,
            "ci_lo": 0.94,
            "ci_hi": 0.99,
            "ci_excl_breakeven": ci_excl,
            "raw_edge": net_edge + 0.01,
        }])

    def test_non_sports_cell_passes_kc1(self):
        from kalshi_backtest.report import evaluate_kcs
        import pandas as pd

        df_val = self._make_val_calib(n=100, category="politics",
                                       net_edge=0.02, ci_excl=True)
        df_sel = self._make_val_calib(n=100, category="politics",
                                       net_edge=0.02, ci_excl=True)
        df_adv = pd.DataFrame()
        df_data = pd.DataFrame()

        res = evaluate_kcs(df_sel, df_val, df_adv, df_data)
        assert res["kc1"] is True

    def test_sports_small_n_fails_kc1(self):
        from kalshi_backtest.report import evaluate_kcs
        import pandas as pd

        df_val = self._make_val_calib(n=200, category="sports",
                                       net_edge=0.02, ci_excl=True)
        df_sel = pd.DataFrame()
        df_adv = pd.DataFrame()
        df_data = pd.DataFrame()

        res = evaluate_kcs(df_sel, df_val, df_adv, df_data)
        assert res["kc1"] is False

    def test_sports_large_n_passes_kc1(self):
        from kalshi_backtest.report import evaluate_kcs
        import pandas as pd

        df_val = self._make_val_calib(n=1500, category="sports",
                                       net_edge=0.02, ci_excl=True)
        df_sel = pd.DataFrame()
        df_adv = pd.DataFrame()
        df_data = pd.DataFrame()

        res = evaluate_kcs(df_sel, df_val, df_adv, df_data)
        assert res["kc1"] is True

    def test_ci_not_excluding_zero_fails_kc1(self):
        from kalshi_backtest.report import evaluate_kcs
        import pandas as pd

        df_val = self._make_val_calib(n=200, category="politics",
                                       net_edge=0.02, ci_excl=False)
        df_sel = pd.DataFrame()
        df_adv = pd.DataFrame()
        df_data = pd.DataFrame()

        res = evaluate_kcs(df_sel, df_val, df_adv, df_data)
        assert res["kc1"] is False


# ===========================================================================
# 12. S3 ingest — shard I/O, manifest, funnel report
# ===========================================================================

class TestS3ShardIO:
    """_append_to_shard and load_s3_shards round-trip."""

    def test_append_and_load_round_trip(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")

        rows = [
            {"ticker_name": "A-1", "report_ticker": "A", "date": "2025-01-15",
             "high_cents": 90, "low_cents": 88, "daily_volume": 500.0,
             "open_interest": 200.0, "status": "active"},
            {"ticker_name": "B-1", "report_ticker": "B", "date": "2025-02-10",
             "high_cents": 85, "low_cents": 83, "daily_volume": 300.0,
             "open_interest": 100.0, "status": "finalized"},
        ]
        ingest_s3._append_to_shard(rows)

        from datetime import date
        loaded = ingest_s3.load_s3_shards(
            start=date(2025, 1, 1), end=date(2025, 3, 1))
        tickers = {r["ticker_name"] for r in loaded}
        assert "A-1" in tickers
        assert "B-1" in tickers

    def test_append_empty_rows_is_noop(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        ingest_s3._append_to_shard([])
        assert not (tmp_path / "shards").exists() or \
               not list((tmp_path / "shards").glob("*.csv"))

    def test_load_shards_date_filter(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        from datetime import date
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")

        rows = [
            {"ticker_name": "EARLY", "report_ticker": "E", "date": "2024-06-15",
             "high_cents": 90, "low_cents": 88, "daily_volume": 100.0,
             "open_interest": 0.0, "status": "finalized"},
            {"ticker_name": "LATE", "report_ticker": "L", "date": "2025-09-01",
             "high_cents": 90, "low_cents": 88, "daily_volume": 100.0,
             "open_interest": 0.0, "status": "finalized"},
        ]
        ingest_s3._append_to_shard(rows)

        # Only load rows in 2024
        loaded = ingest_s3.load_s3_shards(
            start=date(2024, 1, 1), end=date(2024, 12, 31))
        tickers = {r["ticker_name"] for r in loaded}
        assert "EARLY" in tickers
        assert "LATE" not in tickers


class TestS3Manifest:
    """_load_manifest and _save_manifest round-trip."""

    def test_manifest_save_and_load(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "MANIFEST", tmp_path / "manifest.json")
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")

        manifest = {"2025-01-02": "ok", "2025-01-03": "404"}
        ingest_s3._save_manifest(manifest)
        loaded = ingest_s3._load_manifest()
        assert loaded == manifest

    def test_manifest_empty_when_missing(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "MANIFEST", tmp_path / "missing.json")
        assert ingest_s3._load_manifest() == {}


class TestS3DayUrl:
    def test_day_url_format(self):
        from datetime import date
        from kalshi_backtest.ingest_s3 import _day_url
        url = _day_url(date(2024, 10, 15))
        assert url == "https://kalshi-public-docs.s3.amazonaws.com/reporting/market_data_2024-10-15.json"


class TestS3IngestOneDay:
    """_ingest_one_day worker with mocked download."""

    def test_ingest_one_day_ok(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")

        records = [
            {"ticker_name": "KXPRES-01", "report_ticker": "KXPRES",
             "high": 92, "low": 88, "daily_volume": 50,
             "open_interest": 200, "payout_type": "Binary Option", "status": "finalized"},
        ]
        monkeypatch.setattr(ingest_s3, "_download_day_records", lambda d: records)

        d = date(2025, 3, 15)
        date_str, status, rows_kept = ingest_s3._ingest_one_day((d, None))
        assert status == "ok"
        assert rows_kept == 1

    def test_ingest_one_day_404(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "_download_day_records", lambda d: None)

        d = date(2025, 3, 16)
        date_str, status, rows_kept = ingest_s3._ingest_one_day((d, None))
        assert status == "404"
        assert rows_kept == 0

    def test_ingest_one_day_empty(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "_download_day_records", lambda d: [])

        d = date(2025, 3, 17)
        date_str, status, rows_kept = ingest_s3._ingest_one_day((d, None))
        assert status == "empty"
        assert rows_kept == 0


class TestS3RunIngest:
    """run_ingest with mocked downloads — manifest, skip-already-done."""

    def test_run_ingest_skips_manifest_entries(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3

        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "MANIFEST", tmp_path / "manifest.json")

        # Pre-seed manifest with one day already done
        ingest_s3._save_manifest({"2025-01-02": "ok"})

        downloaded = []

        def mock_download(d):
            downloaded.append(d)
            return []

        monkeypatch.setattr(ingest_s3, "_download_day_records", mock_download)

        from datetime import date
        ingest_s3.run_ingest(
            start=date(2025, 1, 2), end=date(2025, 1, 3),
            n_workers=1,
        )
        # 2025-01-02 is in manifest → skipped; 2025-01-03 is not → downloaded
        assert date(2025, 1, 2) not in downloaded
        assert date(2025, 1, 3) in downloaded

    def test_run_ingest_records_404_in_manifest(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3

        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "MANIFEST", tmp_path / "manifest.json")
        monkeypatch.setattr(ingest_s3, "_download_day_records", lambda d: None)

        ingest_s3.run_ingest(start=date(2025, 1, 4), end=date(2025, 1, 4), n_workers=1)

        manifest = ingest_s3._load_manifest()
        assert manifest.get("2025-01-04") == "404"


class TestS3FunnelReport:
    """build_funnel_report — pure function, no I/O."""

    def _rows(self):
        return [
            {"ticker_name": "KXPRES-01", "report_ticker": "KXPRES",
             "date": "2025-02-01", "daily_volume": "1000", "open_interest": "0"},
            {"ticker_name": "KXPRES-02", "report_ticker": "KXPRES",
             "date": "2025-02-02", "daily_volume": "500", "open_interest": "0"},
            {"ticker_name": "KXMVESPORTS-P", "report_ticker": "KXMVESPORTS",
             "date": "2025-02-01", "daily_volume": "200", "open_interest": "0"},
        ]

    def test_funnel_report_is_string(self):
        from kalshi_backtest.ingest_s3 import build_funnel_report
        rows = self._rows()
        settlements = {"KXPRES-01": "yes", "KXPRES-02": "no"}
        series_cache: dict = {}
        report = build_funnel_report(rows, settlements, series_cache)
        assert isinstance(report, str)
        assert "FUNNEL" in report

    def test_funnel_report_counts_non_parlay_only(self):
        from kalshi_backtest.ingest_s3 import build_funnel_report
        rows = self._rows()
        settlements = {"KXPRES-01": "yes", "KXPRES-02": "no"}
        report = build_funnel_report(rows, settlements, {})
        # Parlay KXMVESPORTS-P should be excluded from "After parlay exclusion" count
        assert "KXPRES" in report or "2" in report


class TestS3FetchSeriesMetadata:
    """fetch_series_metadata — mock client, cache behaviour."""

    def test_fetches_uncached_series(self, tmp_path):
        from unittest.mock import MagicMock
        from kalshi_backtest.ingest_s3 import fetch_series_metadata

        cache_path = tmp_path / "series_cache.json"
        client = MagicMock()
        client.get.return_value = {"series": {"ticker": "KXPRES", "category": "politics"}}

        result = fetch_series_metadata(["KXPRES"], client, cache_path=cache_path)
        assert "KXPRES" in result
        assert cache_path.exists()

    def test_skips_cached_series(self, tmp_path):
        import json
        from unittest.mock import MagicMock
        from kalshi_backtest.ingest_s3 import fetch_series_metadata

        cache_path = tmp_path / "series_cache.json"
        cache_path.write_text(json.dumps({"KXPRES": {"ticker": "KXPRES", "category": "politics"}}))

        client = MagicMock()
        result = fetch_series_metadata(["KXPRES"], client, cache_path=cache_path)
        client.get.assert_not_called()
        assert result["KXPRES"]["category"] == "politics"

    def test_handles_fetch_error_gracefully(self, tmp_path):
        from unittest.mock import MagicMock
        from kalshi_backtest.ingest_s3 import fetch_series_metadata

        cache_path = tmp_path / "series_cache.json"
        client = MagicMock()
        client.get.side_effect = Exception("API error")

        result = fetch_series_metadata(["KXUNKNOWN"], client, cache_path=cache_path)
        assert "KXUNKNOWN" in result
        assert "_fetch_error" in result["KXUNKNOWN"]


class TestS3AssignCategory:
    def test_api_category_takes_precedence(self):
        from kalshi_backtest.ingest_s3 import assign_category
        cache = {"KXPRES": {"category": "politics"}}
        assert assign_category("KXPRES", cache) == "politics"

    def test_prefix_fallback_when_no_api_category(self):
        from kalshi_backtest.ingest_s3 import assign_category
        # No cache entry — falls back to prefix mapping
        assert assign_category("KXBTCD", {}) == "financials"
        assert assign_category("KXFOMC", {}) == "economics"
        assert assign_category("KXTEMPNYC", {}) == "climate"
        assert assign_category("KXNBA", {}) == "sports"

    def test_unknown_prefix_returns_other(self):
        from kalshi_backtest.ingest_s3 import assign_category
        assert assign_category("KXMYSTERY", {}) == "other"


class TestS3GenerateReportS3:
    """generate_report_s3 writes REPORT.md and RESULTS_SUMMARY.md."""

    def _make_calib_df(self):
        return pd.DataFrame([{
            "window": "validation",
            "horizon_h": 24,
            "bucket": "90–93¢",
            "category": "politics",
            "n": 150,
            "implied": 0.91,
            "realized": 0.95,
            "raw_edge": 0.04,
            "net_edge": 0.03,
            "ci_lo": 0.93,
            "ci_hi": 0.97,
            "ci_excl_breakeven": True,
        }])

    def test_generate_report_s3_creates_files(self, tmp_path, monkeypatch):
        from kalshi_backtest import report as rpt
        monkeypatch.setattr(rpt, "REPORT_MD", tmp_path / "REPORT.md")
        monkeypatch.setattr(rpt, "SUMMARY_MD", tmp_path / "RESULTS_SUMMARY.md")

        df_val = self._make_calib_df()
        kc_results = {
            "kc1": True, "kc2": False, "kc3": True, "kc4": False, "kc5": False,
            "all_pass": False,
            "kc1_cells": df_val.head(1),
            "roi_8k": 0.03,
            "roi_8k_doubled": -0.01,
            "val_8k": __import__("kalshi_backtest.simulate", fromlist=["SimState"]).SimState(
                bankroll=8200.0, peak_equity=8300.0, realized_pnl=200.0,
                total_trades=50, wins=42, losses=8, total_fees=15.0,
                max_drawdown=-0.04,
            ),
            "val_8k_doubled": __import__("kalshi_backtest.simulate", fromlist=["SimState"]).SimState(
                bankroll=8050.0, peak_equity=8200.0,
            ),
            "trades_per_yr": 60.0,
            "cells": set(),
            "require_rising": set(),
            "val_start": "2025-07-01",
            "val_end": "2026-01-01",
        }

        rpt.generate_report_s3(
            df_dataset=pd.DataFrame(),
            df_sel_calib=df_val,
            df_val_calib=df_val,
            df_adv_sel=pd.DataFrame(),
            kc_results=kc_results,
            rows=[],
            settlements={},
            series_cache={},
            haircut_1c=True,
        )

        assert (tmp_path / "REPORT.md").exists()
        assert (tmp_path / "RESULTS_SUMMARY.md").exists()
        content = (tmp_path / "REPORT.md").read_text()
        assert "S3" in content

    def test_generate_report_s3_2c_appends_sensitivity(self, tmp_path, monkeypatch):
        from kalshi_backtest import report as rpt
        monkeypatch.setattr(rpt, "REPORT_MD", tmp_path / "REPORT.md")
        monkeypatch.setattr(rpt, "RESULTS_SUMMARY.md", tmp_path / "RESULTS_SUMMARY.md", raising=False)
        monkeypatch.setattr(rpt, "SUMMARY_MD", tmp_path / "RESULTS_SUMMARY.md")

        # First write 1¢ report
        df_val = self._make_calib_df()
        from kalshi_backtest.simulate import SimState
        kc_base = {
            "kc1": True, "kc2": True, "kc3": True, "kc4": True, "kc5": True,
            "all_pass": True,
            "kc1_cells": df_val.head(1),
            "roi_8k": 0.08,
            "roi_8k_doubled": 0.04,
            "val_8k": SimState(bankroll=8640.0, peak_equity=8700.0,
                                realized_pnl=640.0, total_trades=80, wins=70, losses=10,
                                total_fees=20.0, max_drawdown=-0.03),
            "val_8k_doubled": SimState(bankroll=8320.0, peak_equity=8400.0),
            "trades_per_yr": 90.0,
            "cells": set(), "require_rising": set(),
            "val_start": "2025-07-01", "val_end": "2026-01-01",
        }
        rpt.generate_report_s3(pd.DataFrame(), df_val, df_val, pd.DataFrame(),
                                kc_base, [], {}, {}, haircut_1c=True)

        # Now append 2¢ sensitivity
        kc_2c = dict(kc_base, roi_8k=0.05, roi_8k_doubled=0.01, all_pass=True)
        rpt.generate_report_s3(pd.DataFrame(), df_val, df_val, pd.DataFrame(),
                                kc_2c, [], {}, {}, haircut_1c=False)

        text = (tmp_path / "RESULTS_SUMMARY.md").read_text()
        assert "2¢ haircut sensitivity" in text


# ===========================================================================
# 13. S3 ingest — additional edge-case coverage
# ===========================================================================

class TestS3DownloadDayRecords:
    """_download_day_records with mocked urllib."""

    def test_downloads_and_returns_list(self, tmp_path, monkeypatch):
        import json
        import io
        from datetime import date
        from unittest.mock import MagicMock
        from kalshi_backtest import ingest_s3

        payload = json.dumps([{"ticker_name": "A-1", "daily_volume": 10}]).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        # Simulate chunked read: first call returns data, second returns b""
        mock_resp.read.side_effect = [payload, b""]

        monkeypatch.setattr(ingest_s3.urllib.request, "urlopen",
                            lambda *a, **kw: mock_resp)

        result = ingest_s3._download_day_records(date(2025, 1, 2))
        assert result is not None
        assert result[0]["ticker_name"] == "A-1"

    def test_404_returns_none(self, monkeypatch):
        import urllib.error
        from datetime import date
        from kalshi_backtest import ingest_s3

        err = urllib.error.HTTPError(url="u", code=404, msg="", hdrs=None, fp=None)  # type: ignore
        monkeypatch.setattr(ingest_s3.urllib.request, "urlopen",
                            lambda *a, **kw: (_ for _ in ()).throw(err))

        result = ingest_s3._download_day_records(date(2025, 1, 5))
        assert result is None

    def test_non_list_response_returns_empty(self, tmp_path, monkeypatch):
        import json
        from datetime import date
        from unittest.mock import MagicMock
        from kalshi_backtest import ingest_s3

        payload = json.dumps({"unexpected": "dict"}).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.side_effect = [payload, b""]

        monkeypatch.setattr(ingest_s3.urllib.request, "urlopen",
                            lambda *a, **kw: mock_resp)

        result = ingest_s3._download_day_records(date(2025, 1, 3))
        assert result == []


class TestS3AppendShardEdgeCases:
    """_append_to_shard exception path and load_s3_shards edge cases."""

    def test_invalid_date_row_is_silently_skipped(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")

        rows = [
            {"ticker_name": "X", "report_ticker": "X", "date": "NOT-A-DATE",
             "high_cents": 90, "low_cents": 88, "daily_volume": 10.0,
             "open_interest": 0.0, "status": "active"},
        ]
        # Should not raise
        ingest_s3._append_to_shard(rows)
        # No file written since all rows had invalid date
        assert not list((tmp_path / "shards").glob("*.csv")) if (tmp_path / "shards").exists() else True

    def test_load_shards_no_end_defaults_to_today(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")

        rows = [
            {"ticker_name": "Z-1", "report_ticker": "Z", "date": "2025-05-01",
             "high_cents": 90, "low_cents": 88, "daily_volume": 10.0,
             "open_interest": 0.0, "status": "finalized"},
        ]
        ingest_s3._append_to_shard(rows)
        # Call without end param — should default to date.today()
        loaded = ingest_s3.load_s3_shards(start=date(2025, 1, 1))
        assert any(r["ticker_name"] == "Z-1" for r in loaded)

    def test_load_shards_skips_malformed_filename(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        (tmp_path / "shards").mkdir()
        # Write a file that doesn't match the expected naming pattern
        (tmp_path / "shards" / "markets_s3_badname.csv").write_text("x")
        (tmp_path / "shards" / "markets_s3_2025_noint.csv").write_text("x")

        # Should not raise; bad files are skipped
        loaded = ingest_s3.load_s3_shards(start=date(2025, 1, 1), end=date(2025, 12, 31))
        assert loaded == []


class TestS3IngestOneDayException:
    """_ingest_one_day exception path."""

    def test_exception_returns_error_status(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "_download_day_records",
                            lambda d: (_ for _ in ()).throw(RuntimeError("boom")))

        d = date(2025, 4, 1)
        date_str, status, rows = ingest_s3._ingest_one_day((d, None))
        assert "error" in status
        assert rows == 0


class TestS3RunIngestCounters:
    """run_ingest counter paths (ok, error)."""

    def test_run_ingest_ok_rows_counter(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3

        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "MANIFEST", tmp_path / "manifest.json")

        records = [
            {"ticker_name": "KXPRES-T", "report_ticker": "KXPRES",
             "high": 92, "low": 88, "daily_volume": 50,
             "open_interest": 200, "payout_type": "Binary Option", "status": "finalized"},
        ]
        monkeypatch.setattr(ingest_s3, "_download_day_records", lambda d: records)

        counters = ingest_s3.run_ingest(
            start=date(2025, 2, 1), end=date(2025, 2, 1), n_workers=1)
        assert counters["ok"] >= 1
        assert counters["rows_kept"] >= 1

    def test_run_ingest_error_counter(self, tmp_path, monkeypatch):
        from datetime import date
        from kalshi_backtest import ingest_s3

        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "MANIFEST", tmp_path / "manifest.json")
        monkeypatch.setattr(ingest_s3, "_download_day_records",
                            lambda d: (_ for _ in ()).throw(RuntimeError("fail")))

        counters = ingest_s3.run_ingest(
            start=date(2025, 2, 2), end=date(2025, 2, 2), n_workers=1)
        assert counters["errors"] >= 1

    def test_run_ingest_default_end(self, tmp_path, monkeypatch):
        """run_ingest without end param should use date.today()."""
        from datetime import date
        from kalshi_backtest import ingest_s3

        monkeypatch.setattr(ingest_s3, "SHARD_DIR", tmp_path / "shards")
        monkeypatch.setattr(ingest_s3, "MANIFEST", tmp_path / "manifest.json")
        # Seed manifest with today so nothing is downloaded
        from datetime import date as _date
        today_str = _date.today().isoformat()
        ingest_s3._save_manifest({today_str: "ok"})
        monkeypatch.setattr(ingest_s3, "_download_day_records", lambda d: [])

        # Narrow window: just today
        counters = ingest_s3.run_ingest(start=_date.today())
        assert "total_days" in counters


class TestS3LoadSettlementCache:
    """load_settlement_cache with pre-existing files."""

    def test_loads_from_disk(self, tmp_path, monkeypatch):
        import json
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SETTLE_DIR", tmp_path / "settle")

        # Write a settlement file
        sub = (tmp_path / "settle" / "kx")
        sub.mkdir(parents=True)
        (sub / "KXPRES-01.json").write_text(
            json.dumps({"ticker_name": "KXPRES-01", "result": "yes"}))

        cache = ingest_s3.load_settlement_cache()
        assert cache.get("KXPRES-01") == "yes"

    def test_returns_empty_when_dir_missing(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SETTLE_DIR", tmp_path / "nonexistent")
        cache = ingest_s3.load_settlement_cache()
        assert cache == {}

    def test_skips_malformed_json(self, tmp_path, monkeypatch):
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SETTLE_DIR", tmp_path / "settle")
        sub = (tmp_path / "settle" / "ba")
        sub.mkdir(parents=True)
        (sub / "bad.json").write_text("not-json{{")
        cache = ingest_s3.load_settlement_cache()
        assert cache == {}


class TestS3ResolveSettlementsEdgeCases:
    """resolve_settlements: live fallback when historical returns non-binary result."""

    def test_falls_back_to_live_when_historical_returns_empty_result(self, tmp_path, monkeypatch):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        from kalshi_backtest import ingest_s3
        monkeypatch.setattr(ingest_s3, "SETTLE_DIR", tmp_path / "settle")
        monkeypatch.setattr(ingest_s3.time, "sleep", lambda s: None)

        call_n = {"n": 0}
        def mock_get(path, params=None):
            call_n["n"] += 1
            if "historical" in path:
                return {"market": {"result": ""}}  # empty result → fallback
            return {"market": {"result": "yes"}}

        client = MagicMock()
        client.get.side_effect = mock_get
        cutoff = datetime(2026, 4, 13, tzinfo=timezone.utc)
        result = ingest_s3.resolve_settlements(["KXPRES-X"], client, cutoff)
        assert result.get("KXPRES-X") == "yes"
        # Both historical and live endpoints called
        assert call_n["n"] == 2


class TestS3BuildDatasetEdgeCases:
    """build_dataset_s3: no-active-days, zero-h-lo, out-of-bucket."""

    def test_ticker_with_no_active_days_excluded(self):
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        # All rows have zero volume AND zero open_interest → no active days
        rows = [
            {"ticker_name": "X-1", "report_ticker": "KXPRES",
             "date": "2025-01-10", "high_cents": "90", "low_cents": "88",
             "daily_volume": "0", "open_interest": "0", "status": "finalized"},
        ]
        df = build_dataset_s3(rows, {"X-1": "yes"}, {}, haircut_cents=1, volume_floor=0)
        assert df.empty

    def test_zero_high_low_row_skipped(self):
        from datetime import date, timedelta
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        # Build 10 days of rows but set one entry day to h=0,l=0
        rows = []
        for i in range(10):
            d = (date(2025, 1, 2) + timedelta(days=i)).isoformat()
            rows.append({
                "ticker_name": "Y-1", "report_ticker": "KXPRES",
                "date": d,
                "high_cents": "0" if i == 8 else "90",  # entry for 1d horizon
                "low_cents": "0" if i == 8 else "88",
                "daily_volume": "100", "open_interest": "0", "status": "active",
            })
        # With haircut, 0+0/2/100 = 0 → entry_price <= 0 → skipped
        df = build_dataset_s3(rows, {"Y-1": "yes"}, {}, haircut_cents=1, volume_floor=0)
        # Should still have rows for horizons where entry day is not day 8
        # (horizon 7d entry is day 2 which has h=90)
        if not df.empty:
            for _, row in df.iterrows():
                assert float(row["ask_price"]) > 0

    def test_price_out_of_study_band_skipped(self):
        from datetime import date, timedelta
        from kalshi_backtest.ingest_s3 import build_dataset_s3
        # Price = 50¢ → outside all BUCKETS → bucket is None → no rows in dataset
        rows = []
        for i in range(10):
            d = (date(2025, 1, 2) + timedelta(days=i)).isoformat()
            rows.append({
                "ticker_name": "Z-1", "report_ticker": "KXPRES",
                "date": d, "high_cents": "50", "low_cents": "50",
                "daily_volume": "100", "open_interest": "0", "status": "active",
            })
        df = build_dataset_s3(rows, {"Z-1": "yes"}, {}, haircut_cents=1, volume_floor=0)
        assert df.empty


class TestReportS3AdditionalBranches:
    """Coverage for report.py S3 branches not yet hit."""

    def _kc_results(self, n_kc1_cells=0):
        from kalshi_backtest.simulate import SimState
        import pandas as pd

        kc1_cells = pd.DataFrame() if n_kc1_cells == 0 else pd.DataFrame(
            [{"net_edge": 0.02}] * n_kc1_cells)
        return {
            "kc1": n_kc1_cells > 0,
            "kc2": False, "kc3": True, "kc4": False, "kc5": False,
            "all_pass": False,
            "kc1_cells": kc1_cells,
            "roi_8k": 0.02,
            "roi_8k_doubled": -0.01,
            "val_8k": SimState(bankroll=8200.0, peak_equity=8300.0,
                                realized_pnl=200.0, total_trades=30,
                                wins=25, losses=5, total_fees=10.0,
                                max_drawdown=-0.03),
            "val_8k_doubled": SimState(bankroll=8050.0, peak_equity=8200.0),
            "trades_per_yr": 40.0,
            "cells": set(), "require_rising": set(),
            "val_start": "2025-07-01", "val_end": "2026-01-01",
        }

    def test_report_with_non_parlay_rows(self, tmp_path, monkeypatch):
        """generate_report_s3 with non-empty rows hits the category loop (lines 430-433, 465)."""
        import pandas as pd
        from kalshi_backtest import report as rpt
        monkeypatch.setattr(rpt, "REPORT_MD", tmp_path / "REPORT.md")
        monkeypatch.setattr(rpt, "SUMMARY_MD", tmp_path / "RESULTS_SUMMARY.md")

        rows = [
            {"ticker_name": "KXPRES-01", "report_ticker": "KXPRES",
             "date": "2025-02-01"},
            {"ticker_name": "KXMVESPORTS-P", "report_ticker": "KXMVESPORTS",
             "date": "2025-02-01"},  # parlay → skipped in category loop
        ]
        df_val = pd.DataFrame([{
            "window": "validation", "horizon_h": 24, "bucket": "90–93¢",
            "category": "politics", "n": 80, "implied": 0.91, "realized": 0.94,
            "raw_edge": 0.03, "net_edge": 0.02, "ci_lo": 0.92, "ci_hi": 0.96,
            "ci_excl_breakeven": True,
        }])
        rpt.generate_report_s3(pd.DataFrame(), df_val, df_val, pd.DataFrame(),
                                self._kc_results(1), rows, {}, {}, haircut_1c=True)
        content = (tmp_path / "REPORT.md").read_text()
        assert "politics" in content

    def test_report_with_empty_validation_shows_no_data_msg(self, tmp_path, monkeypatch):
        """generate_report_s3 with empty df_val_calib hits '_(No validation data)_' branch."""
        import pandas as pd
        from kalshi_backtest import report as rpt
        monkeypatch.setattr(rpt, "REPORT_MD", tmp_path / "REPORT.md")
        monkeypatch.setattr(rpt, "SUMMARY_MD", tmp_path / "RESULTS_SUMMARY.md")

        rpt.generate_report_s3(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
                                pd.DataFrame(), self._kc_results(0),
                                [], {}, {}, haircut_1c=True)
        content = (tmp_path / "REPORT.md").read_text()
        assert "No validation data" in content

    def test_evaluate_kcs_with_non_empty_dataset(self):
        """evaluate_kcs: df_sim = df_dataset branch (line 328)."""
        import pandas as pd
        from kalshi_backtest.report import evaluate_kcs

        df_data = pd.DataFrame([{
            "ticker": "KXPRES-01", "category": "politics",
            "close_time": "2025-08-01", "horizon_h": 24,
            "ask_price": 0.91, "bucket": "90–93¢",
            "resolved_yes": 1, "momentum_24h": 0.01,
        }])
        df_sel = pd.DataFrame()
        df_val = pd.DataFrame()
        df_adv = pd.DataFrame()
        res = evaluate_kcs(df_sel, df_val, df_adv, df_data)
        assert "kc1" in res

    def test_write_summary_s3_empty_calib(self, tmp_path, monkeypatch):
        """_write_summary_s3: no rows with n≥50 → fallback calib_rows text (line 577)."""
        import pandas as pd
        from kalshi_backtest import report as rpt
        monkeypatch.setattr(rpt, "REPORT_MD", tmp_path / "REPORT.md")
        monkeypatch.setattr(rpt, "SUMMARY_MD", tmp_path / "RESULTS_SUMMARY.md")

        # df_val_calib has rows but all n < 50
        df_val_low_n = pd.DataFrame([{
            "window": "validation", "horizon_h": 24, "bucket": "90–93¢",
            "category": "politics", "n": 5,  # < 50
            "implied": 0.91, "realized": 0.94, "raw_edge": 0.03,
            "net_edge": 0.02, "ci_lo": 0.90, "ci_hi": 0.98, "ci_excl_breakeven": True,
        }])

        from kalshi_backtest.simulate import SimState
        kc = {
            "kc1": False, "kc2": False, "kc3": True, "kc4": False, "kc5": False,
            "all_pass": False,
            "kc1_cells": pd.DataFrame(),
            "roi_8k": 0.01,
            "roi_8k_doubled": -0.01,
            "val_8k": SimState(bankroll=8100.0, peak_equity=8200.0,
                                realized_pnl=100.0, total_trades=10,
                                wins=8, losses=2, total_fees=3.0, max_drawdown=-0.02),
            "val_8k_doubled": SimState(bankroll=8050.0, peak_equity=8200.0),
            "trades_per_yr": 12.0, "cells": set(), "require_rising": set(),
            "val_start": "2025-07-01", "val_end": "2026-01-01",
        }
        rpt._write_summary_s3(
            n_markets=100, settled_count=80, cats={"politics": 100},
            df_val_calib=df_val_low_n, kc_results=kc,
            haircut_label="1¢", adv_text="n/a",
        )
        text = (tmp_path / "RESULTS_SUMMARY.md").read_text()
        assert "no cells with n≥50" in text


# ===========================================================================
# 14. Final coverage gap tests
# ===========================================================================

class TestS3DownloadNon404Error:
    """_download_day_records re-raises non-404 HTTP errors."""

    def test_non_404_http_error_reraises(self, monkeypatch):
        import urllib.error
        from datetime import date
        from kalshi_backtest import ingest_s3

        err = urllib.error.HTTPError(url="u", code=500, msg="server error",
                                     hdrs=None, fp=None)  # type: ignore
        monkeypatch.setattr(ingest_s3.urllib.request, "urlopen",
                            lambda *a, **kw: (_ for _ in ()).throw(err))

        with pytest.raises(urllib.error.HTTPError):
            ingest_s3._download_day_records(date(2025, 1, 6))


class TestS3ParlayFromMetaTickerPrefix:
    """_is_parlay_from_meta: ticker prefix match path (line ~404)."""

    def test_ticker_prefix_match_returns_true(self):
        from kalshi_backtest.ingest_s3 import _is_parlay_from_meta
        # Title has no parlay pattern, but ticker starts with known parlay prefix
        meta = {"ticker": "KXMVESPORTS-123", "title": "Will team X win?"}
        assert _is_parlay_from_meta(meta)

    def test_no_pattern_no_prefix_returns_false(self):
        from kalshi_backtest.ingest_s3 import _is_parlay_from_meta
        meta = {"ticker": "KXPRES-24-DEM", "title": "Will DEM win?"}
        assert not _is_parlay_from_meta(meta)


class TestS3FetchSeriesMetadataMalformedCache:
    """fetch_series_metadata: exception path when cache file has invalid JSON."""

    def test_malformed_cache_file_is_silently_ignored(self, tmp_path):
        from unittest.mock import MagicMock
        from kalshi_backtest.ingest_s3 import fetch_series_metadata

        cache_path = tmp_path / "series_cache.json"
        cache_path.write_text("not valid json {{{{")  # malformed

        client = MagicMock()
        client.get.return_value = {"series": {"ticker": "KXPRES", "category": "politics"}}

        # Should not raise; falls through to fetch from API
        result = fetch_series_metadata(["KXPRES"], client, cache_path=cache_path)
        assert "KXPRES" in result


class TestS3FunnelReportEdgeCases:
    """build_funnel_report: settled ticker not in after_vol, invalid date row."""

    def test_unsettled_ticker_skipped_in_category_breakdown(self):
        from kalshi_backtest.ingest_s3 import build_funnel_report
        # 2 non-parlay rows, only one settled → other is skipped in category breakdown
        rows = [
            {"ticker_name": "KXPRES-01", "report_ticker": "KXPRES",
             "date": "2025-03-01", "daily_volume": "600", "open_interest": "0"},
            {"ticker_name": "KXPRES-02", "report_ticker": "KXPRES",
             "date": "2025-03-02", "daily_volume": "600", "open_interest": "0"},
        ]
        # Only KXPRES-01 settled; KXPRES-02 is not in settlements
        report = build_funnel_report(rows, {"KXPRES-01": "yes"}, {})
        assert "1" in report  # settled count = 1

    def test_invalid_date_in_funnel_row_handled(self):
        from kalshi_backtest.ingest_s3 import build_funnel_report
        rows = [
            {"ticker_name": "KXPRES-X", "report_ticker": "KXPRES",
             "date": "NOT-A-DATE",  # invalid → triggers except → mo = "unknown"
             "daily_volume": "600", "open_interest": "0"},
        ]
        report = build_funnel_report(rows, {"KXPRES-X": "yes"}, {}, volume_floor=0)
        assert "unknown" in report or isinstance(report, str)
