import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import History
from app.models.climate_config import ClimateConfig
from app.models.crypto_config import CryptoConfig
from app.models.user import User
from app.schemas.climate_config import ClimateConfigResponse, ClimateConfigUpdate
from app.schemas.crypto_config import CryptoConfigResponse, CryptoConfigUpdate
from app.schemas.kalshi_keys import KalshiKeysStatus, KalshiKeysUpdate
from app.services.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_FIELD_LABELS: dict[str, str] = {
    "mode": "Mode",
    "enabled": "Enabled",
    "series_tickers": "Series Tickers",
    "min_volume_24h": "Min 24h Volume",
    "min_price": "Min Price",
    "max_price": "Max Price",
    "min_hours_to_expiry": "Min Hours to Expiry",
    "min_edge": "Min Edge",
    "exit_edge": "Exit Edge",
    "contracts_per_signal": "Contracts per Signal",
    "max_cost_per_signal": "Max Cost per Signal",
    "max_open_positions": "Max Open Positions",
    "max_positions_per_event": "Max Positions per Event",
    "stop_loss_pct": "Stop Loss %",
    "take_profit_pct": "Take Profit %",
    "daily_loss_limit_usd": "Daily Loss Limit ($)",
    "max_signals_per_hour": "Max Signals per Hour",
    "min_hold_minutes": "Min Hold Minutes",
}


async def _log_config_changes(db: AsyncSession, user_id, section: str, old_values: dict, new_values: dict):
    """Create a History entry for each changed config field."""
    for key, value in new_values.items():
        old = old_values.get(key)
        old_str = str(old) if old is not None else "(none)"
        new_str = str(value) if value is not None else "(none)"
        if old_str == new_str:
            continue
        label = _FIELD_LABELS.get(key, key)
        text = f"{section}: User changed {label} from {old_str} to {new_str}"
        db.add(History(user_id=user_id, text=text))
    if new_values:
        await db.commit()


@router.get("/crypto-config", response_model=CryptoConfigResponse)
async def get_crypto_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(CryptoConfig).where(CryptoConfig.user_id == user.id))
    ).scalar_one_or_none()
    if not config:
        config = CryptoConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return _crypto_config_response(config)


def _crypto_config_response(config: CryptoConfig) -> CryptoConfigResponse:
    return CryptoConfigResponse(
        mode=config.mode,
        enabled=config.enabled,
        series_tickers=config.series_tickers,
        min_volume_24h=config.min_volume_24h,
        min_price=config.min_price,
        max_price=config.max_price,
        min_hours_to_expiry=config.min_hours_to_expiry,
        min_edge=config.min_edge,
        exit_edge=config.exit_edge,
        contracts_per_signal=config.contracts_per_signal,
        max_cost_per_signal=config.max_cost_per_signal,
        max_open_positions=config.max_open_positions,
        max_positions_per_event=config.max_positions_per_event,
        min_hold_minutes=config.min_hold_minutes,
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
        daily_loss_limit_usd=config.daily_loss_limit_usd,
        max_signals_per_hour=config.max_signals_per_hour,
    )


@router.put("/crypto-config", response_model=CryptoConfigResponse)
async def update_crypto_config(
    body: CryptoConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(CryptoConfig).where(CryptoConfig.user_id == user.id))
    ).scalar_one_or_none()
    if not config:
        config = CryptoConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    updates = body.model_dump(exclude_unset=True)
    if "mode" in updates and updates["mode"] not in ("paper", "live"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mode must be 'paper' or 'live'",
        )

    old_values = {key: getattr(config, key, None) for key in updates}

    for key, value in updates.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)

    await _log_config_changes(db, user.id, "Crypto", old_values, updates)

    return _crypto_config_response(config)


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


def _climate_config_response(config: ClimateConfig) -> ClimateConfigResponse:
    return ClimateConfigResponse(
        mode=config.mode,
        enabled=config.enabled,
        series_tickers=config.series_tickers,
        min_volume_24h=config.min_volume_24h,
        min_price=config.min_price,
        max_price=config.max_price,
        min_hours_to_expiry=config.min_hours_to_expiry,
        min_edge=config.min_edge,
        exit_edge=config.exit_edge,
        contracts_per_signal=config.contracts_per_signal,
        max_cost_per_signal=config.max_cost_per_signal,
        max_open_positions=config.max_open_positions,
        max_positions_per_event=config.max_positions_per_event,
        min_hold_minutes=config.min_hold_minutes,
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
        daily_loss_limit_usd=config.daily_loss_limit_usd,
        max_signals_per_hour=config.max_signals_per_hour,
    )


@router.get("/climate-config", response_model=ClimateConfigResponse)
async def get_climate_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(ClimateConfig).where(ClimateConfig.user_id == user.id))
    ).scalar_one_or_none()
    if not config:
        config = ClimateConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return _climate_config_response(config)


@router.put("/climate-config", response_model=ClimateConfigResponse)
async def update_climate_config(
    body: ClimateConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = (
        await db.execute(select(ClimateConfig).where(ClimateConfig.user_id == user.id))
    ).scalar_one_or_none()
    if not config:
        config = ClimateConfig(user_id=user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    updates = body.model_dump(exclude_unset=True)
    if "mode" in updates and updates["mode"] not in ("paper", "live"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mode must be 'paper' or 'live'",
        )

    old_values = {key: getattr(config, key, None) for key in updates}

    for key, value in updates.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)

    await _log_config_changes(db, user.id, "Climate", old_values, updates)

    return _climate_config_response(config)


class KalshiBalanceResponse(BaseModel):
    cash_cents: int = 0
    portfolio_cents: int = 0
    error: str | None = None


# Backtest endpoint removed as classical backtesting is deprecated.

def _read_cached_balance(user_id: str) -> dict | None:
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path

    try:
        path = Path(f"/tmp/kalshi_balance_{user_id}.json")
        if not path.exists():
            return None
        data = _json.loads(path.read_text())
        cached_at = datetime.fromisoformat(data["cached_at"])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age > 120:
            return None
        return data
    except Exception:
        return None


@router.get("/kalshi-balance", response_model=KalshiBalanceResponse)
async def get_kalshi_balance(user: User = Depends(get_current_user)):
    if user.kalshi_api_key_id and user.kalshi_private_key:
        try:
            client = KalshiClient(user.kalshi_api_key_id, user.kalshi_private_key)
            data = await client.get_balance()
            return KalshiBalanceResponse(
                cash_cents=int(data.get("balance", 0)),
                portfolio_cents=int(data.get("portfolio_value", 0)),
            )
        except Exception:
            logger.exception("Kalshi balance fetch failed, falling back to cache")

    cached = _read_cached_balance(str(user.id))
    if cached:
        return KalshiBalanceResponse(
            cash_cents=cached["cash_cents"],
            portfolio_cents=cached["portfolio_cents"],
        )

    if not user.kalshi_api_key_id:
        return KalshiBalanceResponse(error="no_keys")
    return KalshiBalanceResponse(error="balance_unavailable")


@router.post("/reset-data")
async def reset_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text

    result = await db.execute(text("SELECT COUNT(*) FROM signals"))
    count = result.scalar() or 0

    tables = ["signals"]
    for t in tables:
        await db.execute(text(f"DELETE FROM {t}"))
    await db.commit()

    db.add(History(user_id=user.id, text=f"Cleared all {count} signal records"))
    await db.commit()

    return {"status": "ok", "cleared": tables, "count": count}
