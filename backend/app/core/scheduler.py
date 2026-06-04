import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.core.config import settings
from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.model_train_history import ModelTrainHistory
from app.models.user import User
from app.services.binance_client import get_crypto_prices, get_market_stats, get_realized_vol
from app.services.climate_fair_value import (
    check_climate_exits,
    scan_climate_entries,
    settle_expired_climate_paper,
)
from app.services.kalshi_client import KalshiClient
from app.services.kalshi_fair_value import (
    cancel_stale_placed_orders,
    check_kalshi_exits,
    scan_kalshi_entries,
    settle_expired_paper,
)
from app.services.kalshi_live_sync import sync_kalshi_live
from app.services.market_data import set as cache_set
from app.services.probability_model import series_to_underlying

_BALANCE_CACHE_TTL = 60  # seconds; scheduler refreshes every 30s
_SCAN_INTERVAL = 30  # seconds between entry scan cycles
_EXIT_INTERVAL = 15  # seconds between exit check cycles

logger = logging.getLogger(__name__)

_sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_size=5, max_overflow=5)


def _write_scanner_health(status: str, error: str | None = None) -> None:
    """Write scanner health status for the dashboard to read."""
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path

    health = {
        "last_scan": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    if error:
        health["error"] = error
    try:
        Path("/tmp/scanner_health.json").write_text(_json.dumps(health))
    except Exception:
        logger.warning("Failed to write scanner health file")


def _write_balance_cache(user_id: str, data: dict) -> None:
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path

    try:
        cache = {
            "cash_cents": int(data.get("balance", 0)),
            "portfolio_cents": int(data.get("portfolio_value", 0)),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        Path(f"/tmp/kalshi_balance_{user_id}.json").write_text(_json.dumps(cache))
    except Exception:
        logger.warning("Failed to write balance cache for user %s", user_id)


def _run_kalshi_scan():
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(CryptoConfig).where(CryptoConfig.enabled.is_(True))
        ).scalars().all()

        for cfg in configs:
            user = session.execute(
                select(User).where(User.id == cfg.user_id)
            ).scalar_one_or_none()
            if not user:
                continue

            client = None
            if cfg.mode == "live" and user.kalshi_api_key_id and user.kalshi_private_key:
                try:
                    client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
                except Exception:
                    pass

            try:
                signals = scan_kalshi_entries(cfg.user_id, session, client)
                if signals:
                    logger.info("Created %d Kalshi signals for %s", len(signals), user.email)
            except Exception:
                logger.exception("Kalshi scan failed for user %s", cfg.user_id)

            # Re-fetch portfolio/cash balance after each scan cycle
            if client:
                try:
                    bal = run_async(client.get_balance())
                    _write_balance_cache(str(cfg.user_id), bal)
                except Exception:
                    logger.exception("Failed to cache Kalshi balance for user %s", cfg.user_id)
            elif cfg.mode == "paper":
                # Paper mode has no real Kalshi balance. Write a simulated
                # bankroll so Kelly sizing works identically to live mode.
                # Default $1000 paper bankroll — change contracts_per_signal
                # if you want a different fixed size regardless of Kelly.
                _write_balance_cache(str(cfg.user_id), {"balance": 0, "portfolio_value": 100000})


def _run_kalshi_check_exits():
    with Session(_sync_engine) as session:
        users = session.execute(
            select(User).where(
                User.kalshi_api_key_id.isnot(None),
                User.kalshi_private_key.isnot(None),
            )
        ).scalars().all()

        exchange_clients = {}
        for user in users:
            try:
                exchange_clients[str(user.id)] = KalshiClient(
                    user.kalshi_api_key_id, user.kalshi_private_key
                )
            except Exception:
                pass

        exited = check_kalshi_exits(session, exchange_clients if exchange_clients else None)
        if exited:
            logger.info("Exited %d Kalshi positions", exited)


def _run_kalshi_sync_live():
    """Reconcile placed/filled Kalshi signals with Kalshi-side state."""
    with Session(_sync_engine) as session:
        users = session.execute(
            select(User).where(
                User.kalshi_api_key_id.isnot(None),
                User.kalshi_private_key.isnot(None),
            )
        ).scalars().all()

        exchange_clients = {}
        for user in users:
            try:
                exchange_clients[str(user.id)] = KalshiClient(
                    user.kalshi_api_key_id, user.kalshi_private_key
                )
            except Exception:
                pass

        if not exchange_clients:
            return

        counts = sync_kalshi_live(session, exchange_clients)
        if any(counts.values()):
            logger.info(
                "Kalshi live sync: %d filled, %d settled, %d cancelled",
                counts["filled"], counts["settled"], counts["cancelled"],
            )


def _run_kalshi_housekeeping():
    """Run periodic housekeeping tasks: paper settlement, order timeouts."""
    with Session(_sync_engine) as session:
        settled = settle_expired_paper(session)
        if settled:
            logger.info("Settled %d expired paper signals", settled)

        cancelled = cancel_stale_placed_orders(session)
        if cancelled:
            logger.info("Cancelled %d stale placed orders", cancelled)


def _write_scanner_health_climate(status: str, error: str | None = None) -> None:
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path

    health = {
        "last_scan": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    if error:
        health["error"] = error
    try:
        Path("/tmp/scanner_health_climate.json").write_text(_json.dumps(health))
    except Exception:
        logger.warning("Failed to write climate scanner health file")


def _write_heartbeats() -> None:
    """Refresh the timestamp in both scanner health files.

    Called by a 30 s asyncio task so the dashboard never shows a stale
    timestamp regardless of how long a scan cycle takes.  The scan loops
    only update the ``status`` / ``error`` fields when they complete or
    fail — they no longer touch the timestamp.
    """
    _write_scanner_health("online")
    _write_scanner_health_climate("online")


# ---------------------------------------------------------------------------
#  Data-refresh helpers — run in a thread-pool worker via asyncio.to_thread
# ---------------------------------------------------------------------------

def _refresh_crypto_cache() -> None:
    """Prefetch all shared crypto market data and populate the global cache."""
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(CryptoConfig).where(CryptoConfig.enabled.is_(True))
        ).scalars().all()

    series_set: set[str] = set()
    for cfg in configs:
        for s in (cfg.series_tickers or "").split(","):
            s = s.strip()
            if s:
                series_set.add(s)

    symbols = {series_to_underlying(t) for t in series_set}
    symbols.discard(None)
    if not symbols:
        return

    async def _fetch_stats(s: str):
        return s, await get_market_stats(s, hours=48, interval="1h")

    async def _fetch_vol_baseline(s: str):
        return s, await get_realized_vol(s, hours=168, interval="1h")

    prices = run_async(get_crypto_prices(list(symbols)))
    cache_set("crypto_prices", prices)

    async def _gather_stats():
        return await asyncio.gather(*[_fetch_stats(s) for s in symbols])

    stats_results = run_async(_gather_stats())
    for sym, stats in stats_results:
        if stats:
            cache_set(f"market_stats_{sym}", stats)

    async def _gather_vols():
        return await asyncio.gather(*[_fetch_vol_baseline(s) for s in symbols])

    vol_results = run_async(_gather_vols())
    for sym, vol in vol_results:
        if vol is not None:
            cache_set(f"realized_vol_{sym}_168_1h", vol)

    client = KalshiClient.public()

    async def _fetch_markets(s: str):
        try:
            data = await client.get_markets(series_ticker=s, limit=200)
            return s, data
        except Exception:
            logger.warning("Refresh failed to fetch markets for series %s", s)
            return s, None

    async def _gather_markets():
        return await asyncio.gather(*[_fetch_markets(s) for s in series_set])

    market_results = run_async(_gather_markets())
    for s, data in market_results:
        if data is not None:
            cache_set(f"kalshi_raw_{s}", data)


def _refresh_climate_cache() -> None:
    """Prefetch shared climate market listings into the global cache."""
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(ClimateConfig).where(ClimateConfig.enabled.is_(True))
        ).scalars().all()

    series_set: set[str] = set()
    for cfg in configs:
        for s in (cfg.series_tickers or "").split(","):
            s = s.strip()
            if s:
                series_set.add(s)

    if not series_set:
        return

    client = KalshiClient.public()

    async def _fetch_markets(s: str):
        try:
            data = await client.get_markets(series_ticker=s, limit=200)
            return s, data
        except Exception:
            logger.warning("Climate refresh failed to fetch markets for series %s", s)
            return s, None

    async def _gather_markets():
        return await asyncio.gather(*[_fetch_markets(s) for s in series_set])

    results = run_async(_gather_markets())
    for s, data in results:
        if data is not None:
            cache_set(f"kalshi_raw_{s}", data)


def _run_climate_scan():
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(ClimateConfig).where(ClimateConfig.enabled.is_(True))
        ).scalars().all()

        for cfg in configs:
            user = session.execute(
                select(User).where(User.id == cfg.user_id)
            ).scalar_one_or_none()
            if not user:
                continue

            client = None
            if cfg.mode == "live" and user.kalshi_api_key_id and user.kalshi_private_key:
                try:
                    client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
                except Exception:
                    pass

            try:
                signals = scan_climate_entries(cfg.user_id, session, client)
                if signals:
                    logger.info("Created %d climate signals for %s", len(signals), user.email)
            except Exception:
                logger.exception("Climate scan failed for user %s", cfg.user_id)


def _run_climate_check_exits():
    with Session(_sync_engine) as session:
        users = session.execute(
            select(User).where(
                User.kalshi_api_key_id.isnot(None),
                User.kalshi_private_key.isnot(None),
            )
        ).scalars().all()

        exchange_clients = {}
        for user in users:
            try:
                exchange_clients[str(user.id)] = KalshiClient(
                    user.kalshi_api_key_id, user.kalshi_private_key
                )
            except Exception:
                pass

        exited = check_climate_exits(session, exchange_clients if exchange_clients else None)
        if exited:
            logger.info("Exited %d climate positions", exited)


def _run_climate_housekeeping():
    with Session(_sync_engine) as session:
        settled = settle_expired_climate_paper(session)
        if settled:
            logger.info("Settled %d expired climate paper signals", settled)


_SCHEDULER_TIMEOUT = 120  # max seconds any single scan/refresh may occupy a thread


async def _run_in_scheduler(executor: ThreadPoolExecutor, func, timeout: float = _SCHEDULER_TIMEOUT):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(executor, func),
        timeout=timeout,
    )


async def start_scheduler(standalone: bool = False):
    """
    Start the background scheduler.

    When ``standalone=True`` (scanner runs as a separate service via
    docker-compose), skip the loops that the scanner already handles
    (kalshi_scan, climate_scan, heartbeat).  Keep the loops the
    scanner does *not* handle: live order sync, retraining, cache
    refresh, exit housekeeping, and balance-cache writing.
    """
    logger.info("Starting Kalshi scheduler (standalone=%s)", standalone)

    scheduler_executor = ThreadPoolExecutor(
        max_workers=4 if standalone else 8,
        thread_name_prefix="scheduler",
    )

    async def kalshi_scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await _run_in_scheduler(scheduler_executor, _run_kalshi_scan)
            except Exception as exc:
                _write_scanner_health("error", str(exc)[:200])
                logger.exception("Kalshi scan loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _SCAN_INTERVAL - elapsed))

    async def kalshi_exit_loop():
        while True:
            t0 = time.monotonic()
            try:
                await _run_in_scheduler(scheduler_executor, _run_kalshi_check_exits)
                await _run_in_scheduler(scheduler_executor, _run_kalshi_housekeeping)
            except Exception:
                logger.exception("Kalshi exit/housekeeping loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _EXIT_INTERVAL - elapsed))

    async def kalshi_sync_live_loop():
        while True:
            t0 = time.monotonic()
            try:
                await _run_in_scheduler(scheduler_executor, _run_kalshi_sync_live)
            except Exception:
                logger.exception("Kalshi live sync loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 30 - elapsed))

    async def kalshi_retrain_loop():
        # Wait 1 hour on startup to allow immediate scanning
        await asyncio.sleep(3600)
        while True:
            try:
                logger.info("Triggering weekly SOTA ML auto-retraining...")
                from sqlalchemy import update
                from app.models.history import History
                from app.services.train_model import train_and_save_model
                from app.services.probability_model import MODEL_FILE, reload_booster
                started_at = datetime.now(timezone.utc)
                success, snapshot = await train_and_save_model()
                crypto_kb = os.path.getsize(MODEL_FILE) / 1024 if os.path.exists(MODEL_FILE) else 0
                msg = "Automated weekly SOTA ML model retraining completed successfully" if success else "Automated weekly SOTA ML model retraining failed"
                if success:
                    reload_booster()
                with Session(_sync_engine) as session:
                    users = session.execute(
                        select(User)
                    ).scalars().all()
                    for user in users:
                        session.add(History(
                            user_id=user.id,
                            text=msg,
                        ))
                    if success and snapshot:
                        session.execute(
                            update(ModelTrainHistory)
                            .where(ModelTrainHistory.crypto_active.is_(True))
                            .values(crypto_active=False)
                        )
                    session.add(ModelTrainHistory(
                        user_id=None,
                        model_type="crypto",
                        crypto_ok=success,
                        climate_ok=None,
                        crypto_size_kb=crypto_kb,
                        climate_size_kb=None,
                        total_size_kb=crypto_kb,
                        crypto_model_path=snapshot,
                        climate_model_path=None,
                        crypto_active=bool(success and snapshot),
                        climate_active=False,
                        message=msg,
                        trigger="scheduled",
                        started_at=started_at,
                    ))
                    session.commit()
                logger.info("SOTA ML auto-retraining completed successfully and booster reloaded.")
            except Exception:
                logger.exception("SOTA ML auto-retraining loop encountered an error")
            await asyncio.sleep(7 * 24 * 3600)

    async def climate_scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await _run_in_scheduler(scheduler_executor, _run_climate_scan)
            except Exception as exc:
                _write_scanner_health_climate("error", str(exc)[:200])
                logger.exception("Climate scan loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _SCAN_INTERVAL - elapsed))

    async def climate_exit_loop():
        while True:
            t0 = time.monotonic()
            try:
                await _run_in_scheduler(scheduler_executor, _run_climate_check_exits)
                await _run_in_scheduler(scheduler_executor, _run_climate_housekeeping)
            except Exception:
                logger.exception("Climate exit/housekeeping loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _EXIT_INTERVAL - elapsed))

    async def climate_retrain_loop():
        await asyncio.sleep(3600)
        while True:
            try:
                logger.info("Triggering weekly climate ML auto-retraining...")
                from sqlalchemy import update
                from app.models.history import History
                from app.services.train_climate_model import train_and_save_climate_model
                from app.services.climate_probability_model import (
                    MODEL_FILE as CLIMATE_MODEL_FILE,
                    reload_booster as reload_climate_booster,
                )
                started_at = datetime.now(timezone.utc)
                success, snapshot = await train_and_save_climate_model()
                climate_kb = os.path.getsize(CLIMATE_MODEL_FILE) / 1024 if os.path.exists(CLIMATE_MODEL_FILE) else 0
                msg = "Automated weekly climate ML model retraining completed successfully" if success else "Automated weekly climate ML model retraining failed"
                if success:
                    reload_climate_booster()
                with Session(_sync_engine) as session:
                    users = session.execute(select(User)).scalars().all()
                    for user in users:
                        session.add(History(
                            user_id=user.id,
                            text=msg,
                        ))
                    if success and snapshot:
                        session.execute(
                            update(ModelTrainHistory)
                            .where(ModelTrainHistory.climate_active.is_(True))
                            .values(climate_active=False)
                        )
                    session.add(ModelTrainHistory(
                        user_id=None,
                        model_type="climate",
                        crypto_ok=None,
                        climate_ok=success,
                        crypto_size_kb=None,
                        climate_size_kb=climate_kb,
                        total_size_kb=climate_kb,
                        crypto_model_path=None,
                        climate_model_path=snapshot,
                        crypto_active=False,
                        climate_active=bool(success and snapshot),
                        message=msg,
                        trigger="scheduled",
                        started_at=started_at,
                    ))
                    session.commit()
                logger.info("Climate ML auto-retraining completed successfully.")
            except Exception:
                logger.exception("Climate ML auto-retraining loop encountered an error")
            await asyncio.sleep(7 * 24 * 3600)

    async def heartbeat_loop():
        while True:
            try:
                _write_heartbeats()
            except Exception:
                logger.exception("Heartbeat write failed")
            await asyncio.sleep(30)

    async def refresh_crypto_data_loop():
        while True:
            try:
                await _run_in_scheduler(scheduler_executor, _refresh_crypto_cache)
            except Exception:
                logger.exception("Crypto data refresh failed")
            await asyncio.sleep(30)

    async def refresh_climate_data_loop():
        while True:
            try:
                await _run_in_scheduler(scheduler_executor, _refresh_climate_cache)
            except Exception:
                logger.exception("Climate data refresh failed")
            await asyncio.sleep(30)

    async def balance_cache_loop():
        """Refresh per-user Kalshi balance caches so the scanner can do
        quarter-Kelly sizing even when kalshi_scan_loop is disabled."""
        while True:
            try:
                with Session(_sync_engine) as session:
                    crypto_configs = session.execute(
                        select(CryptoConfig).where(CryptoConfig.enabled.is_(True))
                    ).scalars().all()
                    climate_configs = session.execute(
                        select(ClimateConfig).where(ClimateConfig.enabled.is_(True))
                    ).scalars().all()

                    seen: set[str] = set()
                    user_configs: list[tuple[str, str, str]] = []
                    for cfg in crypto_configs:
                        uid = str(cfg.user_id)
                        if uid not in seen:
                            seen.add(uid)
                            user_configs.append((uid, cfg.mode, cfg.user_id))
                    for cfg in climate_configs:
                        uid = str(cfg.user_id)
                        if uid not in seen:
                            seen.add(uid)
                            user_configs.append((uid, cfg.mode, cfg.user_id))

                    for uid, mode, user_id_uuid in user_configs:
                        user = session.execute(
                            select(User).where(User.id == user_id_uuid)
                        ).scalar_one_or_none()
                        if not user:
                            continue
                        if mode == "paper":
                            _write_balance_cache(uid, {"balance": 0, "portfolio_value": 100000})
                            continue
                        if not (user.kalshi_api_key_id and user.kalshi_private_key):
                            continue
                        try:
                            client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
                            bal = run_async(client.get_balance())
                            _write_balance_cache(uid, bal)
                        except Exception:
                            pass
            except Exception:
                logger.exception("Balance cache refresh failed")
            await asyncio.sleep(60)

    tasks = [
        asyncio.create_task(kalshi_exit_loop(), name="kalshi_exit"),
        asyncio.create_task(kalshi_sync_live_loop(), name="kalshi_sync_live"),
        asyncio.create_task(kalshi_retrain_loop(), name="kalshi_retrain"),
        asyncio.create_task(climate_exit_loop(), name="climate_exit"),
        asyncio.create_task(climate_retrain_loop(), name="climate_retrain"),
        asyncio.create_task(refresh_crypto_data_loop(), name="refresh_crypto"),
        asyncio.create_task(refresh_climate_data_loop(), name="refresh_climate"),
        asyncio.create_task(balance_cache_loop(), name="balance_cache"),
    ]

    if not standalone:
        tasks += [
            asyncio.create_task(kalshi_scan_loop(), name="kalshi_scan"),
            asyncio.create_task(climate_scan_loop(), name="climate_scan"),
            asyncio.create_task(heartbeat_loop(), name="heartbeat"),
        ]

    if standalone:
        logger.info(
            "Scheduler running (standalone): kalshi_exit(%ds), kalshi_sync_live(30s), "
            "retrain(7d), refresh_crypto(30s), refresh_climate(30s), "
            "balance_cache(60s)",
            _EXIT_INTERVAL,
        )
    else:
        logger.info(
            "Scheduler running: kalshi_scan(%ds), kalshi_exit(%ds), kalshi_live(30s), "
            "climate_scan(%ds), climate_exit(%ds), retrain(7d), "
            "heartbeat(30s), refresh_crypto(30s), refresh_climate(30s)",
            _SCAN_INTERVAL, _EXIT_INTERVAL, _SCAN_INTERVAL, _EXIT_INTERVAL,
        )
    return tasks, scheduler_executor
