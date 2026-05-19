import logging

import httpx

logger = logging.getLogger(__name__)


async def get_crypto_prices() -> dict[str, float]:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://api.binance.us/api/v3/ticker/price",
                params={"symbols": "[" + ",".join('"' + s + '"' for s in ["BTCUSDT", "ETHUSDT"]) + "]"},
            )
            resp.raise_for_status()
            return {item["symbol"].replace("USDT", ""): float(item["price"]) for item in resp.json()}
        except Exception:
            pass

        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin,ethereum", "vs_currencies": "usd"},
            )
            resp.raise_for_status()
            data = resp.json()
            result = {}
            if "bitcoin" in data:
                result["BTC"] = float(data["bitcoin"]["usd"])
            if "ethereum" in data:
                result["ETH"] = float(data["ethereum"]["usd"])
            return result
        except Exception:
            logger.warning("All crypto price sources failed")
            raise


async def get_fear_greed() -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("https://api.alternative.me/fng/?limit=1")
        resp.raise_for_status()
        data = resp.json().get("data", [{}])[0]
        return {
            "value": int(data.get("value", 50)),
            "label": data.get("value_classification", "Neutral"),
        }
