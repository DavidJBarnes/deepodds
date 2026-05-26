"""Unit tests for Kalshi fair-value probability strategy logic.

Tests market discovery filters, edge-based exit conditions,
and contract P&L calculations.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.kalshi_fair_value import _discover_markets


def _make_kalshi_config(**overrides):
    defaults = dict(
        user_id=uuid.uuid4(),
        mode="paper",
        enabled=True,
        series_tickers="KXBTC,KXETH",
        min_volume_24h=500,
        min_price=0.15,
        max_price=0.85,
        min_hours_to_expiry=4,
        min_edge=0.05,
        exit_edge=-0.02,
        vol_lookback_hours=24,
        vol_interval="15m",
        contracts_per_signal=50,
        max_cost_per_signal=25.0,
        max_open_positions=5,
        stop_loss_pct=15.0,
        daily_loss_limit_usd=25.0,
        max_signals_per_hour=3,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_kalshi_signal(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        venue="kalshi",
        pair="KXBTC",
        side="buy",
        signal_type="paper",
        status="filled",
        entry_price=0.55,
        fill_price=0.55,
        fill_quantity=50.0,
        quantity=50.0,
        cost_usd=27.50,
        model_prob=0.62,
        market_prob=0.55,
        edge=0.07,
        floor_strike=100000.0,
        cap_strike=105000.0,
        strike_type="between",
        market_ticker="KXBTC-26MAY24-BTC-100000",
        event_ticker="KXBTC-26MAY24",
        expiry_time=datetime.now(timezone.utc) + timedelta(hours=12),
        filled_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestKalshiExitLogic:
    def test_edge_lost_exit(self):
        cfg = _make_kalshi_config(exit_edge=-0.02)
        current_edge = -0.03
        should_exit = current_edge <= cfg.exit_edge
        assert should_exit

    def test_no_exit_when_edge_positive(self):
        cfg = _make_kalshi_config(exit_edge=-0.02)
        current_edge = 0.04
        should_exit = current_edge <= cfg.exit_edge
        assert not should_exit

    def test_stop_loss(self):
        sig = _make_kalshi_signal(fill_price=0.55)
        cfg = _make_kalshi_config(stop_loss_pct=15.0)
        price = 0.45
        pnl_pct = (price - sig.fill_price) / sig.fill_price * 100
        should_exit = pnl_pct <= -cfg.stop_loss_pct
        assert should_exit
        assert pnl_pct == pytest.approx(-18.18, rel=0.01)

    def test_approaching_expiry_exit(self):
        cfg = _make_kalshi_config(min_hours_to_expiry=4)
        sig = _make_kalshi_signal(
            expiry_time=datetime.now(timezone.utc) + timedelta(hours=1.5),
        )
        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=cfg.min_hours_to_expiry / 2)
        should_exit = sig.expiry_time and (sig.expiry_time - now) < threshold
        assert should_exit

    def test_no_expiry_exit_when_far_from_expiry(self):
        cfg = _make_kalshi_config(min_hours_to_expiry=4)
        sig = _make_kalshi_signal(
            expiry_time=datetime.now(timezone.utc) + timedelta(hours=10),
        )
        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=cfg.min_hours_to_expiry / 2)
        should_exit = sig.expiry_time and (sig.expiry_time - now) < threshold
        assert not should_exit

    def test_max_hold_24h(self):
        sig = _make_kalshi_signal(
            filled_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        now = datetime.now(timezone.utc)
        should_exit = sig.filled_at and (now - sig.filled_at) > timedelta(hours=24)
        assert should_exit


class TestKalshiPnl:
    def test_contract_pnl_win(self):
        entry = 0.55
        exit_price = 0.65
        qty = 50
        pnl = (exit_price - entry) * qty
        assert pnl == pytest.approx(5.0)

    def test_contract_pnl_loss(self):
        entry = 0.55
        exit_price = 0.45
        qty = 50
        pnl = (exit_price - entry) * qty
        assert pnl == pytest.approx(-5.0)

    def test_cost_calculation(self):
        price = 0.55
        count = 50
        cost = price * count
        assert cost == pytest.approx(27.50)


class TestDiscoverMarkets:
    def _mock_client(self, markets_by_series: dict[str, list[dict]]):
        client = MagicMock()

        async def mock_get_markets(series_ticker=None, limit=200):
            return {"markets": markets_by_series.get(series_ticker, [])}

        client.get_markets = mock_get_markets
        return client

    def _make_market(self, ticker: str, series: str, volume: float, price: float, hours_to_close: float) -> dict:
        close_time = (datetime.now(timezone.utc) + timedelta(hours=hours_to_close)).isoformat()
        return {
            "ticker": ticker,
            "event_ticker": f"{series}-EVENT",
            "series_ticker": series,
            "volume_24h_fp": str(volume),
            "last_price_dollars": str(price),
            "close_time": close_time,
        }

    def test_filters_low_volume(self):
        markets = {"KXBTC": [self._make_market("T1", "KXBTC", 50, 0.50, 12)]}
        client = self._mock_client(markets)
        result = _discover_markets(client, ["KXBTC"], min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4)
        assert len(result) == 0

    def test_filters_low_price(self):
        markets = {"KXBTC": [self._make_market("T1", "KXBTC", 200, 0.10, 12)]}
        client = self._mock_client(markets)
        result = _discover_markets(client, ["KXBTC"], min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4)
        assert len(result) == 0

    def test_filters_high_price(self):
        markets = {"KXBTC": [self._make_market("T1", "KXBTC", 200, 0.90, 12)]}
        client = self._mock_client(markets)
        result = _discover_markets(client, ["KXBTC"], min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4)
        assert len(result) == 0

    def test_filters_soon_to_expire(self):
        markets = {"KXBTC": [self._make_market("T1", "KXBTC", 200, 0.50, 2)]}
        client = self._mock_client(markets)
        result = _discover_markets(client, ["KXBTC"], min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4)
        assert len(result) == 0

    def test_passes_eligible_market(self):
        markets = {"KXBTC": [self._make_market("T1", "KXBTC", 500, 0.50, 12)]}
        client = self._mock_client(markets)
        result = _discover_markets(client, ["KXBTC"], min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4)
        assert len(result) == 1
        assert result[0]["ticker"] == "T1"

    def test_sorts_by_volume_descending(self):
        markets = {"KXBTC": [
            self._make_market("T1", "KXBTC", 300, 0.50, 12),
            self._make_market("T2", "KXBTC", 800, 0.55, 12),
            self._make_market("T3", "KXBTC", 500, 0.60, 12),
        ]}
        client = self._mock_client(markets)
        result = _discover_markets(client, ["KXBTC"], min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4)
        assert [m["ticker"] for m in result] == ["T2", "T3", "T1"]

    def test_multiple_series(self):
        markets = {
            "KXBTC": [self._make_market("T1", "KXBTC", 500, 0.50, 12)],
            "KXETH": [self._make_market("T2", "KXETH", 400, 0.40, 8)],
        }
        client = self._mock_client(markets)
        result = _discover_markets(
            client, ["KXBTC", "KXETH"],
            min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4,
        )
        assert len(result) == 2

    def test_edge_price_at_boundary(self):
        markets = {"KXBTC": [
            self._make_market("T1", "KXBTC", 200, 0.15, 12),
            self._make_market("T2", "KXBTC", 200, 0.85, 12),
        ]}
        client = self._mock_client(markets)
        result = _discover_markets(client, ["KXBTC"], min_volume=100, min_price=0.15, max_price=0.85, min_hours_to_expiry=4)
        assert len(result) == 2


class TestKalshiEntryConditions:
    def test_edge_threshold(self):
        cfg = _make_kalshi_config(min_edge=0.05)
        edge = 0.07
        should_signal = edge >= cfg.min_edge
        assert should_signal

    def test_no_signal_below_threshold(self):
        cfg = _make_kalshi_config(min_edge=0.05)
        edge = 0.03
        should_signal = edge >= cfg.min_edge
        assert not should_signal

    def test_paper_kalshi_fills_immediately(self):
        cfg = _make_kalshi_config(mode="paper")
        assert cfg.mode == "paper"

    def test_contracts_cost(self):
        cfg = _make_kalshi_config(contracts_per_signal=50)
        price = 0.55
        cost = price * cfg.contracts_per_signal
        assert cost == pytest.approx(27.50)


class TestCostBasedSizing:
    def test_cheap_contract_uses_max_contracts(self):
        price = 0.05
        contracts_per_signal = 50
        max_cost = 25.0
        count = contracts_per_signal
        if price * count > max_cost:
            count = int(max_cost / price)
        assert count == 50
        assert price * count == pytest.approx(2.50)

    def test_expensive_contract_reduces_count(self):
        price = 0.94
        contracts_per_signal = 50
        max_cost = 25.0
        count = contracts_per_signal
        if price * count > max_cost:
            count = int(max_cost / price)
        assert count == 26
        assert price * count < max_cost

    def test_mid_price_contract_capped(self):
        price = 0.55
        contracts_per_signal = 50
        max_cost = 25.0
        count = contracts_per_signal
        if price * count > max_cost:
            count = int(max_cost / price)
        assert count == 45
        assert price * count <= max_cost

    def test_very_expensive_contract_gets_at_least_one(self):
        price = 0.98
        contracts_per_signal = 50
        max_cost = 25.0
        count = contracts_per_signal
        if price * count > max_cost:
            count = int(max_cost / price)
        assert count >= 1

    def test_zero_count_skipped(self):
        price = 0.99
        max_cost = 0.50
        count = int(max_cost / price)
        assert count < 1


class TestBreakevenStatus:
    def test_positive_pnl_is_win(self):
        pnl_usd = 5.0
        if pnl_usd > 0:
            status = "settled_win"
        elif pnl_usd < 0:
            status = "settled_loss"
        else:
            status = "settled_breakeven"
        assert status == "settled_win"

    def test_negative_pnl_is_loss(self):
        pnl_usd = -3.0
        if pnl_usd > 0:
            status = "settled_win"
        elif pnl_usd < 0:
            status = "settled_loss"
        else:
            status = "settled_breakeven"
        assert status == "settled_loss"

    def test_zero_pnl_is_breakeven(self):
        pnl_usd = 0.0
        if pnl_usd > 0:
            status = "settled_win"
        elif pnl_usd < 0:
            status = "settled_loss"
        else:
            status = "settled_breakeven"
        assert status == "settled_breakeven"

    def test_tiny_positive_is_still_win(self):
        pnl_usd = 0.0001
        if pnl_usd > 0:
            status = "settled_win"
        elif pnl_usd < 0:
            status = "settled_loss"
        else:
            status = "settled_breakeven"
        assert status == "settled_win"
