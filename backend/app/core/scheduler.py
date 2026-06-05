"""API-side background scheduler.

The market scan / score / signal / exit / Platt-refit loops live in the
separate scanner process (backend/scanner/main.py). This scheduler runs
only what the api container owns:

- live order/fill reconciliation (kalshi_sync_live_loop)
- model retraining cron with throttle (kalshi_retrain_loop, climate_retrain_loop)
- API-side data caches (refresh_crypto_data_loop, refresh_climate_data_loop)
- per-user Kalshi balance cache (balance_cache_loop)
"""

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, desc, select, update
from sqlalchemy.orm import Session

from app.core.async_util import run_async
from app.core.config import settings
from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.history import History
from app.models.model_train_history import ModelTrainHistory
from app.models.user import User
from app.services.binance_client import get_crypto_prices, get_market_stats, get_realized_vol
from app.services.kalshi_client import KalshiClient
from app.services.kalshi_live_sync import sync_kalshi_live
from app.services.market_data import set as cache_set
from app.services.probability_model import series_to_underlying

logger = logging.getLogger(__name__)

_sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_size=5, max_overflow=5)

_SCHEDULER_TIMEOUT = 120
_RETRAIN_INTERVAL = timedelta(days=7)
# Skip the iteration's retrain if a successful active run exists within this
# window. Prevents container restarts from triggering off-cycle retraining.
_RETRAIN_THROTTLE = timedelta(days=6)


def _last_active_retrain(session: Session, venue: str) -> ModelTrainHistory | None:
    col = (
        ModelTrainHistory.crypto_active if venue == "crypto"
        else ModelTrainHistory.climate_active
    )
    return session.execute(
        select(ModelTrainHistory)
        .where(col.is_(True))
        .order_by(desc(ModelTrainHistory.completed_at))
        .limit(1)
    ).scalar_one_or_none()


def _retrain_skip_age(session: Session, venue: str) -> timedelta | None:
    last = _last_active_retrain(session, venue)
    if last is None:
        return None
    age = datetime.now(timezone.utc) - last.completed_at
    return age if age < _RETRAIN_THROTTLE else None


def _write_balance_cache(user_id: str, data: dict) -> None:
    import json as _json
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


def _run_kalshi_sync_live() -> None:
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


def _refresh_crypto_cache() -> None:
    """Prefetch shared crypto market data and populate the global cache."""
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


async def _run_in_scheduler(executor: ThreadPoolExecutor, func, timeout: float = _SCHEDULER_TIMEOUT):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(executor, func),
        timeout=timeout,
    )


async def start_scheduler():
    """Start the api-side background scheduler."""
    logger.info("Starting api scheduler (live sync, retrains, caches)")

    scheduler_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scheduler")

    async def kalshi_sync_live_loop():
        while True:
            try:
                await _run_in_scheduler(scheduler_executor, _run_kalshi_sync_live)
            except Exception:
                logger.exception("Kalshi live sync loop failed")
            await asyncio.sleep(30)

    async def kalshi_retrain_loop():
        await asyncio.sleep(3600)
        while True:
            try:
                with Session(_sync_engine) as session:
                    skip_age = _retrain_skip_age(session, "crypto")
                if skip_age is not None:
                    logger.info(
                        "Skipping crypto retrain — last successful run was %.1fh ago (throttle %dh)",
                        skip_age.total_seconds() / 3600,
                        _RETRAIN_THROTTLE.total_seconds() / 3600,
                    )
                    await asyncio.sleep(_RETRAIN_INTERVAL.total_seconds())
                    continue

                logger.info("Triggering weekly crypto model retraining...")
                from app.services.train_model import train_and_save_model
                from app.services.probability_model import MODEL_FILE, reload_booster
                started_at = datetime.now(timezone.utc)
                success, snapshot = await train_and_save_model()
                crypto_kb = os.path.getsize(MODEL_FILE) / 1024 if os.path.exists(MODEL_FILE) else 0
                msg = "Automated crypto model retraining " + ("succeeded" if success else "failed")
                if success:
                    reload_booster()
                with Session(_sync_engine) as session:
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
                    users = session.execute(select(User)).scalars().all()
                    for user in users:
                        session.add(History(user_id=user.id, text=msg))
                    session.commit()
            except Exception:
                logger.exception("Crypto retrain loop failed")
            await asyncio.sleep(_RETRAIN_INTERVAL.total_seconds())

    async def climate_retrain_loop():
        await asyncio.sleep(3600)
        while True:
            try:
                with Session(_sync_engine) as session:
                    skip_age = _retrain_skip_age(session, "climate")
                if skip_age is not None:
                    logger.info(
                        "Skipping climate retrain — last successful run was %.1fh ago (throttle %dh)",
                        skip_age.total_seconds() / 3600,
                        _RETRAIN_THROTTLE.total_seconds() / 3600,
                    )
                    await asyncio.sleep(_RETRAIN_INTERVAL.total_seconds())
                    continue

                logger.info("Triggering weekly climate model retraining...")
                from app.services.train_climate_model import train_and_save_climate_model
                from app.services.climate_probability_model import (
                    MODEL_FILE as CLIMATE_MODEL_FILE,
                    reload_booster as reload_climate_booster,
                )
                started_at = datetime.now(timezone.utc)
                success, snapshot = await train_and_save_climate_model()
                climate_kb = os.path.getsize(CLIMATE_MODEL_FILE) / 1024 if os.path.exists(CLIMATE_MODEL_FILE) else 0
                msg = "Automated climate model retraining " + ("succeeded" if success else "failed")
                if success:
                    reload_climate_booster()
                with Session(_sync_engine) as session:
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
                    users = session.execute(select(User)).scalars().all()
                    for user in users:
                        session.add(History(user_id=user.id, text=msg))
                    session.commit()
            except Exception:
                logger.exception("Climate retrain loop failed")
            await asyncio.sleep(_RETRAIN_INTERVAL.total_seconds())

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
        asyncio.create_task(kalshi_sync_live_loop(), name="kalshi_sync_live"),
        asyncio.create_task(kalshi_retrain_loop(), name="kalshi_retrain"),
        asyncio.create_task(climate_retrain_loop(), name="climate_retrain"),
        asyncio.create_task(refresh_crypto_data_loop(), name="refresh_crypto"),
        asyncio.create_task(refresh_climate_data_loop(), name="refresh_climate"),
        asyncio.create_task(balance_cache_loop(), name="balance_cache"),
    ]

    logger.info(
        "Api scheduler running: kalshi_sync_live(30s), retrains(7d w/ 6d throttle), "
        "refresh_crypto(30s), refresh_climate(30s), balance_cache(60s)"
    )
    return tasks, scheduler_executor
