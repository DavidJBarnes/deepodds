import base64
import logging
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import settings

logger = logging.getLogger(__name__)


class KalshiClient:
    def __init__(self, api_key_id: str, api_private_key_pem: str):
        self.api_key_id = api_key_id
        self.private_key = serialization.load_pem_private_key(api_private_key_pem.encode(), password=None)
        self.base_url = settings.KALSHI_BASE_URL

    def _sign_headers(self, method: str, path: str) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        sign_path = path.split("?")[0]
        message = f"{timestamp_ms}{method}{sign_path}"
        signature = self.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        full_path = f"/trade-api/v2{path}"
        headers = self._sign_headers(method.upper(), full_path)
        logger.info("Kalshi %s %s", method.upper(), url)
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(3):
                resp = await client.request(method, url, headers=headers, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt < 2:
                        await _sleep_async(2 ** attempt)
                        headers = self._sign_headers(method.upper(), full_path)
                        continue
                if resp.status_code >= 400:
                    logger.error("Kalshi %d response: %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
                return resp.json()
        return {}

    async def get_event(self, event_ticker: str) -> dict:
        return await self._request("GET", f"/events/{event_ticker}")

    async def get_markets_for_event(self, event_ticker: str) -> list[dict]:
        result = await self._request("GET", f"/markets?event_ticker={event_ticker}&limit=100")
        return result.get("markets", [])

    async def get_market(self, ticker: str) -> dict:
        return await self._request("GET", f"/markets/{ticker}")

    async def get_orderbook(self, ticker: str, depth: int = 20) -> dict:
        return await self._request("GET", f"/markets/{ticker}/orderbook?depth={depth}")

    async def get_trades(self, ticker: str, limit: int = 100) -> dict:
        return await self._request("GET", f"/markets/trades?ticker={ticker}&limit={limit}")

    async def get_candlesticks(self, series_ticker: str, ticker: str) -> dict:
        return await self._request(
            "GET", f"/series/{series_ticker}/markets/{ticker}/candlesticks?period_interval=60"
        )

    async def get_order(self, order_id: str) -> dict:
        result = await self._request("GET", f"/portfolio/orders/{order_id}")
        return result.get("order", {})

    async def get_balance(self) -> dict:
        return await self._request("GET", "/portfolio/balance")

    async def place_order(self, ticker: str, side: str, action: str, price: int, quantity: int) -> dict:
        return await self._request(
            "POST",
            "/portfolio/orders",
            json={
                "ticker": ticker,
                "side": side,
                "action": action,
                "type": "limit",
                "count": quantity,
                "yes_price": price if side == "yes" else None,
                "no_price": price if side == "no" else None,
            },
        )


async def _sleep_async(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)
