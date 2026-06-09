"""Tests for raw_model_prob plumbing + Platt training source + status taxonomy.

Covers:
- predict_climate_probability returns both raw_model_prob (pre-Platt) and
  model_prob (post-Platt). When no calibrator is loaded they're equal.
- climate_calibration._fetch_training_pairs reads raw_model_prob, unions
  Signal rows with MarketSnapshot rows, dedupes by ticker.
- scanner.loops.signal._classify_rejection maps Kalshi errors to granular
  status strings.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.climate_probability_model import predict_climate_probability
from app.services.climate_calibration import _fetch_training_pairs, reset_cache
from scanner.loops.signal import _classify_rejection


# ---------------------------------------------------------------------------
# predict_climate_probability raw/calibrated round-trip
# ---------------------------------------------------------------------------


def test_predict_returns_both_raw_and_calibrated_fields(monkeypatch):
    # Pin the calibrator to identity so raw == calibrated, simplifying the
    # round-trip assertion. (The real calibrator gets tested by
    # apply_platt's own logic; here we just check the plumbing.)
    reset_cache()
    monkeypatch.setattr(
        "app.services.climate_calibration.get_calibrator",
        lambda: None,  # no calibrator → apply_platt passes through
    )

    result = predict_climate_probability(
        forecast_value=72.0,
        floor_strike=70.0,
        cap_strike=75.0,
        strike_type="between",
        forecast_sigma=3.0,
        market_price=0.20,
        city="NYC",
        days_ahead=1,
    )

    assert result.raw_model_prob is not None
    assert result.model_prob == pytest.approx(result.raw_model_prob, abs=1e-6)


def test_predict_calibrated_differs_from_raw_when_calibrator_active(monkeypatch):
    """When the calibrator has non-identity coefficients, raw != calibrated."""
    reset_cache()
    monkeypatch.setattr(
        "app.services.climate_calibration.get_calibrator",
        lambda: {"a": 0.2, "b": -2.0, "n": 50, "wins": 6, "fitted_at": "x"},
    )

    result = predict_climate_probability(
        forecast_value=72.0,
        floor_strike=70.0,
        cap_strike=75.0,
        strike_type="between",
        forecast_sigma=3.0,
        market_price=0.20,
        city="NYC",
        days_ahead=1,
    )

    # raw is what the XGBoost model predicted; calibrated is sigmoid(a*raw + b),
    # which with these coefficients compresses any raw to ~0.12.
    assert result.raw_model_prob > 0.0
    assert result.model_prob != result.raw_model_prob
    assert 0.10 < result.model_prob < 0.15


def test_platt_disabled_env_flag_forces_passthrough(monkeypatch):
    """PLATT_ENABLED=false must bypass the calibrator even when one is loaded.

    Catches the prod incident on 2026-06-05 where a degenerate Platt fit
    (range collapsed to 0.14–0.16) was distorting model_prob and flooding
    the signal loop. The env flag is the kill switch.
    """
    reset_cache()
    monkeypatch.setenv("PLATT_ENABLED", "false")
    # Calibrator IS loaded — but the flag should make apply_platt ignore it.
    monkeypatch.setattr(
        "app.services.climate_calibration.get_calibrator",
        lambda: {"a": 0.2, "b": -2.0, "n": 50, "wins": 6, "fitted_at": "x"},
    )

    result = predict_climate_probability(
        forecast_value=72.0,
        floor_strike=70.0,
        cap_strike=75.0,
        strike_type="between",
        forecast_sigma=3.0,
        market_price=0.20,
        city="NYC",
        days_ahead=1,
    )

    assert result.model_prob == pytest.approx(result.raw_model_prob, abs=1e-6)


# ---------------------------------------------------------------------------
# _fetch_training_pairs: reads raw_model_prob, unions signal + snapshot
# ---------------------------------------------------------------------------


def _make_signal_row(ticker, raw_mp, status, exit_price=None, filled_at=None, resolved_at=None):
    return (ticker, raw_mp, status, exit_price, filled_at, resolved_at)


def _make_snapshot_row(ticker, raw_mp, result):
    return (ticker, raw_mp, result)


def _stub_session(sig_rows, snap_rows):
    def execute(stmt):
        text = str(stmt).lower()
        result = MagicMock()
        if "from signals" in text:
            result.all.return_value = sig_rows
        elif "from market_snapshots" in text:
            result.all.return_value = snap_rows
        else:
            result.all.return_value = []
        return result

    session = MagicMock()
    session.execute.side_effect = execute
    return session


def test_fetch_training_pairs_signals_only():
    """Pre-existing settled Signal rows produce the training pairs."""
    now = datetime.now(timezone.utc)
    sig_rows = [
        _make_signal_row("KX-A", 0.25, "settled_loss", exit_price=0.0),
        _make_signal_row("KX-B", 0.55, "settled_win", exit_price=1.0),
    ]
    session = _stub_session(sig_rows, [])
    pairs = _fetch_training_pairs(session)
    assert len(pairs) == 2
    assert (0.25, 0) in pairs
    assert (0.55, 1) in pairs


def test_fetch_training_pairs_snapshots_added_for_unsignaled_markets():
    """Scored snapshots that finalized on Kalshi contribute pairs too."""
    sig_rows = []
    snap_rows = [
        _make_snapshot_row("KX-A", 0.15, "no"),
        _make_snapshot_row("KX-B", 0.85, "no"),  # model said yes likely, actually no
    ]
    session = _stub_session(sig_rows, snap_rows)
    pairs = _fetch_training_pairs(session)
    assert len(pairs) == 2
    assert (0.15, 0) in pairs
    assert (0.85, 0) in pairs


def test_fetch_training_pairs_signal_wins_over_snapshot_dedup():
    """Same ticker in both sources → Signal row takes precedence."""
    sig_rows = [
        _make_signal_row("KX-DUP", 0.50, "settled_win", exit_price=1.0),
    ]
    snap_rows = [
        _make_snapshot_row("KX-DUP", 0.49, "yes"),
    ]
    session = _stub_session(sig_rows, snap_rows)
    pairs = _fetch_training_pairs(session)
    # Only one pair, and it's the Signal-side value.
    assert pairs == [(0.50, 1)]


def test_fetch_training_pairs_drops_invalid_settles():
    """Non-binary exit AND short hold → not a usable signal."""
    now = datetime.now(timezone.utc)
    sig_rows = [
        # Stop-out at 0.32, held 30 minutes — neither real nor long-held.
        _make_signal_row(
            "KX-BAD", 0.40, "settled_loss",
            exit_price=0.32,
            filled_at=now - timedelta(minutes=30),
            resolved_at=now,
        ),
    ]
    session = _stub_session(sig_rows, [])
    assert _fetch_training_pairs(session) == []


# ---------------------------------------------------------------------------
# _classify_rejection: error string → granular status
# ---------------------------------------------------------------------------


def test_classify_rejection_insufficient_balance():
    err = '400 Bad Request: {"error":{"code":"insufficient_balance","message":"insufficient balance"}}'
    assert _classify_rejection(err) == "rejected_insufficient_funds"


def test_classify_rejection_too_many_requests():
    err = '429 Too Many Requests: {"error":{"code":"too_many_requests","message":"too many requests"}}'
    assert _classify_rejection(err) == "rejected_rate_limit"


def test_classify_rejection_unknown_falls_through_to_cancelled():
    assert _classify_rejection("some random connection error") == "cancelled"


def test_classify_rejection_handles_empty():
    assert _classify_rejection("") == "cancelled"
    assert _classify_rejection(None) == "cancelled"


# ---------------------------------------------------------------------------
# Signal-loop dedup: one-shot per (user, ticker), regardless of prior status.
# Pins the fix for the refire-after-stop-out bug observed 2026-06-09 where
# a stop-loss exit on KXHIGHTATL-26JUN09-B80.5 flipped the row to
# 'settled_loss', dropping it out of the no-refire set; the scanner then
# refired on the same ticker 4 more times within 50 seconds at identical
# entries, stacking losses on a single bad idea.
# ---------------------------------------------------------------------------


def test_signal_loop_dedup_source_does_not_filter_by_status():
    """The dedup query in signal.py must not constrain on Signal.status.

    Any status filter (the old _NO_REFIRE_STATUSES tuple) leaves settled
    states out and reopens the refire window. Read the source directly
    so this guards the actual loop, not a re-implementation in the test.
    """
    import inspect
    import scanner.loops.signal as signal_module

    src = inspect.getsource(signal_module)

    # Locate the dedup existence query block. It's the only `Signal.market_ticker == ticker` query.
    needle_start = src.index("Signal.market_ticker == ticker")
    # Walk forward to the closing paren of the .where(...) clause containing it.
    # Pull a generous window so any sibling Signal.status reference would land in it.
    window = src[max(0, needle_start - 400): needle_start + 400]
    assert "Signal.status" not in window, (
        "Refire dedup must not filter by Signal.status — that lets settled_loss "
        "(stop-out) immediately reopen the ticker for refire. Window:\n" + window
    )
