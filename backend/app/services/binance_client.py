import logging
import math

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


async def get_realized_vol(symbol: str = "BTC", hours: int = 4) -> float | None:
    """Compute annualized realized volatility from Binance 1-minute klines.

    Uses close-to-close log returns over the specified window.
    Returns annualized vol as a decimal (e.g. 0.65 = 65%).
    """
    pair = f"{symbol}USDT"
    limit = hours * 60
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://api.binance.us/api/v3/klines",
                params={"symbol": pair, "interval": "1m", "limit": limit},
            )
            resp.raise_for_status()
            klines = resp.json()
        except Exception:
            try:
                resp = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": pair, "interval": "1m", "limit": limit},
                )
                resp.raise_for_status()
                klines = resp.json()
            except Exception:
                logger.warning("Failed to fetch klines for realized vol (%s)", symbol)
                return None

    if len(klines) < 30:
        return None

    closes = [float(k[4]) for k in klines]
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]

    if len(log_returns) < 20:
        return None

    mean_r = sum(log_returns) / len(log_returns)
    variance = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
    vol_per_minute = math.sqrt(variance)
    annualized = vol_per_minute * math.sqrt(365.25 * 24 * 60)
    return annualized
