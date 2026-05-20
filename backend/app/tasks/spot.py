import asyncio
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from app.celery_app import celery
from app.core.config import settings
from app.services.spot_engine import check_dip_buys, check_spot_exits

logger = logging.getLogger(__name__)


@celery.task(name="check_spot_signals", bind=True, max_retries=0)
def check_spot_signals_task(self):
    engine = create_engine(settings.DATABASE_URL_SYNC)
    session = SyncSession(engine)
    try:
        buys = check_dip_buys(session)
        exits = check_spot_exits(session)
        if buys or exits:
            logger.info("Spot signals: %d buys, %d exits", buys, exits)
    except Exception:
        logger.exception("Error in spot signal check")
    finally:
        session.close()
        engine.dispose()


@celery.task(name="start_binance_stream", bind=True, max_retries=3)
def start_binance_stream_task(self):
    from app.services.binance_ws import run_binance_stream
    try:
        asyncio.run(run_binance_stream())
    except Exception as exc:
        logger.exception("Binance stream crashed")
        raise self.retry(exc=exc, countdown=10)
