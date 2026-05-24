import base64
import json
import logging
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
PUBLIC_ENDPOINTS = ("/markets", "/series/", "/events/")


class KalshiClient:
    def __init__(self, api_key: str, private_key_pem: str):
        self.api_key = api_key
        self._private_key = serialization.load_pem_private_key(
            private_key_pem.strip().encode(), password=None
        )

    def _sign(self, timestamp_ms: str, method: str, path: str) -> str:
        message = f"{timestamp_ms}{method}{path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode()

    def _headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": self._sign(ts, method, path),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        body: str = "",
        params: dict | None = None,
        auth: bool = True,
    ) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            url = f"{BASE_URL}{path}"
            headers = self._headers(method, path) if auth else {
                "Accept": "application/json",
            }
            resp = await client.request(
                method, url, headers=headers,
                content=body if body else None,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def validate(self) -> bool:
        try:
            await self._request("GET", "/portfolio/balance")
            return True
        except Exception:
            return False

    async def get_balance(self) -> dict:
        return await self._request("GET", "/portfolio/balance")

    async def get_markets(
        self,
        series_ticker: str | None = None,
        status: str = "open",
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict:
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/markets", params=params, auth=False)

    async def get_market(self, ticker: str) -> dict:
        data = await self._request("GET", f"/markets/{ticker}", auth=False)
        return data.get("market", data)

    async def get_candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
    ) -> list[dict]:
        path = f"/series/{series_ticker}/markets/{market_ticker}/candlesticks"
        params = {
            "start_ts": str(start_ts),
            "end_ts": str(end_ts),
            "period_interval": str(period_interval),
        }
        data = await self._request("GET", path, params=params, auth=False)
        return data.get("candlesticks", [])

    async def create_order(
        self,
        ticker: str,
        side: str,
        count: int,
        yes_price_cents: int,
        action: str = "buy",
        order_type: str = "limit",
    ) -> dict:
        order = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": order_type,
            "yes_price": yes_price_cents,
        }
        body = json.dumps(order)
        return await self._request("POST", "/portfolio/orders", body=body)

    async def get_order(self, order_id: str) -> dict:
        data = await self._request("GET", f"/portfolio/orders/{order_id}")
        return data.get("order", data)

    async def cancel_order(self, order_id: str) -> dict:
        return await self._request("DELETE", f"/portfolio/orders/{order_id}")

    async def get_positions(self) -> list[dict]:
        data = await self._request("GET", "/portfolio/positions")
        return data.get("market_positions", [])
