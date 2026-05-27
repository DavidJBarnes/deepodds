import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import History
from app.models.user import User
from app.schemas.history import HistoryCreate, HistoryListResponse, HistoryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["history"])


@router.post("", response_model=HistoryResponse, status_code=201)
async def create_history(
    body: HistoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entry = History(user_id=user.id, text=body.text)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return HistoryResponse(
        id=entry.id,
        user_id=entry.user_id,
        text=entry.text,
        created_at=entry.created_at,
    )


@router.get("", response_model=HistoryListResponse)
async def list_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(History).where(History.user_id == user.id)
    count_stmt = select(func.count()).select_from(History).where(History.user_id == user.id)

    total = (await db.execute(count_stmt)).scalar()
    results = (
        await db.execute(stmt.order_by(desc(History.created_at)).limit(limit).offset(offset))
    ).scalars().all()

    return HistoryListResponse(
        items=[
            HistoryResponse(id=h.id, user_id=h.user_id, text=h.text, created_at=h.created_at)
            for h in results
        ],
        total=total,
    )
