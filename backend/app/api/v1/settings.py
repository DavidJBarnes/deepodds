import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.bot_config import BotConfig
from app.models.kalshi_config import KalshiConfig
from app.models.pair_config import PairConfig
from app.models.user import User
from app.schemas.bot_config import BotConfigResponse, BotConfigUpdate
from app.schemas.kalshi_config import KalshiConfigResponse, KalshiConfigUpdate, KalshiKeysStatus, KalshiKeysUpdate
from app.schemas.pair_config import PairConfigResponse, PairConfigUpdate
from app.schemas.settings import RobinhoodKeysStatus, RobinhoodKeysUpdate
from app.services.kalshi_client import KalshiClient
from app.services.robinhood_client import RobinhoodClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/bot-config", response_model=BotConfigResponse)
async def get_bot_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(BotConfig).where(BotConfig.user_id == user.id))
    ).scalar_one_or_none()

    if not config:
        config = BotConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    return _config_response(config)


def _config_response(config: BotConfig) -> BotConfigResponse:
    return BotConfigResponse(
        mode=config.mode,
        enabled=config.enabled,
        pairs=config.pairs,
        lookback_periods=config.lookback_periods,
        entry_z_score=config.entry_z_score,
        exit_z_score=config.exit_z_score,
        position_size_usd=config.position_size_usd,
        max_open_positions=config.max_open_positions,
        stop_loss_pct=config.stop_loss_pct,
        daily_loss_limit_usd=config.daily_loss_limit_usd,
        max_signals_per_hour=config.max_signals_per_hour,
        min_hold_minutes=config.min_hold_minutes,
    )


@router.put("/bot-config", response_model=BotConfigResponse)
async def update_bot_config(
    body: BotConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(BotConfig).where(BotConfig.user_id == user.id))
    ).scalar_one_or_none()

    if not config:
        config = BotConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    updates = body.model_dump(exclude_unset=True)
    if "mode" in updates and updates["mode"] not in ("paper", "live"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mode must be 'paper' or 'live'",
        )
    for key, value in updates.items():
        setattr(config, key, value)

    await db.commit()
    await db.refresh(config)
    return _config_response(config)


@router.put("/exchange-keys", response_model=RobinhoodKeysStatus)
async def update_exchange_keys(
    body: RobinhoodKeysUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.api_key or not body.private_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key and private key are required",
        )

    user.robinhood_api_key = body.api_key
    user.robinhood_private_key = body.private_key
    await db.commit()

    valid = False
    try:
        rh = RobinhoodClient(body.api_key, body.private_key)
        valid = await rh.validate()
    except Exception:
        pass

    return RobinhoodKeysStatus(
        has_keys=True, key_preview=body.api_key[:12] + "...", valid=valid
    )


@router.get("/exchange-keys", response_model=RobinhoodKeysStatus)
async def get_exchange_keys(user: User = Depends(get_current_user)):
    if not user.robinhood_api_key:
        return RobinhoodKeysStatus(has_keys=False)
    valid = False
    try:
        rh = RobinhoodClient(user.robinhood_api_key, user.robinhood_private_key)
        valid = await rh.validate()
    except Exception:
        pass
    return RobinhoodKeysStatus(
        has_keys=True, key_preview=user.robinhood_api_key[:12] + "...", valid=valid
    )


@router.delete("/exchange-keys", response_model=RobinhoodKeysStatus)
async def delete_exchange_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.robinhood_api_key = None
    user.robinhood_private_key = None
    await db.commit()
    return RobinhoodKeysStatus(has_keys=False)


@router.get("/kalshi-config", response_model=KalshiConfigResponse)
async def get_kalshi_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(KalshiConfig).where(KalshiConfig.user_id == user.id))
    ).scalar_one_or_none()
    if not config:
        config = KalshiConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return _kalshi_config_response(config)


def _kalshi_config_response(config: KalshiConfig) -> KalshiConfigResponse:
    return KalshiConfigResponse(
        mode=config.mode,
        enabled=config.enabled,
        series_tickers=config.series_tickers,
        min_volume_24h=config.min_volume_24h,
        min_price=config.min_price,
        max_price=config.max_price,
        min_hours_to_expiry=config.min_hours_to_expiry,
        min_edge=config.min_edge,
        vol_lookback_hours=config.vol_lookback_hours,
        vol_interval=config.vol_interval,
        exit_edge=config.exit_edge,
        contracts_per_signal=config.contracts_per_signal,
        max_cost_per_signal=config.max_cost_per_signal,
        max_open_positions=config.max_open_positions,
        max_positions_per_event=config.max_positions_per_event,
        stop_loss_pct=config.stop_loss_pct,
        daily_loss_limit_usd=config.daily_loss_limit_usd,
        max_signals_per_hour=config.max_signals_per_hour,
    )


@router.put("/kalshi-config", response_model=KalshiConfigResponse)
async def update_kalshi_config(
    body: KalshiConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(KalshiConfig).where(KalshiConfig.user_id == user.id))
    ).scalar_one_or_none()
    if not config:
        config = KalshiConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    updates = body.model_dump(exclude_unset=True)
    if "mode" in updates and updates["mode"] not in ("paper", "live"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mode must be 'paper' or 'live'",
        )
    for key, value in updates.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return _kalshi_config_response(config)


@router.put("/kalshi-keys", response_model=KalshiKeysStatus)
async def update_kalshi_keys(
    body: KalshiKeysUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.kalshi_api_key_id = body.api_key_id
    user.kalshi_private_key = body.private_key_pem
    await db.commit()

    valid = False
    try:
        kc = KalshiClient(body.api_key_id, body.private_key_pem)
        valid = await kc.validate()
    except Exception:
        pass

    return KalshiKeysStatus(
        has_keys=True, key_preview=body.api_key_id[:12] + "...", valid=valid
    )


@router.get("/kalshi-keys", response_model=KalshiKeysStatus)
async def get_kalshi_keys(user: User = Depends(get_current_user)):
    if not user.kalshi_api_key_id:
        return KalshiKeysStatus(has_keys=False)
    valid = False
    try:
        kc = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
        valid = await kc.validate()
    except Exception:
        pass
    return KalshiKeysStatus(
        has_keys=True, key_preview=user.kalshi_api_key_id[:12] + "...", valid=valid
    )


@router.delete("/kalshi-keys", response_model=KalshiKeysStatus)
async def delete_kalshi_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.kalshi_api_key_id = None
    user.kalshi_private_key = None
    await db.commit()
    return KalshiKeysStatus(has_keys=False)


@router.get("/pair-configs", response_model=list[PairConfigResponse])
async def list_pair_configs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        await db.execute(select(PairConfig).where(PairConfig.user_id == user.id))
    ).scalars().all()
    return [
        PairConfigResponse(
            venue=pc.venue, pair=pc.pair,
            entry_z_score=pc.entry_z_score, exit_z_score=pc.exit_z_score,
            position_size_usd=pc.position_size_usd,
            contracts_per_signal=pc.contracts_per_signal,
            stop_loss_pct=pc.stop_loss_pct,
            min_edge=pc.min_edge,
            exit_edge=pc.exit_edge,
        )
        for pc in rows
    ]


@router.put("/pair-configs/{venue}/{pair:path}", response_model=PairConfigResponse)
async def upsert_pair_config(
    venue: str,
    pair: str,
    body: PairConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if venue not in ("crypto", "kalshi"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Venue must be 'crypto' or 'kalshi'")

    pc = (
        await db.execute(
            select(PairConfig).where(
                PairConfig.user_id == user.id, PairConfig.venue == venue, PairConfig.pair == pair
            )
        )
    ).scalar_one_or_none()

    if not pc:
        pc = PairConfig(user_id=user.id, venue=venue, pair=pair)
        db.add(pc)

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(pc, key, value)

    await db.commit()
    await db.refresh(pc)

    return PairConfigResponse(
        venue=pc.venue, pair=pc.pair,
        entry_z_score=pc.entry_z_score, exit_z_score=pc.exit_z_score,
        position_size_usd=pc.position_size_usd,
        contracts_per_signal=pc.contracts_per_signal,
        stop_loss_pct=pc.stop_loss_pct,
        min_edge=pc.min_edge,
        exit_edge=pc.exit_edge,
    )


@router.delete("/pair-configs/{venue}/{pair:path}")
async def delete_pair_config(
    venue: str,
    pair: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pc = (
        await db.execute(
            select(PairConfig).where(
                PairConfig.user_id == user.id, PairConfig.venue == venue, PairConfig.pair == pair
            )
        )
    ).scalar_one_or_none()

    if not pc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")

    await db.delete(pc)
    await db.commit()
    return {"status": "ok"}


class KalshiBalanceResponse(BaseModel):
    cash_cents: int = 0
    portfolio_cents: int = 0
    error: str | None = None


@router.get("/kalshi-balance", response_model=KalshiBalanceResponse)
async def get_kalshi_balance(user: User = Depends(get_current_user)):
    if not user.kalshi_api_key_id or not user.kalshi_private_key:
        return KalshiBalanceResponse(error="no_keys")

    try:
        client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
    except Exception as e:
        logger.exception("Failed to initialize KalshiClient")
        return KalshiBalanceResponse(error=f"key_parse_error: {str(e)[:80]}")

    try:
        data = await client.get_balance()
        return KalshiBalanceResponse(
            cash_cents=int(data.get("balance", 0)),
            portfolio_cents=int(data.get("portfolio_value", 0)),
        )
    except Exception as e:
        logger.exception("Failed to fetch Kalshi balance")
        return KalshiBalanceResponse(error=f"balance_error: {str(e)[:80]}")


class BacktestRequest(BaseModel):
    venue: str
    pair: str
    entry_z_score: float | None = Field(None, ge=-5.0, le=-0.5)
    exit_z_score: float | None = Field(None, ge=-1.0, le=3.0)
    stop_loss_pct: float = Field(ge=0.5, le=50.0)
    position_size_usd: float = Field(default=25.0, ge=5.0, le=1000.0)
    contracts_per_signal: int = Field(default=50, ge=1, le=10000)
    lookback_periods: int = Field(default=48, ge=4, le=200)
    min_edge: float | None = Field(None, ge=0.01, le=0.50)
    exit_edge: float | None = Field(None, ge=-0.50, le=0.0)
    vol_lookback_hours: int | None = Field(None, ge=1, le=168)


@router.post("/backtest-preview")
async def backtest_preview(
    body: BacktestRequest,
    _user: User = Depends(get_current_user),
):
    from app.services.backtest import run_backtest_preview

    result = await run_backtest_preview(
        venue=body.venue,
        pair=body.pair,
        entry_z_score=body.entry_z_score,
        exit_z_score=body.exit_z_score,
        stop_loss_pct=body.stop_loss_pct,
        position_size_usd=body.position_size_usd,
        contracts_per_signal=body.contracts_per_signal,
        lookback_periods=body.lookback_periods,
        min_edge=body.min_edge,
        exit_edge=body.exit_edge,
        vol_lookback_hours=body.vol_lookback_hours,
    )
    return result


@router.post("/reset-data")
async def reset_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text

    tables = ["signals", "archived_signals"]
    for t in tables:
        await db.execute(text(f"DELETE FROM {t}"))
    await db.commit()
    return {"status": "ok", "cleared": tables}
