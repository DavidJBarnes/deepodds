"""Unit tests for backtest.scaling."""
import pytest

from backtest.scaling import (
    PER_SYMBOL_NOTIONAL_RATIO,
    TOTAL_NOTIONAL_RATIO,
    scaled_config,
)


def test_scaled_config_capital():
    cfg = scaled_config(8_000.0)
    assert cfg.paper_capital_usd == 8_000.0


def test_scaled_config_per_symbol_ratio():
    cfg = scaled_config(10_000.0)
    assert abs(cfg.max_notional_per_symbol - 10_000.0 * PER_SYMBOL_NOTIONAL_RATIO) < 0.01


def test_scaled_config_total_ratio():
    cfg = scaled_config(10_000.0)
    assert abs(cfg.max_total_notional_usd - 10_000.0 * TOTAL_NOTIONAL_RATIO) < 0.01


def test_scaled_config_8k():
    """Verify the headline $8k numbers."""
    cfg = scaled_config(8_000.0)
    assert cfg.max_notional_per_symbol == pytest.approx(8_000.0 * 0.30, rel=1e-6)
    assert cfg.max_total_notional_usd  == pytest.approx(8_000.0 * 0.55, rel=1e-6)


def test_scaled_config_5k():
    """Verify the headline $5k numbers."""
    cfg = scaled_config(5_000.0)
    assert cfg.max_notional_per_symbol == pytest.approx(5_000.0 * 0.30, rel=1e-6)
    assert cfg.max_total_notional_usd  == pytest.approx(5_000.0 * 0.55, rel=1e-6)


def test_scaled_config_inherits_defaults():
    """Parameters not explicitly set should inherit CarryConfig defaults."""
    cfg = scaled_config(8_000.0)
    assert cfg.target_leverage == 2.0
    assert cfg.min_funding_hurdle_ann == 0.06
    assert cfg.taker_fee_frac == 0.0004


def test_scaled_config_overrides():
    """Overrides via **kwargs replace the default values."""
    cfg = scaled_config(8_000.0, min_funding_hurdle_ann=0.10, target_leverage=3.0)
    assert cfg.min_funding_hurdle_ann == 0.10
    assert cfg.target_leverage == 3.0
    # Capital-derived fields still correct
    assert cfg.paper_capital_usd == 8_000.0


def test_committed_capital_fits_within_wallet():
    """
    At full two-symbol deployment, committed capital should be ≈ 91% of wallet.

    The effective total notional is capped by max_total_notional_usd (0.55 × capital),
    NOT by 2 × per-symbol (0.60 × capital). The tighter cap is the binding constraint,
    keeping committed ≈ 0.55 × 1.65 ≈ 91% of capital.
    """
    capital = 8_000.0
    cfg = scaled_config(capital)
    # Committed per $1 of notional: spot(1) + margin(1/lev) + reserve(reserve_frac)
    multiplier = 1 + 1 / cfg.target_leverage + cfg.reserve_frac
    # Binding cap is max_total_notional (0.55), not 2 × per_symbol (0.60)
    max_total_notional = cfg.max_total_notional_usd
    total_committed = max_total_notional * multiplier
    # Should be ≤ 95% of wallet (total notional cap keeps it safe)
    assert total_committed <= capital * 0.95, (
        f"Total committed {total_committed:.2f} exceeds 95% of ${capital:.2f} wallet"
    )
    # And close to 91% (sanity lower bound)
    assert total_committed >= capital * 0.85, (
        f"Total committed {total_committed:.2f} too low — ratios may be wrong"
    )
