"""Scanner subprocess entry point.

Launched by the uvicorn lifespan handler as a multiprocessing.Process.
Runs independent asyncio event loop with dedicated ThreadPoolExecutor
for all market discovery, scoring, signal generation, and exit checks.
"""

import asyncio
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

logger = logging.getLogger("scanner")

_DISCOVER_CRYPTO_INTERVAL = 30
_DISCOVER_CLIMATE_INTERVAL = 60
_SCORE_INTERVAL = 30
_SCORE_STAGGER = 5
_SIGNAL_INTERVAL = 10
_EXIT_INTERVAL = 15
_HEARTBEAT_INTERVAL = 30
_MODEL_CHECK_INTERVAL = 60
_PLATT_REFIT_INTERVAL = 24 * 3600
_PLATT_STARTUP_DELAY = 60
_SCHEDULER_TIMEOUT = 120


def run_scanner(db_url: str) -> None:
    """Entry point — called in the scanner subprocess."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Scanner subprocess starting (pid=%d)", os.getpid())

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    os.environ.setdefault("DATABASE_URL_SYNC", db_url)

    from app.core.config import settings

    url = db_url or settings.DATABASE_URL_SYNC
    engine = create_engine(url, pool_size=5, max_overflow=5)
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="scanner")

    async def run_in_executor(func, timeout: float = _SCHEDULER_TIMEOUT):
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(executor, func), timeout=timeout
        )

    from scanner.loops.discover import discover_crypto, discover_climate
    from scanner.loops.score import score_crypto, score_climate
    from scanner.loops.signal import run_signal_loop
    from scanner.loops.exit import run_exit_loop
    from scanner.heartbeat import write_heartbeat, init_heartbeat

    init_heartbeat(engine)

    def _discover_crypto_sync():
        with Session(engine) as s:
            discover_crypto(s)

    def _discover_climate_sync():
        with Session(engine) as s:
            discover_climate(s)

    def _score_crypto_sync():
        with Session(engine) as s:
            score_crypto(s)

    def _score_climate_sync():
        with Session(engine) as s:
            score_climate(s)

    def _signal_sync():
        with Session(engine) as s:
            run_signal_loop(s)

    def _exit_sync():
        with Session(engine) as s:
            run_exit_loop(s, engine)

    def _heartbeat_sync():
        with Session(engine) as s:
            write_heartbeat(s)

    def _model_check_sync():
        from scanner.models.crypto_xgb import check_and_reload as crypto_reload
        from scanner.models.climate_xgb import check_and_reload as climate_reload
        with Session(engine) as s:
            crypto_reload(s)
            climate_reload(s)

    def _platt_refit_sync():
        from app.services.climate_calibration import fit_and_save, reset_cache
        with Session(engine) as s:
            fit_and_save(s)
        reset_cache()

    async def discover_crypto_loop():
        while True:
            t0 = time.monotonic()
            try:
                await run_in_executor(_discover_crypto_sync, _DISCOVER_CRYPTO_INTERVAL + 10)
            except Exception:
                logger.exception("Discover crypto loop failed")
            elapsed = time.monotonic() - t0
            sleep = max(0, _DISCOVER_CRYPTO_INTERVAL - elapsed)
            if elapsed > _DISCOVER_CRYPTO_INTERVAL - 5:
                logger.warning(
                    "Discover crypto took %.1fs, reducing next interval to %.1fs",
                    elapsed, sleep,
                )
            await asyncio.sleep(sleep)

    async def discover_climate_loop():
        while True:
            t0 = time.monotonic()
            try:
                await run_in_executor(_discover_climate_sync, _DISCOVER_CLIMATE_INTERVAL + 10)
            except Exception:
                logger.exception("Discover climate loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _DISCOVER_CLIMATE_INTERVAL - elapsed))

    async def score_crypto_loop():
        await asyncio.sleep(_SCORE_STAGGER)
        while True:
            t0 = time.monotonic()
            try:
                await run_in_executor(_score_crypto_sync, _SCORE_INTERVAL + 10)
            except Exception:
                logger.exception("Score crypto loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _SCORE_INTERVAL - elapsed))

    async def score_climate_loop():
        await asyncio.sleep(_SCORE_STAGGER)
        while True:
            t0 = time.monotonic()
            try:
                await run_in_executor(_score_climate_sync, _SCORE_INTERVAL + 10)
            except Exception:
                logger.exception("Score climate loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _SCORE_INTERVAL - elapsed))

    async def signal_loop():
        while True:
            t0 = time.monotonic()
            try:
                await run_in_executor(_signal_sync, _SIGNAL_INTERVAL + 5)
            except Exception:
                logger.exception("Signal loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _SIGNAL_INTERVAL - elapsed))

    async def exit_loop():
        while True:
            t0 = time.monotonic()
            try:
                await run_in_executor(_exit_sync, _EXIT_INTERVAL + 5)
            except Exception:
                logger.exception("Exit loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _EXIT_INTERVAL - elapsed))

    async def heartbeat_loop():
        while True:
            try:
                await run_in_executor(_heartbeat_sync, 5)
            except Exception:
                logger.exception("Heartbeat write failed")
            await asyncio.sleep(_HEARTBEAT_INTERVAL)

    async def model_check_loop():
        while True:
            try:
                await run_in_executor(_model_check_sync, 10)
            except Exception:
                logger.exception("Model version check failed")
            await asyncio.sleep(_MODEL_CHECK_INTERVAL)

    async def platt_refit_loop():
        # Wait briefly so the scanner finishes initializing before we burn
        # CPU on the logistic fit, then refit daily. Lives in the scanner
        # process (not the api) so the calibrator file is written and read
        # in the same container — predict_climate_probability picks it up
        # on the next score cycle via the apply_platt cache.
        await asyncio.sleep(_PLATT_STARTUP_DELAY)
        while True:
            try:
                await run_in_executor(_platt_refit_sync, 60)
            except Exception:
                logger.exception("Platt refit failed")
            await asyncio.sleep(_PLATT_REFIT_INTERVAL)

    async def main():
        await asyncio.gather(
            heartbeat_loop(),
            discover_crypto_loop(),
            discover_climate_loop(),
            score_crypto_loop(),
            score_climate_loop(),
            signal_loop(),
            exit_loop(),
            model_check_loop(),
            platt_refit_loop(),
        )

    loop = asyncio.new_event_loop()
    loop.add_signal_handler(signal.SIGTERM, loop.stop)
    loop.add_signal_handler(signal.SIGINT, loop.stop)
    try:
        loop.run_until_complete(main())
    except RuntimeError:
        pass  # expected on SIGTERM — event loop stopped before gather completed
    executor.shutdown(wait=True)
    engine.dispose()
    logger.info("Scanner subprocess shutting down")


if __name__ == "__main__":
    db = os.environ.get("DATABASE_URL_SYNC", "postgresql://deepodds:deepodds@localhost:5433/deepodds")
    run_scanner(db)
