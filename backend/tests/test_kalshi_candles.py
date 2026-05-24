"""Unit tests for Kalshi candle conversion and market discovery."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.kalshi_mean_reversion import _kalshi_candles_to_generic


class TestKalshiCandlesToGeneric:
    def test_valid_candle(self):
        candles = [{"price": {"close_dollars": 0.55}, "volume_fp": 120}]
        result = _kalshi_candles_to_generic(candles)
        assert len(result) == 1
        assert result[0]["close"] == "0.55"
        assert result[0]["volume"] == "120.0"

    def test_skips_zero_price(self):
        candles = [{"price": {"close_dollars": 0}, "volume_fp": 120}]
        result = _kalshi_candles_to_generic(candles)
        assert len(result) == 0

    def test_skips_zero_volume(self):
        candles = [{"price": {"close_dollars": 0.55}, "volume_fp": 0}]
        result = _kalshi_candles_to_generic(candles)
        assert len(result) == 0

    def test_skips_missing_fields(self):
        candles = [{"price": {}, "volume_fp": 100}]
        result = _kalshi_candles_to_generic(candles)
        assert len(result) == 0

    def test_multiple_candles(self):
        candles = [
            {"price": {"close_dollars": 0.50}, "volume_fp": 100},
            {"price": {"close_dollars": 0.0}, "volume_fp": 200},
            {"price": {"close_dollars": 0.60}, "volume_fp": 150},
        ]
        result = _kalshi_candles_to_generic(candles)
        assert len(result) == 2
        assert result[0]["close"] == "0.5"
        assert result[1]["close"] == "0.6"

    def test_empty_list(self):
        assert _kalshi_candles_to_generic([]) == []

    def test_string_numbers_converted(self):
        candles = [{"price": {"close_dollars": "0.75"}, "volume_fp": "500"}]
        result = _kalshi_candles_to_generic(candles)
        assert len(result) == 1
        assert float(result[0]["close"]) == 0.75


class TestKalshiCandiesToVwap:
    """Verify Kalshi candles flow through the shared VWAP pipeline."""

    def test_kalshi_candles_produce_valid_vwap(self):
        from app.services.mean_reversion import _compute_vwap_and_std, compute_z_score

        raw = [
            {"price": {"close_dollars": 0.50 + i * 0.01}, "volume_fp": 100 + i * 10}
            for i in range(60)
        ]
        generic = _kalshi_candles_to_generic(raw)
        assert len(generic) == 60

        vwap, std = _compute_vwap_and_std(generic, 60)
        assert vwap > 0
        assert std > 0

        z = compute_z_score(0.40, vwap, std)
        assert z < 0
