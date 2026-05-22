import asyncio
import json
import logging
from datetime import datetime, timezone

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from app.celery_app import celery
from app.core.config import settings
from app.services.kalshi_client import KalshiClient
from app.services.market_scanner import scan_opportunities

logger = logging.getLogger(__name__)


def _get_scanner_kalshi() -> KalshiClient | None:
    engine = create_engine(settings.DATABASE_URL_SYNC)
    session = SyncSession(engine)
    try:
        from app.models.user import User
        from sqlalchemy import select
        user = session.execute(
            select(User).where(
                User.kalshi_api_key_id.isnot(None),
                User.kalshi_api_private_key.isnot(None),
            ).limit(1)
        ).scalar_one_or_none()
        if not user:
            return None
        return KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)
    finally:
        session.close()
        engine.dispose()


async def _run_scan():
    kalshi = _get_scanner_kalshi()
    if not kalshi:
        logger.warning("No user with Kalshi keys found — skipping scan")
        return 0

    # Validate keys — warn if invalid but don't block (network hiccups happen)
    keys_valid = True
    try:
        keys_valid = await kalshi.validate()
        if not keys_valid:
            logger.warning("Kalshi keys returned invalid — scanning anyway")
    except Exception:
        logger.warning("Kalshi key validation failed (network?) — scanning anyway")
        keys_valid = False

    engine = create_engine(settings.DATABASE_URL_SYNC)
    session = SyncSession(engine)
    error_msg = None
    count = 0
    try:
        count = await scan_opportunities(kalshi, session)
        logger.info("Scanner upserted %d opportunities", count)
    except Exception as e:
        error_msg = str(e)[:200]
        logger.exception("Scanner failed")
    finally:
        session.close()
        engine.dispose()

    # Write health to Redis
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        health = {
            "last_scan": datetime.now(timezone.utc).isoformat(),
            "opportunities": count,
            "keys_valid": keys_valid,
            "error": error_msg,
        }
        r.set("scanner:health", json.dumps(health))
        r.expire("scanner:health", 300)  # TTL 5 min — if no scan in 5 min, consider dead
    except Exception:
        pass

    return count


@celery.task(name="scan_markets", bind=True, max_retries=0)
def scan_markets(self):
    asyncio.run(_run_scan())
    from celery import chain
    from app.tasks.signals import evaluate_all_users_task, process_paper_positions_task
    chain(evaluate_all_users_task.si(), process_paper_positions_task.si()).delay()
