from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.signal import Signal
from app.models.user import User
from app.schemas.signal import SignalListResponse, SignalResponse

VALID_STATUSES = {"signaled", "placed", "filled", "settled_win", "settled_loss", "settled_breakeven", "cancelled"}

router = APIRouter(prefix="/signals", tags=["signals"])


def _signal_response(s) -> SignalResponse:
    return SignalResponse(
        id=getattr(s, "original_id", s.id),
        venue=getattr(s, "venue", "kalshi") or "kalshi",
        pair=s.pair,
        side=s.side,
        signal_type=s.signal_type,
        status=s.status,
        entry_price=s.entry_price,
        quantity=s.quantity,
        cost_usd=s.cost_usd,
        model_prob=getattr(s, "model_prob", None),
        market_prob=getattr(s, "market_prob", None),
        edge=getattr(s, "edge", None),
        floor_strike=getattr(s, "floor_strike", None),
        cap_strike=getattr(s, "cap_strike", None),
        strike_type=getattr(s, "strike_type", None),
        underlying_price=getattr(s, "underlying_price", None),
        realized_vol=getattr(s, "realized_vol", None),
        exchange_order_id=s.exchange_order_id,
        fill_price=s.fill_price,
        fill_quantity=s.fill_quantity,
        filled_at=s.filled_at,
        exit_price=s.exit_price,
        pnl_usd=s.pnl_usd,
        pnl_pct=s.pnl_pct,
        market_ticker=getattr(s, "market_ticker", None),
        event_ticker=getattr(s, "event_ticker", None),
        expiry_time=getattr(s, "expiry_time", None),
        created_at=s.created_at,
        resolved_at=s.resolved_at,
    )


@router.get("", response_model=SignalListResponse)
async def list_signals(
    statuses: str | None = Query(None, description="Comma-separated status values"),
    status: str | None = Query(None, deprecated="Use statuses instead"),
    date: date_type | None = Query(None),
    tz_offset: int | None = Query(None, description="Minutes from UTC (JS getTimezoneOffset convention)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Signal).where(Signal.user_id == user.id)
    count_stmt = select(func.count()).select_from(Signal).where(Signal.user_id == user.id)

    raw_statuses = statuses.split(",") if statuses else ([status] if status else None)
    if raw_statuses:
        invalid = set(raw_statuses) - VALID_STATUSES
        if invalid:
            raise HTTPException(400, f"Invalid status values: {', '.join(sorted(invalid))}")
        stmt = stmt.where(Signal.status.in_(raw_statuses))
        count_stmt = count_stmt.where(Signal.status.in_(raw_statuses))

    if date:
        start = datetime(date.year, date.month, date.day, tzinfo=timezone.utc)
        if tz_offset is not None:
            start += timedelta(minutes=tz_offset)
        end = start + timedelta(days=1)
        stmt = stmt.where(Signal.created_at >= start, Signal.created_at < end)
        count_stmt = count_stmt.where(Signal.created_at >= start, Signal.created_at < end)

    total = (await db.execute(count_stmt)).scalar()
    results = (
        await db.execute(stmt.order_by(desc(Signal.created_at)).limit(limit).offset(offset))
    ).scalars().all()

    return SignalListResponse(
        items=[_signal_response(s) for s in results],
        total=total,
    )

