import logging

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.core.config import settings
from app.models.bot_config import BotConfig
from app.models.user import User
from app.services.kalshi_client import KalshiClient
from app.services.signal_engine import (
    check_take_profits,
    evaluate_opportunities,
    settle_signals,
    simulate_fills,
)

logger = logging.getLogger(__name__)


@celery.task(name="evaluate_all_users", bind=True, max_retries=0)
def evaluate_all_users_task(self):
    engine = create_engine(settings.DATABASE_URL_SYNC)
    with Session(engine) as session:
        configs = session.execute(
            select(BotConfig).where(BotConfig.enabled.is_(True))
        ).scalars().all()

        for config in configs:
            user = session.execute(
                select(User).where(User.id == config.user_id)
            ).scalar_one_or_none()
            if not user:
                continue

            kalshi = None
            if config.mode == "live" and user.kalshi_api_key_id and user.kalshi_api_private_key:
                kalshi = KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)

            try:
                signals = evaluate_opportunities(config.user_id, session, kalshi)
                if signals:
                    logger.info("Created %d signals for user %s", len(signals), user.email)
            except Exception:
                logger.exception("Signal evaluation failed for user %s", config.user_id)

    engine.dispose()


@celery.task(name="process_paper_positions", bind=True, max_retries=0)
def process_paper_positions_task(self):
    engine = create_engine(settings.DATABASE_URL_SYNC)
    with Session(engine) as session:
        try:
            filled = simulate_fills(session)
            exited = check_take_profits(session)
            if filled or exited:
                logger.info("Paper positions: %d filled, %d take-profit exits", filled, exited)
        except Exception:
            logger.exception("Paper position processing failed")
    engine.dispose()


@celery.task(name="settle_signals", bind=True, max_retries=0)
def settle_signals_task(self):
    engine = create_engine(settings.DATABASE_URL_SYNC)
    with Session(engine) as session:
        try:
            settled = settle_signals(session)
            if settled:
                logger.info("Settled %d signals", settled)
        except Exception:
            logger.exception("Signal settlement failed")
    engine.dispose()
