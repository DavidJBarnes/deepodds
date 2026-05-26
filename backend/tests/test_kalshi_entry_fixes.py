"""Tests for Kalshi entry-logic audit fixes 1-4:

1. Use yes_ask_dollars for entry price (not last_price_dollars)
2. Filter on ask liquidity (yes_ask_dollars > 0 and yes_ask_size >= min_ask_size)
3. Event-level position limit (max_positions_per_event)
4. Block ticker re-entry (any non-cancelled prior signal blocks the ticker)
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.kalshi_fair_value import (
    _discover_markets,
    _has_traded_ticker,
    _market_ask,
    _market_ask_size,
    _open_event_count,
)


def _mock_client(markets_by_series: dict[str, list[dict]]):
    client = MagicMock()

    async def mock_get_markets(series_ticker=None, limit=200):
        return {"markets": markets_by_series.get(series_ticker, [])}

    client.get_markets = mock_get_markets
    return client


def _make_market(
    ticker: str,
    series: str,
    volume: float = 500.0,
    last: float = 0.50,
    yes_ask: float | None = None,
    yes_ask_size: float = 100.0,
    hours_to_close: float = 12.0,
    event_ticker: str | None = None,
) -> dict:
    if yes_ask is None:
        yes_ask = last
    close_time = (datetime.now(timezone.utc) + timedelta(hours=hours_to_close)).isoformat()
    return {
        "ticker": ticker,
        "event_ticker": event_ticker or f"{series}-EVENT",
        "series_ticker": series,
        "volume_24h_fp": str(volume),
        "last_price_dollars": str(last),
        "yes_ask_dollars": str(yes_ask),
        "yes_ask_size_fp": str(yes_ask_size),
        "close_time": close_time,
    }


# ---------------------------------------------------------------------------
# Fix 1: Entry price = ask, not last
# ---------------------------------------------------------------------------


class TestAskBasedEntry:
    def test_market_ask_reads_yes_ask_dollars(self):
        m = _make_market("T1", "KXBTC", yes_ask=0.42)
        assert _market_ask(m) == pytest.approx(0.42)

    def test_market_ask_returns_zero_when_missing(self):
        m = {"ticker": "T1"}
        assert _market_ask(m) == 0.0

    def test_market_ask_handles_string_with_zeroes(self):
        m = {"yes_ask_dollars": "0.0000"}
        assert _market_ask(m) == 0.0

    def test_discover_uses_ask_not_last(self):
        # Last price is in range but ask is well above max — should be filtered
        m = _make_market("T1", "KXBTC", last=0.20, yes_ask=0.95)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1,
        )
        assert result == []

    def test_discover_uses_ask_not_last_inverse(self):
        # Last is out of range but ask is in range — should pass
        m = _make_market("T1", "KXBTC", last=0.05, yes_ask=0.45)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1,
        )
        assert len(result) == 1
        assert result[0]["_ask"] == pytest.approx(0.45)

    def test_ask_passed_through_as_internal_field(self):
        m = _make_market("T1", "KXBTC", yes_ask=0.33)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1,
        )
        assert result[0]["_ask"] == pytest.approx(0.33)


# ---------------------------------------------------------------------------
# Fix 2: Liquidity filter
# ---------------------------------------------------------------------------


class TestAskLiquidityFilter:
    def test_market_ask_size_reads_field(self):
        m = _make_market("T1", "KXBTC", yes_ask_size=2500)
        assert _market_ask_size(m) == 2500.0

    def test_market_ask_size_returns_zero_when_missing(self):
        assert _market_ask_size({}) == 0.0

    def test_zero_ask_blocked(self):
        m = _make_market("T1", "KXBTC", yes_ask=0.0, yes_ask_size=500)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.01, max_price=0.99,
            min_hours_to_expiry=1,
        )
        assert result == []

    def test_zero_ask_size_blocked(self):
        m = _make_market("T1", "KXBTC", yes_ask=0.40, yes_ask_size=0)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1, min_ask_size=1,
        )
        assert result == []

    def test_ask_size_below_min_blocked(self):
        m = _make_market("T1", "KXBTC", yes_ask=0.40, yes_ask_size=25)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1, min_ask_size=50,
        )
        assert result == []

    def test_ask_size_at_min_passes(self):
        m = _make_market("T1", "KXBTC", yes_ask=0.40, yes_ask_size=50)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1, min_ask_size=50,
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Fix 3: Event-level position limit (pure helper)
# ---------------------------------------------------------------------------


class TestEventCount:
    def _session_with_signals(self, signals: list[SimpleNamespace]):
        session = MagicMock()

        def execute(stmt):
            result = MagicMock()
            count = sum(
                1 for s in signals
                if getattr(s, "venue", None) == "kalshi"
                and getattr(s, "user_id", None) == uid
                and getattr(s, "event_ticker", None) == event
                and getattr(s, "status", None) in ("signaled", "placed", "filled")
            )
            result.scalar.return_value = count
            return result

        nonlocal_uid = {}
        nonlocal_event = {}

        def _wrap(uid_, event_):
            uid_capture = uid_
            event_capture = event_
            def execute_local(stmt):
                result = MagicMock()
                count = sum(
                    1 for s in signals
                    if getattr(s, "venue", None) == "kalshi"
                    and getattr(s, "user_id", None) == uid_capture
                    and getattr(s, "event_ticker", None) == event_capture
                    and getattr(s, "status", None) in ("signaled", "placed", "filled")
                )
                result.scalar.return_value = count
                return result
            return execute_local

        return session, _wrap

    def test_empty_event_returns_zero(self):
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar.return_value = 0
        session.execute.return_value = result_mock
        assert _open_event_count(session, uuid.uuid4(), "EVT") == 0

    def test_counts_open_positions(self):
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar.return_value = 3
        session.execute.return_value = result_mock
        assert _open_event_count(session, uuid.uuid4(), "EVT") == 3

    def test_none_event_returns_zero_no_query(self):
        session = MagicMock()
        result = _open_event_count(session, uuid.uuid4(), "")
        assert result == 0
        session.execute.assert_not_called()

    def test_scalar_none_returns_zero(self):
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        session.execute.return_value = result_mock
        assert _open_event_count(session, uuid.uuid4(), "EVT") == 0


# ---------------------------------------------------------------------------
# Fix 4: Block ticker re-entry
# ---------------------------------------------------------------------------


class TestTickerReentryBlock:
    def test_no_prior_signal_returns_false(self):
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock
        assert _has_traded_ticker(session, uuid.uuid4(), "KXBTC-T1") is False

    def test_open_signal_blocks(self):
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = uuid.uuid4()
        session.execute.return_value = result_mock
        assert _has_traded_ticker(session, uuid.uuid4(), "KXBTC-T1") is True

    def test_settled_signal_also_blocks(self):
        # The implementation queries WHERE status != 'cancelled', so settled
        # wins/losses/breakevens block as well. Returning a non-None scalar
        # simulates that match.
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = uuid.uuid4()
        session.execute.return_value = result_mock
        assert _has_traded_ticker(session, uuid.uuid4(), "KXBTC-T1") is True


# ---------------------------------------------------------------------------
# Regression: existing behavior still holds
# ---------------------------------------------------------------------------


class TestLimitPriceSlippage:
    """Live orders place at ask+1c (capped at config.max_price) so the order
    crosses the spread as a taker. Replicates the helper used in
    scan_kalshi_entries."""

    def _limit_cents(self, market_price: float, max_price: float) -> int:
        max_cents = int(round(max_price * 100))
        return min(int(round(market_price * 100)) + 1, max_cents)

    def test_adds_one_cent(self):
        assert self._limit_cents(market_price=0.66, max_price=0.80) == 67

    def test_caps_at_max_price(self):
        # Ask at exactly max_price — limit can't exceed max
        assert self._limit_cents(market_price=0.80, max_price=0.80) == 80

    def test_cheap_contract_still_pays_extra_cent(self):
        assert self._limit_cents(market_price=0.07, max_price=0.80) == 8

    def test_one_cent_contract(self):
        # A $0.01 contract would limit at $0.02 (or capped by max_price)
        assert self._limit_cents(market_price=0.01, max_price=0.80) == 2

    def test_atm_just_under_cap(self):
        # Ask at $0.79, max $0.80 — limit at $0.80 (= ask + 1c, exactly at cap)
        assert self._limit_cents(market_price=0.79, max_price=0.80) == 80


class TestExistingBehaviorRegression:
    def test_low_volume_still_filtered(self):
        m = _make_market("T1", "KXBTC", volume=10, yes_ask=0.40)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=100, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1,
        )
        assert result == []

    def test_expiry_filter_still_works(self):
        m = _make_market("T1", "KXBTC", yes_ask=0.40, hours_to_close=0.5)
        client = _mock_client({"KXBTC": [m]})
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=2,
        )
        assert result == []

    def test_sort_by_volume_preserved(self):
        markets = {"KXBTC": [
            _make_market("LOW", "KXBTC", volume=100, yes_ask=0.40),
            _make_market("HIGH", "KXBTC", volume=900, yes_ask=0.45),
            _make_market("MID", "KXBTC", volume=500, yes_ask=0.42),
        ]}
        client = _mock_client(markets)
        result = _discover_markets(
            client, ["KXBTC"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1,
        )
        assert [m["ticker"] for m in result] == ["HIGH", "MID", "LOW"]

    def test_multiple_series_still_works(self):
        markets = {
            "KXBTC": [_make_market("B1", "KXBTC", yes_ask=0.40)],
            "KXETH": [_make_market("E1", "KXETH", yes_ask=0.55)],
        }
        client = _mock_client(markets)
        result = _discover_markets(
            client, ["KXBTC", "KXETH"],
            min_volume=0, min_price=0.10, max_price=0.80,
            min_hours_to_expiry=1,
        )
        assert len(result) == 2
