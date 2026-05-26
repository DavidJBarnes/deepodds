"""Tests for get_crypto_prices accepting dynamic symbol lists."""

from unittest.mock import patch, AsyncMock

import pytest

from app.services import binance_client


class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


@pytest.mark.asyncio
class TestGetCryptoPrices:
    async def test_uses_requested_symbols(self):
        captured = {}

        async def fake_get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return _MockResponse([
                {"symbol": "XRPUSDT", "price": "1.33"},
                {"symbol": "SOLUSDT", "price": "83.5"},
            ])

        with patch("httpx.AsyncClient.get", new=fake_get):
            result = await binance_client.get_crypto_prices(["XRP", "SOL"])

        assert result == {"XRP": 1.33, "SOL": 83.5}
        assert '"XRPUSDT"' in captured["params"]["symbols"]
        assert '"SOLUSDT"' in captured["params"]["symbols"]
        # Should NOT request symbols we didn't ask for
        assert '"BTCUSDT"' not in captured["params"]["symbols"]
        assert '"ETHUSDT"' not in captured["params"]["symbols"]

    async def test_defaults_to_common_symbols(self):
        captured = {}

        async def fake_get(self, url, params=None):
            captured["params"] = params
            return _MockResponse([{"symbol": "BTCUSDT", "price": "76000"}])

        with patch("httpx.AsyncClient.get", new=fake_get):
            await binance_client.get_crypto_prices()

        assert '"BTCUSDT"' in captured["params"]["symbols"]
        assert '"ETHUSDT"' in captured["params"]["symbols"]

    async def test_empty_list_returns_empty(self):
        result = await binance_client.get_crypto_prices([])
        assert result == {}

    async def test_normalises_case(self):
        captured = {}

        async def fake_get(self, url, params=None):
            captured["params"] = params
            return _MockResponse([{"symbol": "BTCUSDT", "price": "76000"}])

        with patch("httpx.AsyncClient.get", new=fake_get):
            await binance_client.get_crypto_prices(["btc"])

        assert '"BTCUSDT"' in captured["params"]["symbols"]
