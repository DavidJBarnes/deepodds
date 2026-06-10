"""Tests for scanner/loops/exit.py reading settlement state from
MarketSnapshot instead of per-ticker Kalshi calls.

Covers the structural fix in PR fix/exit-loop-read-from-snapshot:
when a filled signal's MarketSnapshot row reports status='settled' with
a yes/no result, the exit loop must record the binary outcome without
any HTTP client. When status='closed' (Kalshi's brief settling-in-
progress state) it must do nothing.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from scanner.loops.exit import _settled_yes_won, _snapshot_to_market_data, run_exit_loop


# ---------------------------------------------------------------------------
# Pure unit: _settled_yes_won + _snapshot_to_market_data
# ---------------------------------------------------------------------------


def _snap(**overrides):
    """Construct a MarketSnapshot-shaped object (just an attribute bag)."""
    defaults = dict(
        ticker="KXHIGHTNYC-TEST",
        status=None,
        result=None,
        last_price=None,
        bid_price=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_settled_yes_won_returns_true_on_yes_result():
    md = _snapshot_to_market_data(_snap(status="settled", result="yes"))
    assert _settled_yes_won(md) is True


def test_settled_yes_won_returns_false_on_no_result():
    md = _snapshot_to_market_data(_snap(status="settled", result="no"))
    assert _settled_yes_won(md) is False


def test_settled_yes_won_returns_none_when_status_open():
    md = _snapshot_to_market_data(_snap(status="open", result=None))
    assert _settled_yes_won(md) is None


def test_settled_yes_won_returns_none_on_closed_pre_settle():
    """Kalshi's 'closed' state is post-trading, pre-settlement — wait."""
    md = _snapshot_to_market_data(_snap(status="closed", result=None))
    assert _settled_yes_won(md) is None


def test_settled_yes_won_ignores_last_price_when_result_empty():
    """last_price must NOT infer an outcome — the fallback was removed
    2026-06-10 after it misattributed settlements (impossible T90/B96.5
    both-False state on Dallas). Only Kalshi's explicit result counts."""
    for lp in (98, 2, 50):
        md = _snapshot_to_market_data(_snap(status="settled", result=None, last_price=lp))
        assert _settled_yes_won(md) is None


# ---------------------------------------------------------------------------
# Integration-ish: run_exit_loop with a mocked Session
# ---------------------------------------------------------------------------


def _make_signal(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        venue="kalshi_climate",
        signal_type="paper",
        status="filled",
        market_ticker="KXHIGHTNYC-26JUN05-T80",
        entry_price=0.30,
        fill_price=0.30,
        quantity=10,
        fill_quantity=10,
        filled_at=datetime.now(timezone.utc) - timedelta(hours=12),
        expiry_time=datetime.now(timezone.utc) + timedelta(hours=12),
        exit_price=None,
        pnl_usd=None,
        pnl_pct=None,
        resolved_at=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_cfg(**overrides):
    defaults = dict(
        user_id=uuid.uuid4(),
        mode="paper",
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        exit_edge=-0.5,
        min_hold_minutes=0,
        min_hours_to_expiry=2,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _stub_session(filled_signals, snapshots_by_ticker, climate_cfgs=None):
    """Build a MagicMock Session whose .execute() returns a Result-like
    object whose .scalars().all() / .scalar_one_or_none() chain returns
    the data we want based on the query's primary entity.
    """
    climate_cfgs = climate_cfgs or {}

    def execute(stmt):
        # Inspect the SQL stmt to figure out what's being asked for.
        text = str(stmt).lower()
        result = MagicMock()
        if "from signals" in text:
            result.scalars.return_value.all.return_value = filled_signals
        elif "from market_snapshots" in text:
            result.scalars.return_value.all.return_value = list(snapshots_by_ticker.values())
        elif "from climate_configs" in text:
            cfg = next(iter(climate_cfgs.values()), None)
            result.scalar_one_or_none.return_value = cfg
        else:
            result.scalars.return_value.all.return_value = []
            result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute.side_effect = execute
    session.add = MagicMock()
    session.commit = MagicMock()
    return session


def test_filled_paper_signal_with_settled_yes_snapshot_records_win():
    user_id = uuid.uuid4()
    sig = _make_signal(user_id=user_id)
    cfg = _make_cfg(user_id=user_id)
    snap = _snap(
        ticker=sig.market_ticker, status="settled", result="yes", bid_price=0.95,
    )
    session = _stub_session(
        filled_signals=[sig],
        snapshots_by_ticker={sig.market_ticker: snap},
        climate_cfgs={user_id: cfg},
    )

    run_exit_loop(session, engine=MagicMock())

    assert sig.exit_price == 1.0
    assert sig.status == "settled_win"
    # qty=10, fill=0.30 → pnl=(1.0 - 0.30) * 10 = 7.00
    assert sig.pnl_usd == pytest.approx(7.0)
    session.commit.assert_called()


def test_filled_paper_signal_with_settled_no_snapshot_records_loss():
    user_id = uuid.uuid4()
    sig = _make_signal(user_id=user_id)
    cfg = _make_cfg(user_id=user_id)
    snap = _snap(
        ticker=sig.market_ticker, status="settled", result="no", bid_price=0.01,
    )
    session = _stub_session(
        filled_signals=[sig],
        snapshots_by_ticker={sig.market_ticker: snap},
        climate_cfgs={user_id: cfg},
    )

    run_exit_loop(session, engine=MagicMock())

    assert sig.exit_price == 0.0
    assert sig.status == "settled_loss"
    assert sig.pnl_usd == pytest.approx(-3.0)


def test_filled_signal_with_closed_snapshot_does_not_exit():
    """Kalshi 'closed' is pre-settlement — must wait."""
    user_id = uuid.uuid4()
    sig = _make_signal(user_id=user_id)
    cfg = _make_cfg(user_id=user_id)
    # status='closed' is pre-settlement. No result yet, low bid.
    snap = _snap(
        ticker=sig.market_ticker, status="closed", result=None, bid_price=0.04,
    )
    session = _stub_session(
        filled_signals=[sig],
        snapshots_by_ticker={sig.market_ticker: snap},
        climate_cfgs={user_id: cfg},
    )

    run_exit_loop(session, engine=MagicMock())

    # Status should not have changed to a settled_* state via the Kalshi-
    # settle path. (A heuristic exit on bid IS allowed when stops/TP are
    # enabled, but our cfg has them all at 0 — hold-to-resolution mode.)
    assert sig.exit_price is None
    assert sig.status == "filled"


def test_missing_snapshot_continues_silently():
    """Race: signal placed before next discover cycle. Skip, retry next loop."""
    user_id = uuid.uuid4()
    sig = _make_signal(user_id=user_id)
    cfg = _make_cfg(user_id=user_id)
    session = _stub_session(
        filled_signals=[sig],
        snapshots_by_ticker={},  # no snapshot for this ticker
        climate_cfgs={user_id: cfg},
    )

    run_exit_loop(session, engine=MagicMock())

    assert sig.exit_price is None
    assert sig.status == "filled"
