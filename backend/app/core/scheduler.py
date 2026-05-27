import asyncio
import logging
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.core.config import settings
from app.models.kalshi_config import KalshiConfig
from app.models.user import User
from app.services.kalshi_client import KalshiClient
from app.services.kalshi_fair_value import (
    cancel_stale_placed_orders,
    check_kalshi_exits,
    scan_kalshi_entries,
    settle_expired_paper,
)
from app.services.kalshi_live_sync import sync_kalshi_live

_BALANCE_CACHE_TTL = 60  # seconds; scheduler refreshes every 30s

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

            # Re-fetch portfolio/cash balance after each scan cycle
            if client:
                try:
                    bal = run_async(client.get_balance())
                    _write_balance_cache(str(cfg.user_id), bal)
                except Exception:
                    logger.exception("Failed to cache Kalshi balance for user %s", cfg.user_id)


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


async def start_scheduler():
    logger.info("Starting Kalshi scheduler")

    async def kalshi_scan_loop():
        while True:
            t0 = time.monotonic()
            try:
                await asyncio.to_thread(_run_kalshi_scan)
                await asyncio.to_thread(_run_kalshi_check_exits)
                await asyncio.to_thread(_run_kalshi_housekeeping)
                _write_scanner_health("online")
            except Exception as exc:
                _write_scanner_health("error", str(exc)[:200])
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
        asyncio.create_task(kalshi_scan_loop(), name="kalshi_scan"),
        asyncio.create_task(kalshi_sync_live_loop(), name="kalshi_sync_live"),
    ]

    logger.info(
        "Scheduler running: kalshi(30s), kalshi_live(30s)"
    )
    return tasks
