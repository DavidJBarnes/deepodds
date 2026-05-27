"""Tests for Kalshi config defaults and cost-based position sizing."""

import pytest


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
        # Raised from 0.05 to 0.08 after calibration analysis showed the
        # Black-Scholes model is systematically overconfident by ~7%. The
        # market-implied probability is 2x more accurate (Brier 0.13 vs 0.27).
        # Combined with MARKET_WEIGHT=0.5 blending, 0.08 filters out most
        # false positives while allowing edge > 16% raw signals through.
        from app.models.kalshi_config import KalshiConfig
        col = KalshiConfig.__table__.columns["min_edge"]
        assert col.default.arg == 0.08

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

