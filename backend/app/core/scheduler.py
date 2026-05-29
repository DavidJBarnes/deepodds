import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.core.config import settings
from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.model_train_history import ModelTrainHistory
from app.models.user import User
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


async def start_scheduler():
    logger.info("Starting Kalshi scheduler")

    async def kalshi_scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_kalshi_scan)
                _write_scanner_health("online")
            except Exception as exc:
                _write_scanner_health("error", str(exc)[:200])
                logger.exception("Kalshi scan loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _SCAN_INTERVAL - elapsed))

    async def kalshi_exit_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_kalshi_check_exits)
                await asyncio.to_thread(_run_kalshi_housekeeping)
            except Exception:
                logger.exception("Kalshi exit/housekeeping loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _EXIT_INTERVAL - elapsed))

    async def kalshi_sync_live_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_kalshi_sync_live)
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
                from app.models.history import History
                from app.services.train_model import train_and_save_model
                from app.services.probability_model import MODEL_FILE, reload_booster
                started_at = datetime.now(timezone.utc)
                success = await train_and_save_model()
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
                    session.add(ModelTrainHistory(
                        user_id=None,
                        model_type="crypto",
                        crypto_ok=success,
                        climate_ok=None,
                        crypto_size_kb=crypto_kb,
                        climate_size_kb=None,
                        total_size_kb=crypto_kb,
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
                await asyncio.to_thread(_run_climate_scan)
                _write_scanner_health_climate("online")
            except Exception as exc:
                _write_scanner_health_climate("error", str(exc)[:200])
                logger.exception("Climate scan loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _SCAN_INTERVAL - elapsed))

    async def climate_exit_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_climate_check_exits)
                await asyncio.to_thread(_run_climate_housekeeping)
            except Exception:
                logger.exception("Climate exit/housekeeping loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, _EXIT_INTERVAL - elapsed))

    async def climate_retrain_loop():
        await asyncio.sleep(3600)
        while True:
            try:
                logger.info("Triggering weekly climate ML auto-retraining...")
                from app.models.history import History
                from app.services.train_climate_model import train_and_save_climate_model
                from app.services.climate_probability_model import (
                    MODEL_FILE as CLIMATE_MODEL_FILE,
                    reload_booster as reload_climate_booster,
                )
                started_at = datetime.now(timezone.utc)
                success = await train_and_save_climate_model()
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
                    session.add(ModelTrainHistory(
                        user_id=None,
                        model_type="climate",
                        crypto_ok=None,
                        climate_ok=success,
                        crypto_size_kb=None,
                        climate_size_kb=climate_kb,
                        total_size_kb=climate_kb,
                        message=msg,
                        trigger="scheduled",
                        started_at=started_at,
                    ))
                    session.commit()
                logger.info("Climate ML auto-retraining completed successfully.")
            except Exception:
                logger.exception("Climate ML auto-retraining loop encountered an error")
            await asyncio.sleep(7 * 24 * 3600)

    tasks = [
        asyncio.create_task(kalshi_scan_loop(), name="kalshi_scan"),
        asyncio.create_task(kalshi_exit_loop(), name="kalshi_exit"),
        asyncio.create_task(kalshi_sync_live_loop(), name="kalshi_sync_live"),
        asyncio.create_task(kalshi_retrain_loop(), name="kalshi_retrain"),
        asyncio.create_task(climate_scan_loop(), name="climate_scan"),
        asyncio.create_task(climate_exit_loop(), name="climate_exit"),
        asyncio.create_task(climate_retrain_loop(), name="climate_retrain"),
    ]

    logger.info(
        "Scheduler running: kalshi_scan(%ds), kalshi_exit(%ds), kalshi_live(30s), "
        "climate_scan(%ds), climate_exit(%ds), retrain(7d)",
        _SCAN_INTERVAL, _EXIT_INTERVAL, _SCAN_INTERVAL, _EXIT_INTERVAL,
    )
    return tasks
