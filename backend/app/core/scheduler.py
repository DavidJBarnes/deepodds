import asyncio
import logging
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.core.config import settings
from app.models.bot_config import BotConfig
from app.models.kalshi_config import KalshiConfig
from app.models.user import User
from app.services.robinhood_client import RobinhoodClient
from app.services.kalshi_client import KalshiClient
from app.services.mean_reversion import check_exits, scan_entries, sync_live_orders
from app.services.kalshi_fair_value import check_kalshi_exits, scan_kalshi_entries
from app.services.kalshi_live_sync import sync_kalshi_live

logger = logging.getLogger(__name__)

_sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_size=5, max_overflow=5)


def _run_scan_and_evaluate():
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(BotConfig).where(BotConfig.enabled.is_(True))
        ).scalars().all()

        for cfg in configs:
            user = session.execute(
                select(User).where(User.id == cfg.user_id)
            ).scalar_one_or_none()
            if not user:
                continue

            exchange = None
            if cfg.mode == "live" and user.robinhood_api_key and user.robinhood_private_key:
                exchange = RobinhoodClient(user.robinhood_api_key, user.robinhood_private_key)

            try:
                signals = scan_entries(cfg.user_id, session, exchange)
                if signals:
                    logger.info("Created %d crypto signals for %s", len(signals), user.email)
            except Exception:
                logger.exception("Crypto scan failed for user %s", cfg.user_id)


def _run_check_exits():
    with Session(_sync_engine) as session:
        users = session.execute(
            select(User).where(
                User.robinhood_api_key.isnot(None),
                User.robinhood_private_key.isnot(None),
            )
        ).scalars().all()

        exchange_clients = {}
        for user in users:
            try:
                exchange_clients[str(user.id)] = RobinhoodClient(
                    user.robinhood_api_key, user.robinhood_private_key
                )
            except Exception:
                pass

        exited = check_exits(session, exchange_clients if exchange_clients else None)
        if exited:
            logger.info("Exited %d crypto positions", exited)

    from datetime import datetime, timezone
    from pathlib import Path
    import json as _json

    try:
        Path("/tmp/scanner_health.json").write_text(
            _json.dumps({
                "last_scan": datetime.now(timezone.utc).isoformat(),
                "status": "ok",
            })
        )
    except Exception:
        pass


def _run_sync_live():
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(BotConfig).where(BotConfig.mode == "live")
        ).scalars().all()

        for cfg in configs:
            user = session.execute(
                select(User).where(User.id == cfg.user_id)
            ).scalar_one_or_none()
            if not user or not user.robinhood_api_key or not user.robinhood_private_key:
                continue

            exchange = RobinhoodClient(user.robinhood_api_key, user.robinhood_private_key)
            try:
                result = sync_live_orders(session, cfg.user_id, exchange)
                if result["filled"]:
                    logger.info("Live sync for %s: %d filled", user.email, result["filled"])
            except Exception:
                logger.exception("Live sync failed for %s", cfg.user_id)


def _run_kalshi_scan():
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(KalshiConfig).where(KalshiConfig.enabled.is_(True))
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


async def start_scheduler():
    logger.info("Starting mean-reversion scheduler")

    async def crypto_scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_scan_and_evaluate)
                await asyncio.to_thread(_run_check_exits)
            except Exception:
                logger.exception("Crypto scan/exit loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 60 - elapsed))

    async def crypto_sync_live_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_sync_live)
            except Exception:
                logger.exception("Crypto live sync loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 30 - elapsed))

    async def kalshi_scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_kalshi_scan)
                await asyncio.to_thread(_run_kalshi_check_exits)
            except Exception:
                logger.exception("Kalshi scan/exit loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 30 - elapsed))

    async def kalshi_sync_live_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_kalshi_sync_live)
            except Exception:
                logger.exception("Kalshi live sync loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 30 - elapsed))

    tasks = [
        asyncio.create_task(crypto_scan_loop(), name="crypto_scan"),
        asyncio.create_task(crypto_sync_live_loop(), name="crypto_sync_live"),
        asyncio.create_task(kalshi_scan_loop(), name="kalshi_scan"),
        asyncio.create_task(kalshi_sync_live_loop(), name="kalshi_sync_live"),
    ]

    logger.info(
        "Scheduler running: crypto(60s), crypto_live(30s), kalshi(30s), kalshi_live(30s)"
    )
    return tasks
