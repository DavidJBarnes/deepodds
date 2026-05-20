import asyncio
import json
import logging
import time

import redis
import websockets

from app.core.config import settings

logger = logging.getLogger(__name__)

BINANCE_WS_URLS = [
    "wss://fstream.binance.com/ws/btcusdt@trade",
    "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "wss://stream.binance.us:9443/ws/btcusdt@trade",
]
REDIS_KEY_PRICE = "spot:btc:price"
REDIS_KEY_UPDATED = "spot:btc:updated"
REDIS_KEY_HIGH_1H = "spot:btc:high_1h"
HIGH_WINDOW_SECONDS = 3600


def _get_redis():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


async def run_binance_stream():
    r = _get_redis()
    price_history: list[tuple[float, float]] = []

    for url in BINANCE_WS_URLS:
        try:
            async with asyncio.timeout(10):
                async with websockets.connect(url) as ws:
                    await ws.recv()
            ws_url = url
            logger.info("Selected Binance WS endpoint: %s", url)
            break
        except Exception:
            logger.debug("Binance WS endpoint %s unavailable", url)
            continue
    else:
        ws_url = BINANCE_WS_URLS[0]
        logger.warning("No Binance WS endpoint responded, defaulting to %s", ws_url)

    while True:
        try:
            async for ws in websockets.connect(ws_url):
                logger.info("Binance WS connected to %s", ws_url)
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        price = float(msg["p"])
                        now = time.time()

                        r.set(REDIS_KEY_PRICE, str(price))
                        r.set(REDIS_KEY_UPDATED, str(now))

                        price_history.append((now, price))
                        cutoff = now - HIGH_WINDOW_SECONDS
                        price_history[:] = [(t, p) for t, p in price_history if t >= cutoff]
                        high_1h = max(p for _, p in price_history)
                        r.set(REDIS_KEY_HIGH_1H, str(high_1h))
                except websockets.ConnectionClosed:
                    logger.warning("Binance WS disconnected, reconnecting...")
        except Exception:
            logger.exception("Binance WS error, retrying in 5s")
            await asyncio.sleep(5)
