import json
import logging
import secrets
import time
import uuid

import httpx
import jwt

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coinbase.com"


class CoinbaseClient:
    def __init__(self, api_key: str, private_key: str):
        self.api_key = api_key
        # Coinbase provides PEM keys with escaped \n — normalize to real newlines
        self.private_key = private_key.replace("\\n", "\n") if private_key else private_key

    def _build_jwt(self, method: str, path: str) -> str:
        uri = f"{method.upper()} api.coinbase.com{path}"
        now = int(time.time())
        payload = {
            "sub": self.api_key,
            "iss": "cdp",
            "aud": ["cdp_service"],
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        }
        headers = {
            "kid": self.api_key,
            "nonce": secrets.token_hex(16),
            "typ": "JWT",
        }
        return jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)

    def _headers(self, method: str, path: str) -> dict:
        token = self._build_jwt(method, path)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, body: str = "", params: dict | None = None
    ) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = self._headers(method, path)
            url = f"{BASE_URL}{path}"
            resp = await client.request(
                method, url, headers=headers, content=body if body else None, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def validate(self) -> bool:
        try:
            await self._request("GET", "/api/v3/brokerage/accounts")
            return True
        except Exception:
            return False

    async def get_accounts(self) -> list[dict]:
        data = await self._request("GET", "/api/v3/brokerage/accounts")
        return data.get("accounts", [])

    async def get_usd_balance(self) -> float:
        accounts = await self.get_accounts()
        for acct in accounts:
            if acct.get("currency") == "USD":
                return float(acct.get("available_balance", {}).get("value", 0))
        return 0.0

    async def get_ticker(self, product_id: str) -> dict:
        data = await self._request(
            "GET", f"/api/v3/brokerage/market/products/{product_id}"
        )
        return data

    async def get_price(self, product_id: str) -> float:
        data = await self.get_ticker(product_id)
        return float(data.get("price", 0))

    async def get_candles(
        self,
        product_id: str,
        granularity: str = "FIFTEEN_MINUTE",
        limit: int = 64,
    ) -> list[dict]:
        now = int(time.time())
        granularity_seconds = {
            "ONE_MINUTE": 60,
            "FIVE_MINUTE": 300,
            "FIFTEEN_MINUTE": 900,
            "ONE_HOUR": 3600,
        }
        bar_secs = granularity_seconds.get(granularity, 900)
        start = now - (limit * bar_secs)
        params = {
            "start": str(start),
            "end": str(now),
            "granularity": granularity,
        }
        data = await self._request(
            "GET",
            f"/api/v3/brokerage/market/products/{product_id}/candles",
            params=params,
        )
        return data.get("candles", [])

    async def place_market_buy(self, product_id: str, quote_size: float) -> dict:
        order = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": product_id,
            "side": "BUY",
            "order_configuration": {
                "market_market_ioc": {"quote_size": f"{quote_size:.2f}"}
            },
        }
        body = json.dumps(order)
        return await self._request("POST", "/api/v3/brokerage/orders", body=body)

    async def place_market_sell(self, product_id: str, base_size: float) -> dict:
        order = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": product_id,
            "side": "SELL",
            "order_configuration": {
                "market_market_ioc": {"base_size": f"{base_size:.8f}"}
            },
        }
        body = json.dumps(order)
        return await self._request("POST", "/api/v3/brokerage/orders", body=body)

    async def place_limit_order(
        self, product_id: str, side: str, base_size: float, limit_price: float
    ) -> dict:
        order = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": product_id,
            "side": side.upper(),
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": f"{base_size:.8f}",
                    "limit_price": f"{limit_price:.2f}",
                }
            },
        }
        body = json.dumps(order)
        return await self._request("POST", "/api/v3/brokerage/orders", body=body)

    async def get_order(self, order_id: str) -> dict:
        data = await self._request(
            "GET", f"/api/v3/brokerage/orders/historical/{order_id}"
        )
        return data.get("order", data)

    async def cancel_orders(self, order_ids: list[str]) -> dict:
        body = json.dumps({"order_ids": order_ids})
        data = await self._request(
            "POST", "/api/v3/brokerage/orders/batch_cancel", body=body
        )
        return data
