"""Tests for sync_kalshi_live — the reconciliation loop between local
Signal records and Kalshi's portfolio endpoints.

State machine under test:
  placed -> filled -> settled (yes/no/void)
  placed -> cancelled
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.kalshi_live_sync import (
    _apply_fill_from_order,
    _apply_fill_from_position,
    _apply_settlement,
    _sync_signal,
    sync_kalshi_live,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_signal(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        venue="kalshi",
        signal_type="live",
        status="placed",
        market_ticker="KXETH-26MAY2617-B2080",
        exchange_order_id="order-abc-123",
        entry_price=0.64,
        quantity=39,
        cost_usd=24.96,
        fill_price=None,
        fill_quantity=None,
        filled_at=None,
        exit_price=None,
        pnl_usd=None,
        pnl_pct=None,
        resolved_at=None,
        error_message=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _position(ticker, contracts, total_traded):
    return {
        "ticker": ticker,
        "position_fp": str(contracts),
        "total_traded_dollars": str(total_traded),
        "market_exposure_dollars": str(total_traded),
        "fees_paid_dollars": "0.10",
        "realized_pnl_dollars": "0.00",
    }


def _settlement(ticker, result, revenue_cents, cost_dollars=0.0, fees=0.0, yes_count=39):
    """Build a settlement record. `yes_count` defaults to a non-zero value so
    the never-filled-cancellation branch doesn't fire; pass yes_count=0
    explicitly to test that path."""
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "market_result": result,
        "revenue": revenue_cents,
        "yes_total_cost_dollars": str(cost_dollars),
        "no_total_cost_dollars": "0.0",
        "fee_cost": str(fees),
        "yes_count_fp": str(yes_count),
        "no_count_fp": "0.00",
    }


def _order(status, fill_count=0, taker_cost=0.0, yes_price=0.0):
    return {
        "order_id": "order-abc-123",
        "ticker": "KXETH-26MAY2617-B2080",
        "status": status,
        "fill_count_fp": str(fill_count),
        "taker_fill_cost_dollars": str(taker_cost),
        "yes_price_dollars": str(yes_price),
    }


# ---------------------------------------------------------------------------
# _apply_settlement — terminal transition
# ---------------------------------------------------------------------------


class TestApplySettlement:
    def test_yes_settlement_records_profit(self):
        sig = _make_signal(status="filled", fill_price=0.64, fill_quantity=39, cost_usd=24.96)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        sett = _settlement("KXETH-26MAY2617-B2080", "yes", 3900, cost_dollars=24.96, fees=0.07)

        _apply_settlement(sig, sett, counts)

        assert sig.status == "settled_win"
        assert sig.exit_price == 1.0
        assert sig.pnl_usd == pytest.approx(39.0 - 24.96 - 0.07)
        assert sig.cost_usd == pytest.approx(24.96)
        assert sig.resolved_at is not None
        assert counts["settled"] == 1

    def test_no_settlement_records_full_loss(self):
        sig = _make_signal(status="filled", fill_price=0.36, fill_quantity=50, cost_usd=18.0)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        sett = _settlement("KXBTC-X", "no", 0, cost_dollars=18.0, fees=0.05)

        _apply_settlement(sig, sett, counts)

        assert sig.status == "settled_loss"
        assert sig.exit_price == 0.0
        assert sig.pnl_usd == pytest.approx(-18.0 - 0.05)
        assert counts["settled"] == 1

    def test_void_uses_fill_price_as_exit(self):
        sig = _make_signal(status="filled", fill_price=0.30, fill_quantity=10, cost_usd=3.0)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        sett = _settlement("KXBTC-VOID", "void", 300, cost_dollars=3.0, fees=0.0)

        _apply_settlement(sig, sett, counts)

        assert sig.status == "settled_breakeven"
        assert sig.exit_price == pytest.approx(0.30)
        assert sig.pnl_usd == pytest.approx(0.0)
        assert counts["settled"] == 1

    def test_settlement_falls_back_to_signal_cost_when_missing(self):
        sig = _make_signal(status="filled", cost_usd=10.0)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        sett = _settlement("X", "yes", 1500)
        sett["yes_total_cost_dollars"] = "0.0"

        _apply_settlement(sig, sett, counts)

        assert sig.pnl_usd == pytest.approx(5.0)
        assert sig.cost_usd == pytest.approx(10.0)

    def test_pnl_pct_computed(self):
        sig = _make_signal(status="filled", cost_usd=20.0)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        sett = _settlement("X", "yes", 3000, cost_dollars=20.0, fees=0.0)

        _apply_settlement(sig, sett, counts)

        assert sig.pnl_pct == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# _apply_fill_from_position
# ---------------------------------------------------------------------------


class TestApplyFillFromPosition:
    def test_fills_from_position(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        pos = _position("KXETH-X", 39, 24.96)

        _apply_fill_from_position(sig, pos, counts)

        assert sig.status == "filled"
        assert sig.fill_quantity == 39
        assert sig.fill_price == pytest.approx(24.96 / 39)
        assert sig.cost_usd == pytest.approx(24.96)
        assert sig.filled_at is not None
        assert counts["filled"] == 1

    def test_zero_position_no_op(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        pos = _position("X", 0, 0)

        _apply_fill_from_position(sig, pos, counts)

        assert sig.status == "placed"
        assert counts["filled"] == 0

    def test_keeps_signal_cost_when_kalshi_cost_missing(self):
        sig = _make_signal(status="placed", cost_usd=25.0, entry_price=0.50)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        pos = _position("X", 50, 0)

        _apply_fill_from_position(sig, pos, counts)

        assert sig.fill_quantity == 50
        # Falls back to entry_price when total_traded is 0
        assert sig.fill_price == pytest.approx(0.50)
        assert sig.cost_usd == 25.0


# ---------------------------------------------------------------------------
# _apply_fill_from_order
# ---------------------------------------------------------------------------


class TestApplyFillFromOrder:
    def test_fills_from_executed_order(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        order = _order("executed", fill_count=39, taker_cost=24.96, yes_price=0.64)

        _apply_fill_from_order(sig, order, counts)

        assert sig.status == "filled"
        assert sig.fill_quantity == 39
        assert sig.fill_price == pytest.approx(24.96 / 39)
        assert sig.cost_usd == pytest.approx(24.96)
        assert counts["filled"] == 1

    def test_falls_back_to_limit_price_when_no_cost(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        order = _order("executed", fill_count=20, taker_cost=0, yes_price=0.07)

        _apply_fill_from_order(sig, order, counts)

        assert sig.fill_price == pytest.approx(0.07)


# ---------------------------------------------------------------------------
# _sync_signal — orchestration
# ---------------------------------------------------------------------------


class TestSyncSignal:
    def test_settlement_takes_priority_over_fill_detection(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        client = MagicMock()
        positions = {"KXETH-26MAY2617-B2080": _position("KXETH-26MAY2617-B2080", 39, 24.96)}
        settlements = {"KXETH-26MAY2617-B2080": _settlement("KXETH-26MAY2617-B2080", "yes", 3900, 24.96, 0.07)}

        _sync_signal(sig, client, positions, settlements, counts)

        assert sig.status == "settled_win"
        assert counts["settled"] == 1
        assert counts["filled"] == 0

    def test_missing_ticker_skipped(self):
        sig = _make_signal(market_ticker=None)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        _sync_signal(sig, MagicMock(), {}, {}, counts)
        assert sig.status == "placed"
        assert counts == {"filled": 0, "settled": 0, "cancelled": 0}

    def test_filled_status_only_checks_settlement(self):
        # A filled signal should never go through fill-detection again;
        # it only advances if Kalshi reports settlement.
        sig = _make_signal(status="filled", fill_price=0.64, fill_quantity=39)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        positions = {"KXETH-26MAY2617-B2080": _position("KXETH-26MAY2617-B2080", 39, 24.96)}

        _sync_signal(sig, MagicMock(), positions, {}, counts)

        assert sig.status == "filled"
        assert counts == {"filled": 0, "settled": 0, "cancelled": 0}

    def test_placed_with_position_promotes_to_filled(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        positions = {"KXETH-26MAY2617-B2080": _position("KXETH-26MAY2617-B2080", 39, 24.96)}

        _sync_signal(sig, MagicMock(), positions, {}, counts)

        assert sig.status == "filled"
        assert counts["filled"] == 1

    def test_placed_with_no_position_falls_back_to_order_status(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        client = MagicMock()

        async def fake_get_order(_oid):
            return _order("executed", fill_count=39, taker_cost=24.96, yes_price=0.64)

        client.get_order = fake_get_order

        _sync_signal(sig, client, {}, {}, counts)

        assert sig.status == "filled"
        assert counts["filled"] == 1

    def test_cancelled_order_marks_signal_cancelled(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        client = MagicMock()

        async def fake_get_order(_oid):
            return _order("canceled")

        client.get_order = fake_get_order

        _sync_signal(sig, client, {}, {}, counts)

        assert sig.status == "cancelled"
        assert counts["cancelled"] == 1
        assert sig.error_message and "canceled" in sig.error_message

    def test_resting_order_no_op(self):
        sig = _make_signal(status="placed")
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        client = MagicMock()

        async def fake_get_order(_oid):
            return _order("resting")

        client.get_order = fake_get_order

        _sync_signal(sig, client, {}, {}, counts)

        assert sig.status == "placed"
        assert counts == {"filled": 0, "settled": 0, "cancelled": 0}


# ---------------------------------------------------------------------------
# sync_kalshi_live — top-level loop
# ---------------------------------------------------------------------------


class TestSyncKalshiLive:
    def _mock_session(self, signals):
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = signals
        session.execute.return_value = result_mock
        return session

    def test_no_pending_signals_is_no_op(self):
        session = self._mock_session([])

        counts = sync_kalshi_live(session, {})

        assert counts == {"filled": 0, "settled": 0, "cancelled": 0}
        session.commit.assert_not_called()

    def test_user_without_client_skipped(self):
        sig = _make_signal()
        session = self._mock_session([sig])

        counts = sync_kalshi_live(session, {})  # no client for the user

        assert counts == {"filled": 0, "settled": 0, "cancelled": 0}
        assert sig.status == "placed"  # untouched

    def test_commits_only_when_state_changed(self):
        sig = _make_signal()
        session = self._mock_session([sig])
        client = MagicMock()

        async def positions():
            return [_position("KXETH-26MAY2617-B2080", 39, 24.96)]

        async def settlements(limit=100):
            return []

        client.get_positions = positions
        client.get_settlements = settlements

        counts = sync_kalshi_live(session, {str(sig.user_id): client})

        assert counts["filled"] == 1
        session.commit.assert_called_once()

    def test_no_commit_when_no_state_change(self):
        sig = _make_signal()
        session = self._mock_session([sig])
        client = MagicMock()

        async def positions():
            return []

        async def settlements(limit=100):
            return []

        async def get_order(_oid):
            return _order("resting")

        client.get_positions = positions
        client.get_settlements = settlements
        client.get_order = get_order

        counts = sync_kalshi_live(session, {str(sig.user_id): client})

        assert counts == {"filled": 0, "settled": 0, "cancelled": 0}
        session.commit.assert_not_called()

    def test_individual_signal_failure_doesnt_abort_others(self):
        sig_good = _make_signal(market_ticker="KX-GOOD")
        sig_bad = _make_signal(market_ticker=None)  # will be skipped (no ticker)
        # Use distinct user_ids so they're definitely separate signals
        sig_bad.user_id = sig_good.user_id  # same user for simplicity
        session = self._mock_session([sig_bad, sig_good])
        client = MagicMock()

        async def positions():
            return [_position("KX-GOOD", 10, 5.0)]

        async def settlements(limit=100):
            return []

        client.get_positions = positions
        client.get_settlements = settlements

        counts = sync_kalshi_live(session, {str(sig_good.user_id): client})

        assert counts["filled"] == 1
        assert sig_good.status == "filled"
        assert sig_bad.status == "placed"  # skipped due to missing ticker


# ---------------------------------------------------------------------------
# Regression: the +$39 win exact scenario
# ---------------------------------------------------------------------------


class TestNeverFilledSettlement:
    """Settlements where Kalshi shows we owned zero contracts mean our limit
    order never filled before the market settled. The cost_usd in our DB is
    theoretical, not money actually spent — should be cancelled, not lost."""

    def _zero_position_settlement(self, ticker, result):
        return {
            "ticker": ticker,
            "event_ticker": "X",
            "market_result": result,
            "revenue": 0,
            "yes_count_fp": "0.00",
            "no_count_fp": "0.00",
            "yes_total_cost_dollars": "0.000000",
            "no_total_cost_dollars": "0.000000",
            "fee_cost": "0.000000",
        }

    def test_yes_result_with_zero_position_is_cancelled(self):
        # The KXETH-B2070 production bug: settled YES on Kalshi, but our limit
        # order at $0.66 never filled. Sync was marking settled_loss with the
        # full cost_usd as the loss. Should be cancelled.
        sig = _make_signal(
            status="placed",
            market_ticker="KXETH-26MAY2616-B2070",
            entry_price=0.66,
            quantity=37,
            cost_usd=24.42,
        )
        counts = {"filled": 0, "settled": 0, "cancelled": 0}

        _apply_settlement(
            sig,
            self._zero_position_settlement("KXETH-26MAY2616-B2070", "yes"),
            counts,
        )

        # Order never filled before settlement → expired_unfilled (status
        # taxonomy split out from generic "cancelled" so the dashboard can
        # show why this never traded).
        assert sig.status == "expired_unfilled"
        assert sig.pnl_usd is None  # not a P&L event
        assert sig.exit_price is None
        assert sig.error_message and "never_filled" in sig.error_message
        assert counts["cancelled"] == 1
        assert counts["settled"] == 0

    def test_no_result_with_zero_position_is_cancelled(self):
        sig = _make_signal(status="placed", market_ticker="X", cost_usd=10.0)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}

        _apply_settlement(sig, self._zero_position_settlement("X", "no"), counts)

        assert sig.status == "expired_unfilled"
        assert counts["cancelled"] == 1

    def test_nonzero_position_still_settles_normally(self):
        # Regression: a real position that lost should still settle_loss, not
        # be misread as never-filled.
        sig = _make_signal(status="filled", cost_usd=18.0, fill_price=0.36, fill_quantity=50)
        counts = {"filled": 0, "settled": 0, "cancelled": 0}
        sett = {
            "ticker": "X",
            "event_ticker": "X",
            "market_result": "no",
            "revenue": 0,
            "yes_count_fp": "50.00",
            "no_count_fp": "0.00",
            "yes_total_cost_dollars": "18.000000",
            "no_total_cost_dollars": "0.000000",
            "fee_cost": "0.05",
        }

        _apply_settlement(sig, sett, counts)

        assert sig.status == "settled_loss"
        assert sig.pnl_usd == pytest.approx(-18.05)
        assert counts["settled"] == 1
        assert counts["cancelled"] == 0


class TestRealWorldScenario:
    """Reproduces the exact KXETH-26MAY2617-B2080 settlement we saw on AWS.

    Bot placed 39 contracts at $0.64 = $24.96 cost. Market settled YES,
    revenue $39, fees $0.07. Net PnL should be $13.97.
    """

    def test_kxeth_b2080_yes_settlement(self):
        sig = _make_signal(
            status="placed",
            market_ticker="KXETH-26MAY2617-B2080",
            entry_price=0.64,
            quantity=39,
            cost_usd=24.96,
        )
        counts = {"filled": 0, "settled": 0, "cancelled": 0}

        sett = {
            "ticker": "KXETH-26MAY2617-B2080",
            "event_ticker": "KXETH-26MAY2617",
            "market_result": "yes",
            "revenue": 3900,
            "yes_total_cost_dollars": "24.960000",
            "fee_cost": "0.070000",
            "yes_count_fp": "39.00",
            "no_count_fp": "0.00",
        }
        _sync_signal(sig, MagicMock(), {}, {"KXETH-26MAY2617-B2080": sett}, counts)

        assert sig.status == "settled_win"
        assert sig.exit_price == 1.0
        assert sig.pnl_usd == pytest.approx(13.97)
        assert sig.pnl_pct == pytest.approx(55.97, rel=0.01)
        assert sig.resolved_at is not None
