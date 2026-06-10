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
from scanner.loops.signal import (
    _classify_rejection,
    _climate_ticker_direction,
    _kalshi_event_ticker,
)
from scanner.loops.exit import _settled_yes_won


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


# ---------------------------------------------------------------------------
# Climate ticker direction parsing + B-side-only filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ticker,expected", [
    ("KXHIGHTNYC-26JUN09-T80",      "T"),
    ("KXLOWTSEA-26JUN10-B63.5",     "B"),
    ("KXHIGHTATL-26JUN08-B91.5",    "B"),
    ("KXHIGHTPHX-26JUN10-T105",     "T"),
    ("KXLOWTNYC-26JUN08-T60",       "T"),
    (None,                          None),
    ("",                            None),
    ("KXBTCD-26JUN-something",      None),   # not climate format
    ("KXHIGHTNYC-26JUN09",          None),   # missing direction segment
])
def test_climate_ticker_direction(ticker, expected):
    assert _climate_ticker_direction(ticker) == expected


def test_signal_loop_climate_direction_filter_is_b_only():
    """signal.py must skip kalshi_climate tickers whose direction is not 'B'.

    Edge-hunt 2026-06-09 showed T-direction climate markets net -37% ROI
    vs B-direction's +62% on similar n. The filter pins that finding so a
    future refactor can't accidentally re-enable T firing without a test
    update + (one hopes) fresh evidence.
    """
    import inspect
    import scanner.loops.signal as signal_module

    src = inspect.getsource(signal_module)
    # The filter must reference both the direction helper and a B comparison.
    assert "_climate_ticker_direction" in src, (
        "Signal loop must call _climate_ticker_direction to gate climate firings."
    )
    assert 'direction != "B"' in src, (
        "Signal loop must filter direction != 'B' for kalshi_climate firings."
    )


# ---------------------------------------------------------------------------
# Discover loop preserves prior model_prob / scored_at instead of nuking them.
# Pins the fix for the prod bug observed 2026-06-09 where discover defaulted
# new_model_prob=None, score.py only rescored where edge IS NULL, and the
# signal loop's `if model_prob is None: continue` then short-circuited
# every climate firing. Net effect: pool of candidates with edge populated
# but model_prob NULL — bot was firing only in the lucky window where
# score ran after discover and before the next discover poll.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Exit loop is hold-to-resolution: no stop-loss, no take-profit, no
# approaching-expiry forced exit. The strategy needs to collect full
# winners to justify the losing OTM bets; bailing on intraday bid-ask
# noise pays spread both ways and guarantees we never see the payouts.
# Only exits: real Kalshi settlement, plus a 24h-after-expiry janitor.
# ---------------------------------------------------------------------------


def test_exit_loop_has_no_stop_loss_or_take_profit():
    """exit.py must not reference any stop-loss / take-profit heuristic.

    These were ripped 2026-06-09 because (a) binary options cap loss
    at entry price already, so stop-loss adds no risk protection, and
    (b) the strategy thesis requires holding to resolution to collect
    full winners. Source inspection guards against a future refactor
    quietly re-adding them.
    """
    import inspect
    import scanner.loops.exit as exit_module

    src = inspect.getsource(exit_module)
    forbidden = [
        "catastrophic_stop",
        "stops_enabled",
        "cfg.stop_loss_pct",
        "cfg.take_profit_pct",
        "approaching_expiry",
    ]
    for needle in forbidden:
        assert needle not in src, (
            f"exit.py must not contain {needle!r} — that's a heuristic exit "
            f"the strategy has explicitly removed (2026-06-09)."
        )
    # The Kalshi-settlement and 24h-janitor paths must both still exist.
    assert "_settled_yes_won" in src
    assert "post_expiry_orphan" in src


# ---------------------------------------------------------------------------
# event_ticker derivation: signal loop must enforce per-event position cap.
# Pins the fix for the prod bug observed 2026-06-10 where signal.py read a
# phantom attribute (getattr(snapshot, "_event_ticker", None)) that was
# never set anywhere, so max_positions_per_event=1 silently did nothing.
# Bot stacked 9 positions on Dallas June 9 high-temp markets; all lost
# together when the underlying forecast was wrong.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ticker,expected", [
    ("KXHIGHTDAL-26JUN09-B90.5",  "KXHIGHTDAL-26JUN09"),
    ("KXHIGHTDAL-26JUN09-T90",    "KXHIGHTDAL-26JUN09"),
    ("KXLOWTNYC-26JUN10-B62.5",   "KXLOWTNYC-26JUN10"),
    ("KXHIGHTPHX-26JUN10-T105",   "KXHIGHTPHX-26JUN10"),
    ("NODASH",                    None),
    (None,                        None),
    ("",                          None),
])
def test_kalshi_event_ticker(ticker, expected):
    assert _kalshi_event_ticker(ticker) == expected


def test_signal_loop_uses_real_event_ticker_not_phantom_attr():
    """signal.py must derive event_ticker from the market_ticker, not
    getattr(snapshot, '_event_ticker', None) — which always returned None
    because no code path ever sets `_event_ticker` on a MarketSnapshot.

    Inspect just the run_signal_loop function body (excluding docstrings
    elsewhere in the module that document the rip history)."""
    import inspect
    from scanner.loops.signal import run_signal_loop
    src = inspect.getsource(run_signal_loop)
    assert "_kalshi_event_ticker(ticker)" in src, (
        "run_signal_loop must call _kalshi_event_ticker(ticker) to derive event_ticker."
    )
    assert 'getattr(snapshot, "_event_ticker"' not in src, (
        "run_signal_loop must not read the phantom `_event_ticker` attribute."
    )


# ---------------------------------------------------------------------------
# Settlement attribution: trust ONLY Kalshi's explicit result field.
# Pins the fix for the prod bug observed 2026-06-10 where _settled_yes_won
# inferred outcomes from last_price (>=95 → yes, <=5 → no) when Kalshi's
# result field was empty. Caused contradictory settlements (T90 NO and
# B96.5 NO on the same Dallas June 9 underlying — geometrically impossible).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("market_data,expected,label", [
    ({"status": "settled",   "result": "yes"},                                True,  "explicit yes"),
    ({"status": "settled",   "result": "no"},                                 False, "explicit no"),
    ({"status": "finalized", "result": "yes"},                                True,  "finalized + yes"),
    ({"status": "finalized", "result": "no"},                                 False, "finalized + no"),
    ({"status": "settled",   "result": None, "last_price": 99},               None,  "high last_price without result must NOT infer yes"),
    ({"status": "settled",   "result": None, "last_price": 1},                None,  "low last_price without result must NOT infer no"),
    ({"status": "settled",   "result": "",   "last_price": 100},              None,  "empty result string + last_price=100 must NOT infer"),
    ({"status": "open",      "result": "yes"},                                None,  "open status returns None regardless of result"),
    ({},                                                                      None,  "empty dict"),
])
def test_settled_yes_won(market_data, expected, label):
    assert _settled_yes_won(market_data) == expected, label


def test_settled_yes_won_does_not_infer_from_last_price():
    """The function body must not branch on last_price comparisons. The old
    fallbacks (>=95 → yes, <=5 → no) introduced contradictions when Kalshi
    marked a market 'settled' but had not yet published its result."""
    import inspect
    src = inspect.getsource(_settled_yes_won)
    # Drop the docstring before scanning — docstring documents the rip.
    body = src.split('"""', 2)[-1] if '"""' in src else src
    for bad in ("last_price >=", "last_price <=", "last_price>", "last_price<"):
        assert bad not in body, (
            f"_settled_yes_won body must not use {bad!r} — that's the "
            f"last_price-as-result inference we ripped 2026-06-10."
        )


# ---------------------------------------------------------------------------
# Climate model train/inference sigma alignment (HIGH-2 fix, 2026-06-10).
# A prior FORECAST_SKILL_FACTOR=0.4 was applied at inference but not in
# training, inflating inference z-scores by 2.5× vs the training range and
# driving the model into the sigmoid tails (root cause of the 0.80-0.90
# band 0/3 miscalibration). Inference must match training: sigma * sqrt(d).
# ---------------------------------------------------------------------------


def test_scaled_sigma_no_skill_factor_matches_training():
    """Inference's _scaled_sigma must equal `sigma * sqrt(days_ahead)`,
    matching train_climate_model.py:99 exactly. Any constant multiplier
    distorts the train/inference z-score distributions."""
    import math
    from app.services.climate_probability_model import _scaled_sigma
    assert _scaled_sigma(10.0, 1) == pytest.approx(10.0)
    assert _scaled_sigma(10.0, 4) == pytest.approx(10.0 * math.sqrt(4))
    assert _scaled_sigma(5.0, 9) == pytest.approx(5.0 * math.sqrt(9))
    # days_ahead floor at 1
    assert _scaled_sigma(10.0, 0) == pytest.approx(10.0)
    # non-positive sigma falls back to 1.0
    assert _scaled_sigma(0.0, 1) == 1.0
    assert _scaled_sigma(-5.0, 1) == 1.0


def test_climate_probability_model_no_forecast_skill_factor():
    """The skill-factor multiplier must not be assigned or used in the
    inference module. Docstrings may reference the historic constant for
    documentation; what matters is that no live code path multiplies sigma
    by it."""
    import inspect
    import app.services.climate_probability_model as m
    src = inspect.getsource(m)
    forbidden_live_patterns = [
        "FORECAST_SKILL_FACTOR = ",
        "forecast_sigma * FORECAST_SKILL_FACTOR",
        "FORECAST_SKILL_FACTOR *",
        "* FORECAST_SKILL_FACTOR",
    ]
    for pat in forbidden_live_patterns:
        assert pat not in src, (
            f"climate_probability_model.py must not contain {pat!r} — "
            f"that's the 2.5× train/inference mismatch we ripped 2026-06-10."
        )


# ---------------------------------------------------------------------------
# Signal loop in-pass position cap + cumulative bankroll + fresh edge
# (HIGH-1 + M3 + M5, audited 2026-06-10). open_positions is loaded once
# and never grows during a pass; without per-pass counters one scan cycle
# could open dozens of positions past the cap and over-allocate bankroll.
# ---------------------------------------------------------------------------


def test_signal_loop_uses_fired_this_pass_counter():
    """run_signal_loop must increment a counter per fire and use it to
    enforce max_open_positions across the whole pass."""
    import inspect
    from scanner.loops.signal import run_signal_loop
    src = inspect.getsource(run_signal_loop)
    assert "fired_this_pass" in src, (
        "Signal loop must track positions opened in the current pass."
    )
    assert "len(open_positions) + fired_this_pass" in src, (
        "Position cap must include in-pass increments, not just the "
        "initial open_positions snapshot."
    )


def test_signal_loop_uses_remaining_bankroll_for_kelly():
    """Kelly sizing must subtract this-pass spend from the available bankroll."""
    import inspect
    from scanner.loops.signal import run_signal_loop
    src = inspect.getsource(run_signal_loop)
    assert "spent_cents_this_pass" in src
    assert "remaining_cents" in src, (
        "Kelly call must use remaining bankroll, not the pass-start cached value."
    )


def test_signal_loop_recomputes_edge_against_fresh_price():
    """When a live client returns a fresh market_price, signal loop must
    re-gate and re-size on the fresh-edge, not the stale snapshot.edge."""
    import inspect
    from scanner.loops.signal import run_signal_loop
    src = inspect.getsource(run_signal_loop)
    assert "fresh_edge = snapshot.model_prob - market_price" in src
    assert "if fresh_edge < config.min_edge:" in src


# ---------------------------------------------------------------------------
# Exit loop defers live-mode P&L to kalshi_live_sync (M4, 2026-06-10).
# Paper math (no fees) racing the fee-aware live sync produced wrong
# realized P&L in live mode.
# ---------------------------------------------------------------------------


def test_exit_loop_skips_pnl_write_for_live_mode():
    """run_exit_loop must skip the (exit - fill) * qty pnl write when
    cfg.mode == 'live' — kalshi_live_sync owns that attribution."""
    import inspect
    from scanner.loops.exit import run_exit_loop
    src = inspect.getsource(run_exit_loop)
    assert 'cfg.mode == "live"' in src
    # The Kalshi-settled path must have an explicit live-mode guard around
    # the pnl_usd write.
    assert "Let kalshi_live_sync attribute realized P&L" in src


# ---------------------------------------------------------------------------
# Score loop no longer reads phantom _event_ticker attribute (2026-06-10).
# Parses date directly from row.ticker.
# ---------------------------------------------------------------------------


def test_score_climate_does_not_read_phantom_event_ticker():
    import inspect
    import scanner.loops.score as score_module
    src = inspect.getsource(score_module)
    assert 'getattr(row, "_event_ticker"' not in src, (
        "score.py must not read the phantom _event_ticker attribute."
    )


def test_discover_preserves_old_model_prob_default():
    """discover.py must default new_model_prob to old_model_prob, not None.

    The default-None behavior interacted with score.py's `WHERE edge IS NULL`
    selector to leave climate snapshots permanently un-scorable after the
    second discover poll. Default must mirror new_edge=old_edge.
    """
    import inspect
    import scanner.loops.discover as discover_module

    src = inspect.getsource(discover_module)
    # The default assignment (outside any conditional) must use old_model_prob.
    assert "new_model_prob = old_model_prob" in src, (
        "discover.py must default new_model_prob to old_model_prob; "
        "defaulting to None nukes scoring on every discover pass and "
        "blocks the signal loop from firing."
    )
    # And we must actually be fetching old_model_prob from the DB.
    assert "MarketSnapshot.model_prob" in src and "old_model_prob = existing" in src, (
        "discover.py must SELECT MarketSnapshot.model_prob and unpack it "
        "into old_model_prob for the default to be meaningful."
    )
