import asyncio
import logging
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.core.config import settings
from app.models.bot_config import BotConfig
from app.models.user import User
from app.services.coinbase_client import CoinbaseClient
from app.services.mean_reversion import check_exits, scan_entries, sync_live_orders

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

            coinbase = None
            if cfg.mode == "live" and user.coinbase_api_key and user.coinbase_private_key:
                coinbase = CoinbaseClient(user.coinbase_api_key, user.coinbase_private_key)

            try:
                signals = scan_entries(cfg.user_id, session, coinbase)
                if signals:
                    logger.info("Created %d signals for %s", len(signals), user.email)
            except Exception:
                logger.exception("Scan failed for user %s", cfg.user_id)


def _run_check_exits():
    with Session(_sync_engine) as session:
        users = session.execute(
            select(User).where(
                User.coinbase_api_key.isnot(None),
                User.coinbase_private_key.isnot(None),
            )
        ).scalars().all()

        coinbase_clients = {}
        for user in users:
            try:
                coinbase_clients[str(user.id)] = CoinbaseClient(
                    user.coinbase_api_key, user.coinbase_private_key
                )
            except Exception:
                pass

        exited = check_exits(session, coinbase_clients if coinbase_clients else None)
        if exited:
            logger.info("Exited %d positions", exited)

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
            if not user or not user.coinbase_api_key or not user.coinbase_private_key:
                continue

            coinbase = CoinbaseClient(user.coinbase_api_key, user.coinbase_private_key)
            try:
                result = sync_live_orders(session, cfg.user_id, coinbase)
                if result["filled"]:
                    logger.info("Live sync for %s: %d filled", user.email, result["filled"])
            except Exception:
                logger.exception("Live sync failed for %s", cfg.user_id)


async def start_scheduler():
    logger.info("Starting mean-reversion scheduler")

    async def scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_scan_and_evaluate)
                await asyncio.to_thread(_run_check_exits)
            except Exception:
                logger.exception("Scan/exit loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 60 - elapsed))

    async def sync_live_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_sync_live)
            except Exception:
                logger.exception("Live sync loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 30 - elapsed))

    tasks = [
        asyncio.create_task(scan_loop(), name="scan"),
        asyncio.create_task(sync_live_loop(), name="sync_live"),
    ]

    logger.info("Scheduler running: scan+exits(60s), live_sync(30s)")
    return tasks
