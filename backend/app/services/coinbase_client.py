import hashlib
import hmac
import json
import logging
import time
import uuid

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coinbase.com/api/v3/brokerage"


class CoinbaseClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method.upper()}{path}{body}"
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
        }

    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{BASE_URL}{path}"
        body_str = json.dumps(body) if body else ""
        headers = self._sign_headers(method, f"/api/v3/brokerage{path}", body_str)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.request(method, url, headers=headers, content=body_str if body else None)
            resp.raise_for_status()
            return resp.json()

    async def create_market_order(self, side: str, product_id: str, amount_usd: float) -> dict:
        order = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": product_id,
            "side": side.upper(),
            "order_configuration": {
                "market_market_ioc": {
                    "quote_size": str(round(amount_usd, 2)),
                }
            },
        }
        return await self._request("POST", "/orders", order)

    async def get_accounts(self) -> list[dict]:
        data = await self._request("GET", "/accounts")
        return data.get("accounts", [])

    async def get_btc_balance(self) -> float:
        accounts = await self.get_accounts()
        for acc in accounts:
            if acc.get("currency") == "BTC":
                return float(acc.get("available_balance", {}).get("value", 0))
        return 0.0
