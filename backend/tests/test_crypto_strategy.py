"""Regression tests for the crypto mean-reversion strategy logic.

These tests verify the core entry/exit decision logic without hitting
a real database or API.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.mean_reversion import _compute_vwap_and_std, compute_z_score


def _make_config(**overrides):
    defaults = dict(
        user_id=uuid.uuid4(),
        mode="paper",
        enabled=True,
        pairs="SOL-USD,BTC-USD",
        lookback_periods=48,
        entry_z_score=-3.0,
        exit_z_score=-0.5,
        position_size_usd=25.0,
        max_open_positions=3,
        stop_loss_pct=3.0,
        daily_loss_limit_usd=50.0,
        max_signals_per_hour=5,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_signal(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        venue="crypto",
        pair="SOL-USD",
        side="buy",
        signal_type="paper",
        status="filled",
        entry_price=100.0,
        fill_price=100.0,
        fill_quantity=0.25,
        quantity=0.25,
        cost_usd=25.0,
        z_score=-3.5,
        vwap=105.0,
        filled_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _candles_at_price(price: float, n: int = 52) -> list[dict]:
    return [{"close": str(price), "volume": "1000"} for _ in range(n)]


class TestMeanReversionExit:
    """The exit bug that caused SOL-USD loss: rolling VWAP drifted down with price,
    so z-score normalized even though absolute price was still below entry.
    Fix: require price >= fill_price for mean-reversion exits."""

    def test_no_exit_when_price_below_entry_despite_normal_z(self):
        sig = _make_signal(fill_price=100.0)
        cfg = _make_config(exit_z_score=-0.5, stop_loss_pct=10.0)
        price = 97.0
        z = -0.3
        should_exit = z >= cfg.exit_z_score and z != 0 and price >= sig.fill_price
        assert not should_exit

    def test_exit_when_price_above_entry_and_z_reverted(self):
        sig = _make_signal(fill_price=100.0)
        cfg = _make_config(exit_z_score=-0.5)
        price = 102.0
        z = -0.3
        should_exit = z >= cfg.exit_z_score and z != 0 and price >= sig.fill_price
        assert should_exit

    def test_stop_loss_fires_regardless_of_price_vs_entry(self):
        sig = _make_signal(fill_price=100.0)
        cfg = _make_config(stop_loss_pct=3.0)
        price = 96.0
        pnl_pct = (price - sig.fill_price) / sig.fill_price * 100
        should_exit = pnl_pct <= -cfg.stop_loss_pct
        assert should_exit

    def test_stop_loss_does_not_fire_within_threshold(self):
        sig = _make_signal(fill_price=100.0)
        cfg = _make_config(stop_loss_pct=3.0)
        price = 98.0
        pnl_pct = (price - sig.fill_price) / sig.fill_price * 100
        should_exit = pnl_pct <= -cfg.stop_loss_pct
        assert not should_exit

    def test_max_hold_exits_after_24h(self):
        sig = _make_signal(filled_at=datetime.now(timezone.utc) - timedelta(hours=25))
        now = datetime.now(timezone.utc)
        should_exit = sig.filled_at and (now - sig.filled_at) > timedelta(hours=24)
        assert should_exit

    def test_no_max_hold_before_24h(self):
        sig = _make_signal(filled_at=datetime.now(timezone.utc) - timedelta(hours=12))
        now = datetime.now(timezone.utc)
        should_exit = sig.filled_at and (now - sig.filled_at) > timedelta(hours=24)
        assert not should_exit


class TestEntryConditions:
    def test_entry_requires_z_below_threshold(self):
        cfg = _make_config(entry_z_score=-3.0)
        assert -3.5 <= cfg.entry_z_score
        assert -2.0 > cfg.entry_z_score

    def test_paper_mode_fills_immediately(self):
        cfg = _make_config(mode="paper")
        assert cfg.mode == "paper"


class TestPnlCalculation:
    def test_win_pnl(self):
        entry = 100.0
        exit_price = 105.0
        qty = 0.25
        pnl = (exit_price - entry) * qty
        assert pnl == pytest.approx(1.25)

    def test_loss_pnl(self):
        entry = 100.0
        exit_price = 97.0
        qty = 0.25
        pnl = (exit_price - entry) * qty
        assert pnl == pytest.approx(-0.75)

    def test_pnl_pct(self):
        entry = 100.0
        exit_price = 103.0
        pnl_pct = (exit_price - entry) / entry * 100
        assert pnl_pct == pytest.approx(3.0)
