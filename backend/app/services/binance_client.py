import logging
import math

import httpx

logger = logging.getLogger(__name__)


async def get_metals_prices() -> dict[str, float]:
    """Fetch gold and silver spot prices from free APIs."""
    async with httpx.AsyncClient(timeout=10) as client:
        # Try metals.live first (free, no key)
        try:
            resp = await client.get("https://api.metals.live/v1/spot")
            resp.raise_for_status()
            data = resp.json()
            result = {}
            for item in data:
                if item.get("currency") == "USD":
                    metal = item.get("metal", "").upper()
                    if metal in ("GOLD", "SILVER"):
                        result[metal] = float(item["price"])
            if result:
                return result
        except Exception:
            pass

        # Fallback: try exchangerate API
        try:
            resp = await client.get(
                "https://api.exchangerate-api.com/v4/latest/USD"
            )
            resp.raise_for_status()
            rates = resp.json().get("rates", {})
            result = {}
            # XAU = gold (troy ounce), XAG = silver (troy ounce)
            # These are inverse: 1 USD = X/XAU, so price = 1 / rate
            if "XAU" in rates:
                result["GOLD"] = 1.0 / float(rates["XAU"])
            if "XAG" in rates:
                result["SILVER"] = 1.0 / float(rates["XAG"])
            return result
        except Exception:
            pass

        logger.warning("All metals price sources failed")
        return {}


_DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "XRP", "DOGE")

_COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
    "DOGE": "dogecoin", "LINK": "chainlink", "NEAR": "near", "ONDO": "ondo-finance",
    "SUI": "sui", "AVAX": "avalanche-2", "ADA": "cardano", "MATIC": "matic-network",
    "DOT": "polkadot", "LTC": "litecoin", "BCH": "bitcoin-cash",
}


async def get_crypto_prices(symbols: list[str] | tuple[str, ...] | None = None) -> dict[str, float]:
    """Fetch USD spot prices for the requested crypto symbols.

    Symbols are upper-case ticker prefixes (e.g. "BTC", "XRP"). Defaults to a
    common set for backwards compatibility; pass the symbols you actually need
    for efficiency.

    Returns whatever was found — missing symbols are silently omitted (the
    caller should check membership).
    """
    source = _DEFAULT_SYMBOLS if symbols is None else symbols
    requested = tuple(s.upper() for s in source)
    if not requested:
        return {}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            pairs = [f"{s}USDT" for s in requested]
            resp = await client.get(
                "https://api.binance.us/api/v3/ticker/price",
                params={"symbols": "[" + ",".join('"' + p + '"' for p in pairs) + "]"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {item["symbol"].replace("USDT", ""): float(item["price"]) for item in data}
        except Exception:
            pass

        try:
            ids = [_COINGECKO_IDS[s] for s in requested if s in _COINGECKO_IDS]
            if not ids:
                logger.warning("No CoinGecko mapping for any of %s", requested)
                return {}
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ",".join(ids), "vs_currencies": "usd"},
            )
            resp.raise_for_status()
            data = resp.json()
            reverse = {v: k for k, v in _COINGECKO_IDS.items()}
            return {reverse[gid]: float(d["usd"]) for gid, d in data.items() if gid in reverse}
        except Exception:
            logger.warning("All crypto price sources failed for %s", requested)
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
