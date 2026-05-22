import asyncio
import logging
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.core.config import settings
from app.models.bot_config import BotConfig
from app.models.user import User
from app.services.kalshi_client import KalshiClient
from app.services.market_scanner import prune_settled_batch, scan_opportunities
from app.services.signal_engine import (
    check_take_profits,
    evaluate_naive_no,
    evaluate_opportunities,
    evaluate_settlement_arb,
    settle_signals,
    simulate_fills,
    sync_live_orders,
)

logger = logging.getLogger(__name__)

# Shared sync engine for background tasks — one connection pool for all scheduler loops.
_sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_size=5, max_overflow=5)


def _scanner_kalshi() -> KalshiClient | None:
    with Session(_sync_engine) as session:
        user = session.execute(
            select(User).where(
                User.kalshi_api_key_id.isnot(None),
                User.kalshi_api_private_key.isnot(None),
            ).limit(1)
        ).scalar_one_or_none()
        if not user:
            return None
        return KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)


def _run_scan_sync() -> int:
    """Fetch opportunities from Kalshi and upsert into the database."""
    kalshi = _scanner_kalshi()
    if not kalshi:
        logger.warning("No user with Kalshi keys found — skipping scan")
        return 0

    keys_valid = True
    try:
        keys_valid = run_async(kalshi.validate())
    except Exception:
        keys_valid = False

    count = 0
    error_msg = None
    with Session(_sync_engine) as session:
        try:
            count = run_async(scan_opportunities(kalshi, session))
            logger.info("Scanner upserted %d opportunities", count)
        except Exception as e:
            error_msg = str(e)[:200]
            logger.exception("Scanner failed")

    # Write health to file for dashboard
    from datetime import datetime, timezone
    from pathlib import Path
    import json as _json

    try:
        Path("/tmp/scanner_health.json").write_text(_json.dumps({
            "last_scan": datetime.now(timezone.utc).isoformat(),
            "opportunities": count,
            "keys_valid": keys_valid,
            "error": error_msg,
        }))
    except Exception:
        pass

    return count


def _run_evaluate_all_sync():
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

            kalshi = None
            if cfg.mode == "live" and user.kalshi_api_key_id and user.kalshi_api_private_key:
                kalshi = KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)

            try:
                if cfg.strategy == "naive_no":
                    signals = evaluate_naive_no(cfg.user_id, session)
                elif cfg.strategy == "settlement_arb":
                    signals = evaluate_settlement_arb(cfg.user_id, session, kalshi)
                else:
                    signals = evaluate_opportunities(cfg.user_id, session, kalshi)
                if signals:
                    logger.info("Created %d signals for user %s", len(signals), user.email)
            except Exception:
                logger.exception("Signal evaluation failed for user %s", cfg.user_id)


def _run_process_paper_sync():
    with Session(_sync_engine) as session:
        filled = simulate_fills(session)
        exited = check_take_profits(session)
        if filled or exited:
            logger.info("Paper positions: %d filled, %d take-profit exits", filled, exited)


def _run_settle_sync():
    with Session(_sync_engine) as session:
        users_with_keys = session.execute(
            select(User).where(
                User.kalshi_api_key_id.isnot(None),
                User.kalshi_api_private_key.isnot(None),
            )
        ).scalars().all()
        kalshi_clients = {}
        for user in users_with_keys:
            try:
                kalshi_clients[user.id] = KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)
            except Exception:
                pass

        settled = settle_signals(session, kalshi_clients)
        pruned = prune_settled_batch(session)
        if settled:
            logger.info("Settled %d signals", settled)
        if pruned:
            logger.info("Pruned %d expired opportunities", pruned)


def _run_sync_live_sync():
    with Session(_sync_engine) as session:
        configs = session.execute(
            select(BotConfig).where(BotConfig.mode == "live")
        ).scalars().all()

        for cfg in configs:
            user = session.execute(
                select(User).where(User.id == cfg.user_id)
            ).scalar_one_or_none()
            if not user or not user.kalshi_api_key_id or not user.kalshi_api_private_key:
                continue

            kalshi = KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)
            try:
                result = sync_live_orders(session, cfg.user_id, kalshi)
                if result["filled"] or result["settled"]:
                    logger.info(
                        "Live sync for %s: %d filled, %d settled",
                        user.email, result["filled"], result["settled"],
                    )
            except Exception:
                logger.exception("Live order sync failed for user %s", cfg.user_id)


async def start_scheduler():
    """Launch all periodic trading tasks as asyncio background loops.

    Runs native asyncio loops instead of Celery + Redis. Each task
    runs in a thread via asyncio.to_thread() to keep the event loop responsive.
    """
    logger.info("Starting native scheduler")

    async def scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_scan_sync)
                await asyncio.to_thread(_run_evaluate_all_sync)
                await asyncio.to_thread(_run_process_paper_sync)
            except Exception:
                logger.exception("Scan/evaluate loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 30 - elapsed))

    async def settle_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_settle_sync)
            except Exception:
                logger.exception("Settle loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 300 - elapsed))

    async def sync_live_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_sync_live_sync)
            except Exception:
                logger.exception("Sync live loop failed")
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, 60 - elapsed))

    tasks = [
        asyncio.create_task(scan_loop(), name="scan"),
        asyncio.create_task(settle_loop(), name="settle"),
        asyncio.create_task(sync_live_loop(), name="sync_live"),
    ]

    logger.info("Scheduler running: scan(30s), settle(5m), sync(1m)")

    # Return tasks so the caller can cancel them on shutdown
    return tasks
