import logging

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.bot_config import BotConfig
from app.models.user import User
from app.schemas.bot_config import BotConfigResponse, BotConfigUpdate
from app.schemas.settings import KalshiKeysStatus, KalshiKeysUpdate
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/bot-config", response_model=BotConfigResponse)
async def get_bot_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (await db.execute(
        select(BotConfig).where(BotConfig.user_id == user.id)
    )).scalar_one_or_none()

    if not config:
        config = BotConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    return BotConfigResponse(
        mode=config.mode, enabled=config.enabled,
        max_exposure_cents=config.max_exposure_cents,
        daily_budget_cents=config.daily_budget_cents,
        min_edge_cents=config.min_edge_cents,
        min_liquidity=config.min_liquidity,
        max_position_cents=config.max_position_cents,
        max_contracts_per_signal=config.max_contracts_per_signal,
        max_position_cents_moderate=config.max_position_cents_moderate,
        max_contracts_moderate=config.max_contracts_moderate,
        max_position_cents_high=config.max_position_cents_high,
        max_contracts_high=config.max_contracts_high,
        max_position_cents_elite=config.max_position_cents_elite,
        max_contracts_elite=config.max_contracts_elite,
        take_profit_cents=config.take_profit_cents,
        stop_loss_cents=config.stop_loss_cents,
        daily_loss_limit_cents=config.daily_loss_limit_cents,
        max_signals_per_hour=config.max_signals_per_hour,
        tier_budget_pct_elite=config.tier_budget_pct_elite,
        tier_budget_pct_high=config.tier_budget_pct_high,
        max_positions_per_asset=config.max_positions_per_asset,
    )


@router.put("/bot-config", response_model=BotConfigResponse)
async def update_bot_config(
    body: BotConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (await db.execute(
        select(BotConfig).where(BotConfig.user_id == user.id)
    )).scalar_one_or_none()

    if not config:
        config = BotConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    updates = body.model_dump(exclude_unset=True)
    if "mode" in updates and updates["mode"] not in ("paper", "live"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mode must be 'paper' or 'live'")

    for key, value in updates.items():
        setattr(config, key, value)

    await db.commit()
    await db.refresh(config)

    return BotConfigResponse(
        mode=config.mode, enabled=config.enabled,
        max_exposure_cents=config.max_exposure_cents,
        daily_budget_cents=config.daily_budget_cents,
        min_edge_cents=config.min_edge_cents,
        min_liquidity=config.min_liquidity,
        max_position_cents=config.max_position_cents,
        max_contracts_per_signal=config.max_contracts_per_signal,
        max_position_cents_moderate=config.max_position_cents_moderate,
        max_contracts_moderate=config.max_contracts_moderate,
        max_position_cents_high=config.max_position_cents_high,
        max_contracts_high=config.max_contracts_high,
        max_position_cents_elite=config.max_position_cents_elite,
        max_contracts_elite=config.max_contracts_elite,
        take_profit_cents=config.take_profit_cents,
        stop_loss_cents=config.stop_loss_cents,
        daily_loss_limit_cents=config.daily_loss_limit_cents,
        max_signals_per_hour=config.max_signals_per_hour,
        tier_budget_pct_elite=config.tier_budget_pct_elite,
        tier_budget_pct_high=config.tier_budget_pct_high,
        max_positions_per_asset=config.max_positions_per_asset,
    )


@router.put("/kalshi-keys", response_model=KalshiKeysStatus)
async def update_kalshi_keys(
    body: KalshiKeysUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        load_pem_private_key(body.api_private_key.encode(), password=None)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid RSA private key PEM")

    user.kalshi_api_key_id = body.api_key_id
    user.kalshi_api_private_key = body.api_private_key
    await db.commit()
    return KalshiKeysStatus(has_keys=True, key_id_preview=body.api_key_id[:8] + "...")


@router.get("/kalshi-keys", response_model=KalshiKeysStatus)
async def get_kalshi_keys(user: User = Depends(get_current_user)):
    if user.kalshi_api_key_id:
        return KalshiKeysStatus(has_keys=True, key_id_preview=user.kalshi_api_key_id[:8] + "...")
    return KalshiKeysStatus(has_keys=False)


@router.delete("/kalshi-keys", response_model=KalshiKeysStatus)
async def delete_kalshi_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.kalshi_api_key_id = None
    user.kalshi_api_private_key = None
    await db.commit()
    return KalshiKeysStatus(has_keys=False)


class KalshiBalanceResponse(BaseModel):
    cash_cents: int
    portfolio_cents: int


@router.get("/kalshi-balance", response_model=KalshiBalanceResponse)
async def get_kalshi_balance(user: User = Depends(get_current_user)):
    if not user.kalshi_api_key_id or not user.kalshi_api_private_key:
        return KalshiBalanceResponse(cash_cents=0, portfolio_cents=0)
    try:
        client = KalshiClient(user.kalshi_api_key_id, user.kalshi_api_private_key)
        data = await client.get_balance()
        return KalshiBalanceResponse(
            cash_cents=data.get("balance", 0),
            portfolio_cents=data.get("portfolio_value", 0),
        )
    except Exception:
        logger.exception("Failed to fetch Kalshi balance")
        return KalshiBalanceResponse(cash_cents=0, portfolio_cents=0)
