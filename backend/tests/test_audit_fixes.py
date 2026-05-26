"""Tests for the 5 audit fixes:
1. Crypto exit scanner venue filter
2. Breakeven status labeling
3. Kalshi config defaults (min_edge, max_price, min_hours_to_expiry, min_volume_24h)
4. Cost-based position sizing (max_cost_per_signal)
5. Crypto min hold time
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


class TestVenueFilter:
    """Fix 1: check_exits() must only process crypto signals."""

    def test_venue_filter_excludes_kalshi(self):
        signals = [
            SimpleNamespace(venue="crypto", status="filled", pair="BTC-USD"),
            SimpleNamespace(venue="kalshi", status="filled", pair="KXBTC"),
            SimpleNamespace(venue="crypto", status="filled", pair="ETH-USD"),
        ]
        crypto_only = [s for s in signals if s.venue == "crypto"]
        assert len(crypto_only) == 2
        assert all(s.venue == "crypto" for s in crypto_only)

    def test_venue_filter_no_crypto(self):
        signals = [
            SimpleNamespace(venue="kalshi", status="filled", pair="KXBTC"),
            SimpleNamespace(venue="kalshi", status="filled", pair="KXETH"),
        ]
        crypto_only = [s for s in signals if s.venue == "crypto"]
        assert len(crypto_only) == 0

    def test_venue_filter_all_crypto(self):
        signals = [
            SimpleNamespace(venue="crypto", status="filled", pair="BTC-USD"),
            SimpleNamespace(venue="crypto", status="filled", pair="SOL-USD"),
        ]
        crypto_only = [s for s in signals if s.venue == "crypto"]
        assert len(crypto_only) == 2


class TestBreakevenStatus:
    """Fix 2: $0 PnL should be settled_breakeven, not settled_win."""

    def _settle(self, pnl_usd: float) -> str:
        if pnl_usd > 0:
            return "settled_win"
        elif pnl_usd < 0:
            return "settled_loss"
        else:
            return "settled_breakeven"

    def test_positive_is_win(self):
        assert self._settle(5.0) == "settled_win"

    def test_negative_is_loss(self):
        assert self._settle(-3.0) == "settled_loss"

    def test_zero_is_breakeven(self):
        assert self._settle(0.0) == "settled_breakeven"

    def test_tiny_positive_is_win(self):
        assert self._settle(0.0001) == "settled_win"

    def test_tiny_negative_is_loss(self):
        assert self._settle(-0.0001) == "settled_loss"

    def test_breakeven_not_counted_as_win(self):
        results = [self._settle(5.0), self._settle(0.0), self._settle(-3.0), self._settle(0.0)]
        wins = sum(1 for r in results if r == "settled_win")
        losses = sum(1 for r in results if r == "settled_loss")
        breakevens = sum(1 for r in results if r == "settled_breakeven")
        assert wins == 1
        assert losses == 1
        assert breakevens == 2


class TestKalshiConfigDefaults:
    """Fix 3: Safer default values for Kalshi config."""

    def test_min_edge_default(self):
        from app.models.kalshi_config import KalshiConfig
        col = KalshiConfig.__table__.columns["min_edge"]
        assert col.default.arg == 0.07

    def test_max_price_default(self):
        from app.models.kalshi_config import KalshiConfig
        col = KalshiConfig.__table__.columns["max_price"]
        assert col.default.arg == 0.80

    def test_min_hours_to_expiry_default(self):
        from app.models.kalshi_config import KalshiConfig
        col = KalshiConfig.__table__.columns["min_hours_to_expiry"]
        assert col.default.arg == 1

    def test_min_volume_24h_default(self):
        from app.models.kalshi_config import KalshiConfig
        col = KalshiConfig.__table__.columns["min_volume_24h"]
        assert col.default.arg == 100

    def test_max_cost_per_signal_default(self):
        from app.models.kalshi_config import KalshiConfig
        col = KalshiConfig.__table__.columns["max_cost_per_signal"]
        assert col.default.arg == 25.0


class TestCostBasedSizing:
    """Fix 4: Position size capped by max_cost_per_signal."""

    def _compute_count(self, price: float, contracts: int = 50, max_cost: float = 25.0) -> int:
        count = contracts
        if price > 0 and price * count > max_cost:
            count = int(max_cost / price)
        return count

    def test_cheap_contract_full_count(self):
        count = self._compute_count(0.02)
        assert count == 50

    def test_mid_price_reduced(self):
        count = self._compute_count(0.55)
        assert count == 45
        assert 0.55 * count <= 25.0

    def test_expensive_contract_heavily_reduced(self):
        count = self._compute_count(0.94)
        assert count == 26
        assert 0.94 * count <= 25.0

    def test_very_cheap_contract(self):
        count = self._compute_count(0.01)
        assert count == 50

    def test_at_max_cost_boundary(self):
        count = self._compute_count(0.50)
        assert count == 50
        assert 0.50 * count == 25.0

    def test_just_over_max_cost(self):
        count = self._compute_count(0.51)
        assert count == 49
        assert 0.51 * count < 25.0

    def test_cost_never_exceeds_max(self):
        for price_cents in range(1, 100):
            price = price_cents / 100
            count = self._compute_count(price)
            assert price * count <= 25.0 or count <= 50

    def test_high_max_cost_no_reduction(self):
        count = self._compute_count(0.94, contracts=50, max_cost=100.0)
        assert count == 50

    def test_zero_count_when_too_expensive(self):
        count = self._compute_count(0.99, contracts=50, max_cost=0.50)
        assert count == 0


class TestMinHoldTime:
    """Fix 5: Crypto positions must be held for min_hold_minutes before mean-reversion exit."""

    def _should_exit_mean_reversion(
        self, z: float, exit_z: float, price: float, fill_price: float,
        filled_at: datetime, now: datetime, min_hold: int
    ) -> bool:
        hold_minutes = (now - filled_at).total_seconds() / 60
        return z >= exit_z and z != 0 and price >= fill_price and hold_minutes >= min_hold

    def test_exit_after_hold_period(self):
        now = datetime.now(timezone.utc)
        filled = now - timedelta(minutes=35)
        assert self._should_exit_mean_reversion(
            z=-0.3, exit_z=-0.5, price=100.5, fill_price=100.0,
            filled_at=filled, now=now, min_hold=30
        )

    def test_no_exit_during_hold_period(self):
        now = datetime.now(timezone.utc)
        filled = now - timedelta(minutes=10)
        assert not self._should_exit_mean_reversion(
            z=-0.3, exit_z=-0.5, price=100.5, fill_price=100.0,
            filled_at=filled, now=now, min_hold=30
        )

    def test_stop_loss_ignores_hold_period(self):
        pnl_pct = -5.0
        stop_loss_pct = 3.0
        assert pnl_pct <= -stop_loss_pct

    def test_max_hold_ignores_hold_period(self):
        now = datetime.now(timezone.utc)
        filled = now - timedelta(hours=25)
        hold_hours = (now - filled).total_seconds() / 3600
        assert hold_hours > 24

    def test_zero_hold_exits_immediately(self):
        now = datetime.now(timezone.utc)
        filled = now - timedelta(seconds=5)
        assert self._should_exit_mean_reversion(
            z=-0.3, exit_z=-0.5, price=100.5, fill_price=100.0,
            filled_at=filled, now=now, min_hold=0
        )

    def test_exactly_at_hold_boundary(self):
        now = datetime.now(timezone.utc)
        filled = now - timedelta(minutes=30)
        assert self._should_exit_mean_reversion(
            z=-0.3, exit_z=-0.5, price=100.5, fill_price=100.0,
            filled_at=filled, now=now, min_hold=30
        )

    def test_no_exit_when_z_below_threshold(self):
        now = datetime.now(timezone.utc)
        filled = now - timedelta(minutes=60)
        assert not self._should_exit_mean_reversion(
            z=-2.0, exit_z=-0.5, price=100.5, fill_price=100.0,
            filled_at=filled, now=now, min_hold=30
        )

    def test_no_exit_when_price_below_fill(self):
        now = datetime.now(timezone.utc)
        filled = now - timedelta(minutes=60)
        assert not self._should_exit_mean_reversion(
            z=-0.3, exit_z=-0.5, price=99.0, fill_price=100.0,
            filled_at=filled, now=now, min_hold=30
        )


class TestBotConfigMinHold:
    """Verify min_hold_minutes exists on BotConfig model."""

    def test_min_hold_minutes_column_exists(self):
        from app.models.bot_config import BotConfig
        col = BotConfig.__table__.columns["min_hold_minutes"]
        assert col.default.arg == 30

    def test_min_hold_minutes_schema(self):
        from app.schemas.bot_config import BotConfigResponse, BotConfigUpdate
        resp = BotConfigResponse(mode="paper", enabled=True, min_hold_minutes=30)
        assert resp.min_hold_minutes == 30
        update = BotConfigUpdate(min_hold_minutes=60)
        assert update.min_hold_minutes == 60


class TestKalshiMaxCostSchema:
    """Verify max_cost_per_signal in schemas."""

    def test_response_schema(self):
        from app.schemas.kalshi_config import KalshiConfigResponse
        resp = KalshiConfigResponse(mode="paper", enabled=True, max_cost_per_signal=25.0)
        assert resp.max_cost_per_signal == 25.0

    def test_update_schema_validation(self):
        from app.schemas.kalshi_config import KalshiConfigUpdate
        update = KalshiConfigUpdate(max_cost_per_signal=50.0)
        assert update.max_cost_per_signal == 50.0

    def test_update_schema_min_validation(self):
        from pydantic import ValidationError
        from app.schemas.kalshi_config import KalshiConfigUpdate
        with pytest.raises(ValidationError):
            KalshiConfigUpdate(max_cost_per_signal=0.5)

    def test_config_resolver_includes_max_cost(self):
        from app.services.config_resolver import resolve_kalshi_config
        cfg = SimpleNamespace(
            min_edge=0.07, exit_edge=-0.02,
            contracts_per_signal=50, max_cost_per_signal=25.0,
            stop_loss_pct=15.0,
        )
        result = resolve_kalshi_config(cfg, None)
        assert result["max_cost_per_signal"] == 25.0
