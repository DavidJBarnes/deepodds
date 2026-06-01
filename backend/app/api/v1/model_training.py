import logging
import os

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.model_train_history import ModelTrainHistory
from app.models.user import User
from app.schemas.model_train_history import (
    ModelTrainHistoryCreate,
    ModelTrainHistoryListResponse,
    ModelTrainHistoryResponse,
)


def _exists(path: str | None) -> bool:
    return bool(path) and os.path.exists(path)


def _to_response(r: ModelTrainHistory) -> ModelTrainHistoryResponse:
    return ModelTrainHistoryResponse(
        id=r.id,
        user_id=r.user_id,
        model_type=r.model_type,
        crypto_ok=r.crypto_ok,
        climate_ok=r.climate_ok,
        crypto_size_kb=r.crypto_size_kb,
        climate_size_kb=r.climate_size_kb,
        total_size_kb=r.total_size_kb,
        crypto_model_path=r.crypto_model_path,
        climate_model_path=r.climate_model_path,
        crypto_active=r.crypto_active,
        climate_active=r.climate_active,
        crypto_snapshot_exists=_exists(r.crypto_model_path),
        climate_snapshot_exists=_exists(r.climate_model_path),
        message=r.message,
        trigger=r.trigger,
        started_at=r.started_at,
        completed_at=r.completed_at,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model-training-history", tags=["model-training-history"])


class ListParams(BaseModel):
    limit: int = 20
    offset: int = 0


@router.get("", response_model=ModelTrainHistoryListResponse)
async def list_model_training_history(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(ModelTrainHistory).where(
        (ModelTrainHistory.user_id == user.id) | (ModelTrainHistory.user_id.is_(None))
    )
    count_stmt = (
        select(func.count())
        .select_from(ModelTrainHistory)
        .where(
            (ModelTrainHistory.user_id == user.id) | (ModelTrainHistory.user_id.is_(None))
        )
    )

    total = (await db.execute(count_stmt)).scalar()
    results = (
        await db.execute(
            stmt.order_by(desc(ModelTrainHistory.completed_at)).limit(limit).offset(offset)
        )
    ).scalars().all()

    return ModelTrainHistoryListResponse(
        items=[_to_response(r) for r in results],
        total=total,
    )


@router.post("", response_model=ModelTrainHistoryResponse, status_code=201)
async def create_model_training_history(
    body: ModelTrainHistoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entry = ModelTrainHistory(
        user_id=user.id if body.trigger != "scheduled" else None,
        model_type=body.model_type,
        crypto_ok=body.crypto_ok,
        climate_ok=body.climate_ok,
        crypto_size_kb=body.crypto_size_kb,
        climate_size_kb=body.climate_size_kb,
        total_size_kb=body.total_size_kb,
        message=body.message,
        trigger=body.trigger,
        started_at=body.started_at,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _to_response(entry)
