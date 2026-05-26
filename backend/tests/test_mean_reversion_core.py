"""Unit tests for shared mean-reversion math: VWAP, std dev, z-score."""

import math

import pytest

from app.services.mean_reversion import _compute_vwap_and_std, compute_z_score


def _make_candles(prices: list[float], volumes: list[float] | None = None) -> list[dict]:
    if volumes is None:
        volumes = [100.0] * len(prices)
    return [{"close": str(p), "volume": str(v)} for p, v in zip(prices, volumes)]


class TestComputeZScore:
    def test_price_at_vwap_gives_zero(self):
        assert compute_z_score(100.0, 100.0, 5.0) == 0.0

    def test_price_one_std_below(self):
        assert compute_z_score(95.0, 100.0, 5.0) == pytest.approx(-1.0)

    def test_price_two_std_above(self):
        assert compute_z_score(110.0, 100.0, 5.0) == pytest.approx(2.0)

    def test_zero_std_returns_zero(self):
        assert compute_z_score(105.0, 100.0, 0.0) == 0.0

    def test_negative_std_returns_zero(self):
        assert compute_z_score(105.0, 100.0, -1.0) == 0.0


class TestComputeVwapAndStd:
    def test_uniform_prices_zero_std(self):
        candles = _make_candles([50.0] * 10)
        vwap, std = _compute_vwap_and_std(candles, 10)
        assert vwap == pytest.approx(50.0)
        assert std == pytest.approx(0.0)

    def test_insufficient_candles_returns_zeros(self):
        candles = _make_candles([100.0, 101.0])
        vwap, std = _compute_vwap_and_std(candles, 10)
        assert vwap == 0.0
        assert std == 0.0

    def test_vwap_weights_by_volume(self):
        candles = _make_candles([100.0, 200.0], [900.0, 100.0])
        vwap, std = _compute_vwap_and_std(candles, 2)
        expected_vwap = (100 * 900 + 200 * 100) / 1000
        assert vwap == pytest.approx(expected_vwap)

    def test_std_dev_calculation(self):
        prices = [10.0, 12.0, 14.0, 16.0, 18.0]
        candles = _make_candles(prices)
        vwap, std = _compute_vwap_and_std(candles, 5)
        mean = sum(prices) / len(prices)
        expected_var = sum((p - mean) ** 2 for p in prices) / (len(prices) - 1)
        assert std == pytest.approx(math.sqrt(expected_var))

    def test_uses_last_n_candles_only(self):
        prices = [999.0, 100.0, 101.0, 102.0, 103.0]
        candles = _make_candles(prices)
        vwap_4, _ = _compute_vwap_and_std(candles, 4)
        assert vwap_4 == pytest.approx(101.5)

    def test_tolerates_some_zero_volume_candles(self):
        candles = _make_candles([50.0, 50.0, 50.0, 50.0], [100.0, 0.0, 100.0, 100.0])
        vwap, std = _compute_vwap_and_std(candles, 4)
        assert vwap == pytest.approx(50.0)

    def test_too_many_zero_volume_candles_returns_zero(self):
        candles = _make_candles([50.0, 50.0, 50.0, 50.0], [100.0, 0.0, 0.0, 0.0])
        vwap, std = _compute_vwap_and_std(candles, 4)
        assert vwap == 0.0

    def test_tolerates_some_zero_price_candles(self):
        candles = _make_candles([50.0, 0.0, 50.0, 50.0], [100.0, 100.0, 100.0, 100.0])
        vwap, std = _compute_vwap_and_std(candles, 4)
        assert vwap == pytest.approx(50.0)

    def test_too_many_zero_price_candles_returns_zero(self):
        candles = _make_candles([50.0, 0.0, 0.0, 0.0], [100.0, 100.0, 100.0, 100.0])
        vwap, std = _compute_vwap_and_std(candles, 4)
        assert vwap == 0.0

    def test_empty_candles(self):
        vwap, std = _compute_vwap_and_std([], 10)
        assert vwap == 0.0
        assert std == 0.0


class TestEndToEnd:
    """Integration of VWAP + z-score — the full mean-reversion signal check."""

    def test_oversold_triggers_entry(self):
        prices = [100.0] * 47 + [85.0]
        candles = _make_candles(prices)
        vwap, std = _compute_vwap_and_std(candles, 48)
        z = compute_z_score(85.0, vwap, std)
        assert z < -2.0

    def test_at_vwap_no_entry(self):
        prices = [100.0] * 48
        candles = _make_candles(prices)
        vwap, std = _compute_vwap_and_std(candles, 48)
        z = compute_z_score(100.0, vwap, std)
        assert z == 0.0
