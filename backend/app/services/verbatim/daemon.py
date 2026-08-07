"""Verbatim background tasks: market discovery and retention pruning.

Run as `python -m app.services.verbatim.daemon`.

SHIPS DISABLED. Both loops are behind flags that default to false, and the
Kalshi-touching one is the reason: the API key is SHARED with `longshot-live`,
which places real orders. Enable one at a time, days apart, watching the harness's
`fill_rate` and `avg_slippage_c` against the recorded baseline. If they move,
disable the flag first and investigate after.

Why a separate process rather than the API's lifespan: every other background job
here is its own container (longshot, oracle, bookrec, explorer), and `app/main.py`
says so explicitly. A Kalshi sweep or a long DELETE has no business sharing a
process with the endpoint that serves the trading UI.

NOT INCLUDED: orderbook logging and the edge_seconds scoreboard. Those need a
persistent Kalshi WebSocket client, which DeepOdds does not have (its client is
synchronous REST), and they only produce anything once detections exist. Building
a WS client is its own piece of work, not a rider on this one.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import signal

from app.core.config import settings
from app.core.database import verbatim_sessionmaker
from app.services.verbatim import retention, watchlist

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("app.verbatim.daemon")


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return default if not v else v not in ("0", "false", "no", "off")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


async def _periodic(name: str, interval_s: float, fn, stop: asyncio.Event,
                    initial_delay_s: float = 0.0) -> None:
    """Run `fn` every `interval_s`, surviving its failures.

    One broken loop must never take the daemon down — the other loop, and the next
    run of this one, are still useful.
    """
    if initial_delay_s:
        logger.info("%s: first run in %.0fs", name, initial_delay_s)
        try:
            await asyncio.wait_for(stop.wait(), timeout=initial_delay_s)
            return
        except TimeoutError:
            pass
    while not stop.is_set():
        try:
            await fn()
        except Exception:
            logger.exception("%s failed; continuing", name)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
            return
        except TimeoutError:
            pass


async def _discovery_once(query: str) -> None:
    from longshot.config import load_kalshi_creds
    from longshot.kalshi_client import KalshiClient

    key_id, pem = load_kalshi_creds()
    client = KalshiClient(key_id, pem)
    try:
        async with verbatim_sessionmaker()() as session:
            n = await watchlist.refresh_once(session, client, query)
            disarmed = await watchlist.disarm_passed_deadlines(session)
        logger.info("verbatim discovery: %d markets, %d disarmed", n, disarmed)
    finally:
        close = getattr(client, "close", None)
        if close:
            close()


async def _retention_once(transcript_hours: int, delta_days: int) -> None:
    async with verbatim_sessionmaker()() as session:
        await retention.prune_transcripts(session, transcript_hours)
        await retention.prune_orderbook_deltas(session, delta_days)


async def _amain(once: bool) -> None:
    if not settings.verbatim_enabled:
        logger.error("VERBATIM_DATABASE_URL is not set; nothing to do")
        return

    discovery_on = _env_bool("VERBATIM_WATCHLIST_ENABLED", False)
    retention_on = _env_bool("VERBATIM_RETENTION_ENABLED", True)
    query = os.environ.get("VERBATIM_DISCOVERY_QUERY", "say").strip() or "say"
    discovery_interval = _env_int("VERBATIM_DISCOVERY_INTERVAL_S", 1800)
    retention_interval = _env_int("VERBATIM_RETENTION_INTERVAL_S", 21600)
    transcript_hours = _env_int("VERBATIM_TRANSCRIPT_RETENTION_HOURS", 48)
    delta_days = _env_int("VERBATIM_DELTA_RETENTION_DAYS", 14)

    if once:
        if discovery_on:
            await _discovery_once(query)
        if retention_on:
            await _retention_once(transcript_hours, delta_days)
        return

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    tasks = []
    if discovery_on:
        # Jittered start so a sweep never lands on the hour alongside
        # longshot-live's order tick. A fixed offset would just move the
        # collision; a random one spreads it across runs.
        jitter = random.uniform(0, min(600, discovery_interval / 2))
        tasks.append(
            _periodic("discovery", discovery_interval,
                      lambda: _discovery_once(query), stop, initial_delay_s=jitter)
        )
    else:
        logger.info("discovery DISABLED (VERBATIM_WATCHLIST_ENABLED); Kalshi untouched")

    if retention_on:
        tasks.append(
            _periodic("retention", retention_interval,
                      lambda: _retention_once(transcript_hours, delta_days), stop)
        )
    else:
        logger.info("retention DISABLED (VERBATIM_RETENTION_ENABLED)")

    if not tasks:
        logger.warning("nothing enabled; idling until stopped")
        await stop.wait()
        return

    logger.info("verbatim tasks started: %d loop(s)", len(tasks))
    await asyncio.gather(*tasks)
    logger.info("verbatim tasks stopped")


def main() -> None:
    ap = argparse.ArgumentParser(description="Verbatim background tasks")
    ap.add_argument("--once", action="store_true",
                    help="run each enabled task once and exit (for manual sweeps)")
    args = ap.parse_args()
    asyncio.run(_amain(args.once))


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
