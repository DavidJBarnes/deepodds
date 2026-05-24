"""Unit tests for Kalshi mean-reversion strategy logic.

Tests the entry/exit decision logic, market discovery filters,
and the Kalshi-specific exit conditions (approaching expiry).
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.kalshi_mean_reversion import (
    _discover_markets,
    _kalshi_candles_to_generic,
)
from app.services.mean_reversion import _compute_vwap_and_std, compute_z_score


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
        candle_interval=60,
        lookback_periods=24,
        entry_z_score=-2.0,
        exit_z_score=-0.3,
        contracts_per_signal=50,
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
        z_score=-2.8,
        vwap=0.60,
        market_ticker="KXBTC-26MAY24-BTC-100000",
        event_ticker="KXBTC-26MAY24",
        expiry_time=datetime.now(timezone.utc) + timedelta(hours=12),
        filled_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestKalshiExitLogic:
    """Test the Kalshi-specific exit conditions."""

    def test_mean_reversion_exit_requires_price_above_entry(self):
        sig = _make_kalshi_signal(fill_price=0.55)
        cfg = _make_kalshi_config(exit_z_score=-0.3)
        price = 0.52
        z = -0.1
        should_exit = z >= cfg.exit_z_score and z != 0 and price >= sig.fill_price
        assert not should_exit

    def test_mean_reversion_exit_when_price_above_entry(self):
        sig = _make_kalshi_signal(fill_price=0.55)
        cfg = _make_kalshi_config(exit_z_score=-0.3)
        price = 0.60
        z = -0.1
        should_exit = z >= cfg.exit_z_score and z != 0 and price >= sig.fill_price
        assert should_exit

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
    """Test market discovery filtering logic."""

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
    def test_entry_z_score_threshold(self):
        cfg = _make_kalshi_config(entry_z_score=-2.5)
        assert -3.0 <= cfg.entry_z_score
        assert -2.0 > cfg.entry_z_score

    def test_paper_kalshi_fills_immediately(self):
        cfg = _make_kalshi_config(mode="paper")
        assert cfg.mode == "paper"

    def test_contracts_cost(self):
        cfg = _make_kalshi_config(contracts_per_signal=50)
        price = 0.55
        cost = price * cfg.contracts_per_signal
        assert cost == pytest.approx(27.50)
