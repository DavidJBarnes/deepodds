"""
Unit tests for backtest.replay.

Verifies trailing-series semantics, ctx construction, replay P&L identity,
and the Task 4 regression (cash cannot go negative).
"""
import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from backtest.replay import (
    _build_ctx,
    _max_drawdown,
    _precompute_trailing,
    _sharpe,
    run_replay,
)
from backtest.scaling import scaled_config
from carry.config import CarryConfig
from carry.engine import PERIODS_PER_YEAR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frames(n_hours: int = 200, funding_rate_hourly: float = 0.0001,
                 perp_price: float = 50_000.0, spot_price: float = 49_900.0,
                 start: str = "2020-01-01") -> dict[str, pd.DataFrame]:
    """
    Construct a synthetic hourly DataFrame for BTC + ETH with constant prices + funding.
    """
    idx = pd.date_range(start, periods=n_hours, freq="1h", tz="UTC")
    rows = {
        "ts": idx,
        "funding_hourly": [funding_rate_hourly] * n_hours,
        "perp_close": [perp_price] * n_hours,
        "spot_close": [spot_price] * n_hours,
    }
    df = pd.DataFrame(rows)
    return {"BTC": df, "ETH": df.copy()}


# ---------------------------------------------------------------------------
# Trailing series
# ---------------------------------------------------------------------------

def test_trailing_series_window():
    """Rolling mean matches hand-computed values for a known sequence."""
    frames = _make_frames(n_hours=300, funding_rate_hourly=0.0001)
    # Vary the BTC funding rate
    btc_df = frames["BTC"].copy()
    btc_df["funding_hourly"] = range(300)   # 0, 1, 2, ..., 299 (as float)
    btc_df["funding_hourly"] = btc_df["funding_hourly"].astype(float) * 1e-6
    frames["BTC"] = btc_df

    cfg = CarryConfig(trailing_window_hours=10)
    ts = _precompute_trailing(frames, cfg)

    s = ts["BTC"]
    # At index 9 (10th hour, window full): mean of [0,1,...,9]*1e-6 = 4.5e-6 * PERIODS_PER_YEAR
    ts9 = btc_df["ts"].iloc[9]
    expected = (sum(range(10)) / 10) * 1e-6 * PERIODS_PER_YEAR
    assert abs(float(s[ts9]) - expected) < 1e-8


def test_trailing_returns_value_from_first_observation():
    """With min_periods=1, trailing is non-None from the first hour."""
    frames = _make_frames(n_hours=10, funding_rate_hourly=0.0001)
    cfg = CarryConfig(trailing_window_hours=168)
    ts = _precompute_trailing(frames, cfg)
    s = ts["BTC"]
    first_ts = frames["BTC"]["ts"].iloc[0]
    assert not math.isnan(float(s[first_ts])), "Trailing should be non-None from tick 1"


# ---------------------------------------------------------------------------
# Context construction (bid/ask sides)
# ---------------------------------------------------------------------------

def test_ctx_bid_ask_sides():
    """
    perp_bid < mark < perp_ask  (engine shorts at bid = worse for the engine).
    spot_ask > spot  > spot_bid (engine buys at ask = worse for the engine).
    """
    frames = _make_frames(n_hours=5, perp_price=50_000.0, spot_price=49_800.0)
    cfg = CarryConfig(spot_spread_bps=2.0)
    price_idx = {
        coin: {row["ts"]: row for _, row in df.iterrows()}
        for coin, df in frames.items()
    }
    ts = frames["BTC"]["ts"].iloc[0]
    ctx = _build_ctx(ts, frames, price_idx, cfg)

    assert "BTC" in ctx
    c = ctx["BTC"]
    assert c["perp_bid"] < c["mark"] < c["perp_ask"]
    spot = frames["BTC"].iloc[0]["spot_close"]
    assert c["spot_ask"] > spot > c["spot_bid"]


def test_ctx_spread_magnitude():
    """With 2.0 spot_spread_bps, half-spread = 1bp on each side."""
    frames = _make_frames(n_hours=5, spot_price=50_000.0)
    cfg = CarryConfig(spot_spread_bps=2.0)
    price_idx = {
        coin: {row["ts"]: row for _, row in df.iterrows()}
        for coin, df in frames.items()
    }
    ts = frames["BTC"]["ts"].iloc[0]
    ctx = _build_ctx(ts, frames, price_idx, cfg)
    c = ctx["BTC"]
    half_spread = 50_000.0 * 1.0 / 10_000   # 1bp of 50k = $5
    assert abs(c["spot_ask"] - 50_000.0 - half_spread) < 0.01
    assert abs(50_000.0 - c["spot_bid"] - half_spread) < 0.01


# ---------------------------------------------------------------------------
# Replay P&L identity — known funding, hand-computed result
# ---------------------------------------------------------------------------

def test_hourly_gaps_do_not_crash_replay():
    """Gaps > 24h in data (common in early Binance archives) must not crash — engine clamps."""
    # Build a frame with a 48h gap in the middle
    ts1 = pd.date_range("2020-01-01", periods=48, freq="1h", tz="UTC")
    ts2 = pd.date_range("2020-01-05", periods=48, freq="1h", tz="UTC")  # 48h gap
    idx = ts1.append(ts2)
    df = pd.DataFrame({
        "ts": idx, "funding_hourly": [0.0001] * 96,
        "perp_close": [50_000.0] * 96, "spot_close": [49_900.0] * 96,
    })
    cfg = scaled_config(100_000.0, trailing_window_hours=1)
    result = run_replay({"BTC": df, "ETH": df.copy()}, cfg)   # must not raise
    assert result.capital == 100_000.0


def test_replay_pnl_equals_funding_minus_fees():
    """
    Synthetic fixture: constant rich funding, constant price, 200 hours.
    Final P&L = (hours_deployed × notional × funding_hourly) − fees  (within float tolerance).
    """
    n_hours = 200
    funding_rate = 0.0002          # 0.02%/hr annualizes to ~175%, well above hurdle
    perp = spot = 50_000.0
    frames = _make_frames(n_hours=n_hours, funding_rate_hourly=funding_rate,
                          perp_price=perp, spot_price=spot)

    # Use a capital level where max_notional_per_symbol can actually open
    cfg = scaled_config(
        100_000.0,
        min_funding_hurdle_ann=0.06,
        rich_funding_ann=0.20,
        trailing_window_hours=1,   # opens on tick 1
        exit_funding_ann=0.0,
    )

    result = run_replay(frames, cfg)

    # After fees, net P&L should be positive and dominated by funding income
    assert result.net_pnl > 0, "Should be profitable with very high constant funding"
    assert result.gross_funding_collected > 0
    # P&L ≈ funding_collected − fees − entry_basis_cost (constant price, delta-neutral).
    # Entry basis cost: open fills at perp_bid < mark, spot_ask > mark (cross the spread).
    # With 2bps spread on 30k notional: basis ≈ $12 (2 × $6).  Allow $20 tolerance.
    expected_approx = result.gross_funding_collected - result.total_fees
    assert abs(result.net_pnl - expected_approx) < 20.0, (
        f"P&L {result.net_pnl:.2f} deviates >$20 from funding({result.gross_funding_collected:.2f})"
        f" - fees({result.total_fees:.2f}) = {expected_approx:.2f}"
    )


# ---------------------------------------------------------------------------
# Task 4 regression — cash cannot go negative
# ---------------------------------------------------------------------------

def test_cash_never_goes_negative_small_capital():
    """
    At small capital ($5k), the engine must NOT open a position that drives cash negative.
    The fix in engine.tick() uses committed_estimate instead of just tgt.
    """
    n_hours = 300
    # High funding → engine wants to open
    frames = _make_frames(n_hours=n_hours, funding_rate_hourly=0.001,
                          perp_price=30_000.0, spot_price=29_900.0)
    cfg = scaled_config(
        5_000.0,
        min_funding_hurdle_ann=0.04,
        rich_funding_ann=0.10,
        trailing_window_hours=1,
        exit_funding_ann=0.0,
    )
    result = run_replay(frames, cfg)
    # run_replay already asserts cash >= -0.01 per tick; reaching here means it passed
    assert result.portfolio.cash_usd >= -0.01, (
        f"Cash went negative: ${result.portfolio.cash_usd:.4f}"
    )


def test_cash_never_goes_negative_two_symbols():
    """Opening both BTC and ETH with limited capital should not overdraw cash."""
    frames = _make_frames(n_hours=300, funding_rate_hourly=0.001)
    cfg = scaled_config(
        8_000.0,
        min_funding_hurdle_ann=0.04,
        rich_funding_ann=0.10,
        trailing_window_hours=1,
        exit_funding_ann=0.0,
    )
    result = run_replay(frames, cfg)
    assert result.portfolio.cash_usd >= -0.01


# ---------------------------------------------------------------------------
# v2 rebalancing — Jan-2020 scenario (price ramp +70%)
# ---------------------------------------------------------------------------

def test_jan2020_scenario_no_liquidation_no_kill():
    """
    Synthetic fixture: price ramps +70% over 1,000 hourly ticks with constant
    positive funding. At $8k capital, 2x leverage, rebalancing must prevent
    any liquidation or kill event.
    """
    n_hours = 1_000
    entry_price = 130.0
    final_price = entry_price * 1.70   # +70%
    funding_rate = 0.0001              # 0.01%/hr = ~87.6%/yr, well above hurdle

    prices = [entry_price + (final_price - entry_price) * i / n_hours for i in range(n_hours)]
    idx = pd.date_range("2020-01-01", periods=n_hours, freq="1h", tz="UTC")
    df = pd.DataFrame({
        "ts": idx,
        "funding_hourly": [funding_rate] * n_hours,
        "perp_close": prices,
        "spot_close": prices,
    })
    frames = {"ETH": df, "BTC": df.copy()}

    cfg = scaled_config(
        8_000.0,
        min_funding_hurdle_ann=0.06,
        rich_funding_ann=0.20,
        trailing_window_hours=1,    # opens on tick 1
        exit_funding_ann=0.0,
        max_leverage_band=3.0,
    )
    result = run_replay(frames, cfg)

    assert result.liquidation_count == 0, (
        f"Expected zero liquidations, got {result.liquidation_count}"
    )
    assert result.kill_events == 0, (
        f"Expected zero kill events, got {result.kill_events}"
    )
    assert result.rebalance_topup_count > 0 or result.rebalance_recenter_count > 0, (
        "Expected at least one rebalance event for a +70% price move"
    )
    assert result.gross_funding_collected > 0, "Should have collected some funding"
    # Delta-neutral: P&L ≈ funding − fees (within spread basis tolerance)
    expected_approx = result.gross_funding_collected - result.total_fees
    assert abs(result.net_pnl - expected_approx) < 30.0, (
        f"P&L {result.net_pnl:.2f} deviates >$30 from funding-fees={expected_approx:.2f}"
    )


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def test_max_drawdown_flat():
    eq = pd.Series([100, 100, 100, 100], dtype=float)
    assert _max_drawdown(eq) == pytest.approx(0.0)


def test_max_drawdown_monotone_down():
    eq = pd.Series([100, 90, 80, 70], dtype=float)
    mdd = _max_drawdown(eq)
    assert abs(mdd - (-0.30)) < 0.001   # peak 100 → trough 70 = −30%


def test_max_drawdown_recovers():
    eq = pd.Series([100, 80, 60, 100], dtype=float)
    mdd = _max_drawdown(eq)
    assert abs(mdd - (-0.40)) < 0.001   # 100 → 60 = −40%


def test_sharpe_positive_drift():
    """A monotonically rising equity curve should have positive Sharpe."""
    eq = pd.Series([1000 + i for i in range(365)], dtype=float)
    s = _sharpe(eq, rf_annual=0.04)
    assert s > 0


def test_sharpe_flat_equity():
    """Flat equity = zero excess return = nan Sharpe."""
    eq = pd.Series([1000.0] * 100)
    s = _sharpe(eq)
    assert math.isnan(s)
