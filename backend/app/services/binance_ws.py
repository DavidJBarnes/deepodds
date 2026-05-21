import asyncio
import json
import logging
import time
from collections import deque

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
REDIS_KEY_HIGH_4H = "spot:btc:high_4h"
HIGH_1H_SECONDS = 3600
HIGH_4H_SECONDS = 14400

# Sample every Nth tick to bound memory. At ~300 ticks/sec, this gives
# ~1 sample/sec → ~14,400 entries for the 4h window.
SAMPLE_INTERVAL = 300
MAX_HISTORY_LEN = 20000


def _get_redis():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


async def run_binance_stream():
    r = _get_redis()
    price_history: deque[tuple[float, float]] = deque(maxlen=MAX_HISTORY_LEN)
    tick_count = 0
    current_high_1h = 0.0
    current_high_4h = 0.0

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

                        # Fast path: update highs without touching the deque
                        if price > current_high_1h:
                            current_high_1h = price
                            r.set(REDIS_KEY_HIGH_1H, str(price))
                        if price > current_high_4h:
                            current_high_4h = price
                            r.set(REDIS_KEY_HIGH_4H, str(price))

                        # Sample every Nth tick to bound memory/CPU
                        tick_count += 1
                        if tick_count % SAMPLE_INTERVAL != 0:
                            continue

                        price_history.append((now, price))

                        # Full recompute from history on sampled ticks
                        cutoff_1h = now - HIGH_1H_SECONDS
                        cutoff_4h = now - HIGH_4H_SECONDS
                        high_1h = price
                        high_4h = price
                        for t, p in price_history:
                            if t >= cutoff_1h and p > high_1h:
                                high_1h = p
                            if t >= cutoff_4h and p > high_4h:
                                high_4h = p
                        current_high_1h = high_1h
                        current_high_4h = high_4h
                        r.set(REDIS_KEY_HIGH_1H, str(high_1h))
                        r.set(REDIS_KEY_HIGH_4H, str(high_4h))
                except websockets.ConnectionClosed:
                    logger.warning("Binance WS disconnected, reconnecting...")
        except Exception:
            logger.exception("Binance WS error, retrying in 5s")
            await asyncio.sleep(5)
