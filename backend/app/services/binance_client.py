import logging
import math

import httpx

logger = logging.getLogger(__name__)


async def get_crypto_prices() -> dict[str, float]:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://api.binance.us/api/v3/ticker/price",
                params={"symbols": "[" + ",".join('"' + s + '"' for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]) + "]"},
            )
            resp.raise_for_status()
            return {item["symbol"].replace("USDT", ""): float(item["price"]) for item in resp.json()}
        except Exception:
            pass

        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin,ethereum,solana,ripple,dogecoin", "vs_currencies": "usd"},
            )
            resp.raise_for_status()
            data = resp.json()
            result = {}
            if "bitcoin" in data:
                result["BTC"] = float(data["bitcoin"]["usd"])
            if "ethereum" in data:
                result["ETH"] = float(data["ethereum"]["usd"])
            if "solana" in data:
                result["SOL"] = float(data["solana"]["usd"])
            if "ripple" in data:
                result["XRP"] = float(data["ripple"]["usd"])
            if "dogecoin" in data:
                result["DOGE"] = float(data["dogecoin"]["usd"])
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


_INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


async def get_realized_vol(symbol: str = "BTC", hours: int = 4, interval: str = "1m") -> float | None:
    """Compute annualized realized volatility from Binance klines.

    Uses close-to-close log returns over the specified window.
    Returns annualized vol as a decimal (e.g. 0.65 = 65%).
    """
    pair = f"{symbol}USDT"
    bar_minutes = _INTERVAL_MINUTES.get(interval, 1)
    limit = min((hours * 60) // bar_minutes, 1000)
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://api.binance.us/api/v3/klines",
                params={"symbol": pair, "interval": interval, "limit": limit},
            )
            resp.raise_for_status()
            klines = resp.json()
        except Exception:
            try:
                resp = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": pair, "interval": interval, "limit": limit},
                )
                resp.raise_for_status()
                klines = resp.json()
            except Exception:
                logger.warning("Failed to fetch klines for realized vol (%s, %s)", symbol, interval)
                return None

    if len(klines) < 30:
        return None

    closes = [float(k[4]) for k in klines]
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]

    if len(log_returns) < 20:
        return None

    mean_r = sum(log_returns) / len(log_returns)
    variance = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
    vol_per_bar = math.sqrt(variance)
    bars_per_year = 365.25 * 24 * 60 / bar_minutes
    annualized = vol_per_bar * math.sqrt(bars_per_year)
    return annualized
