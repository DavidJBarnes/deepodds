import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.bot_config import BotConfig
from app.models.user import User
from app.schemas.bot_config import BotConfigResponse, BotConfigUpdate
from app.schemas.settings import RobinhoodKeysStatus, RobinhoodKeysUpdate
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
