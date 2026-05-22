import base64
import json
import logging
import time
import uuid

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)

BASE_URL = "https://trading.robinhood.com"


class RobinhoodClient:
    def __init__(self, api_key: str, private_key_b64: str):
        self.api_key = api_key
        raw = private_key_b64.strip()
        self._private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))

    def _sign(self, timestamp: str, path: str, method: str, body: str = "") -> str:
        message = f"{self.api_key}{timestamp}{path}{method}{body}"
        signature = self._private_key.sign(message.encode())
        return base64.b64encode(signature).decode()

    def _headers(self, path: str, method: str, body: str = "") -> dict:
        ts = str(int(time.time()))
        return {
            "x-api-key": self.api_key,
            "x-timestamp": ts,
            "x-signature": self._sign(ts, path, method, body),
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, body: str = "", params: dict | None = None
    ) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = self._headers(path, method, body)
            url = f"{BASE_URL}{path}"
            resp = await client.request(
                method, url, headers=headers, content=body if body else None, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def validate(self) -> bool:
        try:
            await self._request("GET", "/api/v1/crypto/trading/accounts/")
            return True
        except Exception:
            return False

    async def get_account(self) -> dict:
        return await self._request("GET", "/api/v1/crypto/trading/accounts/")

    async def get_holdings(self) -> list[dict]:
        data = await self._request("GET", "/api/v1/crypto/trading/holdings/")
        return data.get("results", [])

    async def get_best_bid_ask(self, symbol: str) -> dict:
        data = await self._request(
            "GET", "/api/v1/crypto/marketdata/best_bid_ask/",
            params={"symbol": symbol},
        )
        results = data.get("results", [])
        return results[0] if results else data

    async def get_price(self, symbol: str) -> float:
        data = await self.get_best_bid_ask(symbol)
        bid = float(data.get("bid_inclusive_of_sell_spread", data.get("price", 0)))
        ask = float(data.get("ask_inclusive_of_buy_spread", bid))
        return (bid + ask) / 2 if bid > 0 and ask > 0 else bid

    async def get_estimated_price(self, symbol: str, side: str, quantity: str) -> dict:
        return await self._request(
            "GET", "/api/v1/crypto/marketdata/estimated_price/",
            params={"symbol": symbol, "side": side, "quantity": quantity},
        )

    async def place_market_buy(self, symbol: str, quote_amount: float) -> dict:
        price = await self.get_price(symbol)
        if price <= 0:
            raise ValueError(f"Cannot get price for {symbol}")
        asset_qty = quote_amount / price
        order = {
            "client_order_id": str(uuid.uuid4()),
            "side": "buy",
            "type": "market",
            "symbol": symbol,
            "market_order_config": {
                "asset_quantity": f"{asset_qty:.8f}",
            },
        }
        body = json.dumps(order)
        return await self._request("POST", "/api/v1/crypto/trading/orders/", body=body)

    async def place_market_sell(self, symbol: str, base_size: float) -> dict:
        order = {
            "client_order_id": str(uuid.uuid4()),
            "side": "sell",
            "type": "market",
            "symbol": symbol,
            "market_order_config": {
                "asset_quantity": f"{base_size:.8f}",
            },
        }
        body = json.dumps(order)
        return await self._request("POST", "/api/v1/crypto/trading/orders/", body=body)

    async def get_order(self, order_id: str) -> dict:
        return await self._request(
            "GET", f"/api/v1/crypto/trading/orders/{order_id}/"
        )

    async def cancel_order(self, order_id: str) -> dict:
        return await self._request(
            "POST", f"/api/v1/crypto/trading/orders/{order_id}/cancel/"
        )
