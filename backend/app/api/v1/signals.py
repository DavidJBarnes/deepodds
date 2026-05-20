from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.archived_signal import ArchivedSignal
from app.models.signal import Signal
from app.models.user import User
from app.schemas.signal import SignalListResponse, SignalResponse
from app.services.archive import archive_signals_async

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=SignalListResponse)
async def list_signals(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Signal).where(Signal.user_id == user.id)
    count_stmt = select(func.count()).select_from(Signal).where(Signal.user_id == user.id)

    if status:
        stmt = stmt.where(Signal.status == status)
        count_stmt = count_stmt.where(Signal.status == status)

    total = (await db.execute(count_stmt)).scalar()
    results = (await db.execute(
        stmt.order_by(desc(Signal.created_at)).limit(limit).offset(offset)
    )).scalars().all()

    return SignalListResponse(
        items=[
            SignalResponse(
                id=s.id, ticker=s.ticker, side=s.side, action=s.action,
                limit_price_cents=s.limit_price_cents, quantity=s.quantity,
                cost_cents=s.cost_cents, signal_type=s.signal_type, status=s.status,
                model_prob=s.model_prob, model_fair_cents=s.model_fair_cents,
                model_edge_cents=s.model_edge_cents, edge_tier=s.edge_tier,
                implied_vol=s.implied_vol,
                market_yes_price_cents=s.market_yes_price_cents,
                spot_price=s.spot_price, strike_price=s.strike_price,
                kalshi_order_id=s.kalshi_order_id, fill_price_cents=s.fill_price_cents,
                exit_price_cents=s.exit_price_cents, filled_at=s.filled_at,
                pnl_cents=s.pnl_cents, settled_side=s.settled_side,
                close_time=s.close_time, created_at=s.created_at,
                resolved_at=s.resolved_at,
            )
            for s in results
        ],
        total=total,
    )


class ArchiveResponse(BaseModel):
    archived: int
    run_id: str


@router.post("/archive", response_model=ArchiveResponse)
async def archive_signals(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import uuid
    from datetime import datetime, timezone
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    count = await archive_signals_async(db, user_id=user.id, run_id=run_id)
    return ArchiveResponse(archived=count, run_id=run_id)


class ArchiveListResponse(BaseModel):
    items: list[SignalResponse]
    total: int
    run_ids: list[str]


@router.get("/archive", response_model=ArchiveListResponse)
async def list_archived_signals(
    run_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(ArchivedSignal).where(ArchivedSignal.user_id == user.id)
    count_stmt = select(func.count()).select_from(ArchivedSignal).where(ArchivedSignal.user_id == user.id)

    if run_id:
        stmt = stmt.where(ArchivedSignal.run_id == run_id)
        count_stmt = count_stmt.where(ArchivedSignal.run_id == run_id)

    total = (await db.execute(count_stmt)).scalar()
    results = (await db.execute(
        stmt.order_by(desc(ArchivedSignal.created_at)).limit(limit).offset(offset)
    )).scalars().all()

    run_ids_result = (await db.execute(
        select(ArchivedSignal.run_id)
        .where(ArchivedSignal.user_id == user.id)
        .distinct()
        .order_by(desc(ArchivedSignal.run_id))
    )).scalars().all()

    return ArchiveListResponse(
        items=[
            SignalResponse(
                id=s.original_id, ticker=s.ticker, side=s.side, action=s.action,
                limit_price_cents=s.limit_price_cents, quantity=s.quantity,
                cost_cents=s.cost_cents, signal_type=s.signal_type, status=s.status,
                model_prob=s.model_prob, model_fair_cents=s.model_fair_cents,
                model_edge_cents=s.model_edge_cents, edge_tier=s.edge_tier,
                implied_vol=s.implied_vol,
                market_yes_price_cents=s.market_yes_price_cents,
                spot_price=s.spot_price, strike_price=s.strike_price,
                kalshi_order_id=s.kalshi_order_id, fill_price_cents=s.fill_price_cents,
                exit_price_cents=s.exit_price_cents, filled_at=s.filled_at,
                pnl_cents=s.pnl_cents, settled_side=s.settled_side,
                close_time=s.close_time, created_at=s.created_at,
                resolved_at=s.resolved_at,
            )
            for s in results
        ],
        total=total,
        run_ids=run_ids_result,
    )
