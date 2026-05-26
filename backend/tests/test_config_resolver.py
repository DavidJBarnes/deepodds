from types import SimpleNamespace

from app.services.config_resolver import resolve_crypto_config, resolve_kalshi_config


def _crypto_config(**overrides):
    defaults = {
        "entry_z_score": -3.0,
        "exit_z_score": -0.5,
        "position_size_usd": 25.0,
        "stop_loss_pct": 3.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _kalshi_config(**overrides):
    defaults = {
        "min_edge": 0.05,
        "exit_edge": -0.02,
        "contracts_per_signal": 50,
        "stop_loss_pct": 15.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _override(**fields):
    defaults = {
        "entry_z_score": None,
        "exit_z_score": None,
        "position_size_usd": None,
        "contracts_per_signal": None,
        "stop_loss_pct": None,
        "min_edge": None,
        "exit_edge": None,
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


class TestResolveCryptoConfig:
    def test_no_override_returns_global(self):
        cfg = _crypto_config()
        result = resolve_crypto_config(cfg, None)
        assert result["entry_z_score"] == -3.0
        assert result["exit_z_score"] == -0.5
        assert result["position_size_usd"] == 25.0
        assert result["stop_loss_pct"] == 3.0

    def test_full_override(self):
        cfg = _crypto_config()
        ovr = _override(entry_z_score=-2.0, exit_z_score=0.0, position_size_usd=100.0, stop_loss_pct=5.0)
        result = resolve_crypto_config(cfg, ovr)
        assert result["entry_z_score"] == -2.0
        assert result["exit_z_score"] == 0.0
        assert result["position_size_usd"] == 100.0
        assert result["stop_loss_pct"] == 5.0

    def test_partial_override_falls_back(self):
        cfg = _crypto_config()
        ovr = _override(entry_z_score=-1.5)
        result = resolve_crypto_config(cfg, ovr)
        assert result["entry_z_score"] == -1.5
        assert result["exit_z_score"] == -0.5
        assert result["position_size_usd"] == 25.0
        assert result["stop_loss_pct"] == 3.0

    def test_all_none_override_uses_global(self):
        cfg = _crypto_config()
        ovr = _override()
        result = resolve_crypto_config(cfg, ovr)
        assert result["entry_z_score"] == -3.0
        assert result["position_size_usd"] == 25.0


class TestResolveKalshiConfig:
    def test_no_override_returns_global(self):
        cfg = _kalshi_config()
        result = resolve_kalshi_config(cfg, None)
        assert result["min_edge"] == 0.05
        assert result["exit_edge"] == -0.02
        assert result["contracts_per_signal"] == 50
        assert result["stop_loss_pct"] == 15.0

    def test_full_override(self):
        cfg = _kalshi_config()
        ovr = _override(min_edge=0.10, exit_edge=-0.05, contracts_per_signal=100, stop_loss_pct=10.0)
        result = resolve_kalshi_config(cfg, ovr)
        assert result["min_edge"] == 0.10
        assert result["exit_edge"] == -0.05
        assert result["contracts_per_signal"] == 100
        assert result["stop_loss_pct"] == 10.0

    def test_partial_override(self):
        cfg = _kalshi_config()
        ovr = _override(contracts_per_signal=200)
        result = resolve_kalshi_config(cfg, ovr)
        assert result["min_edge"] == 0.05
        assert result["contracts_per_signal"] == 200
        assert result["stop_loss_pct"] == 15.0
