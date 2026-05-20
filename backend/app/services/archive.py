import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.archived_signal import ArchivedSignal
from app.models.signal import Signal


SIGNAL_FIELDS = [
    "user_id", "opportunity_id", "ticker", "side", "action",
    "limit_price_cents", "quantity", "cost_cents", "signal_type", "status",
    "model_prob", "model_fair_cents", "model_edge_cents", "edge_tier",
    "implied_vol", "market_yes_price_cents", "spot_price", "strike_price",
    "cap_strike", "kalshi_order_id", "fill_price_cents", "fill_quantity",
    "exit_price_cents", "error_message", "filled_at", "settled_side",
    "pnl_cents", "close_time", "resolved_at", "created_at", "updated_at",
]


def archive_signals_sync(session: Session, user_id=None, run_id: str | None = None) -> int:
    """Move signals to archive table. Returns count archived."""
    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]

    stmt = select(Signal)
    if user_id is not None:
        stmt = stmt.where(Signal.user_id == user_id)

    signals = session.execute(stmt).scalars().all()
    if not signals:
        return 0

    now = datetime.now(timezone.utc)
    for sig in signals:
        archived = ArchivedSignal(
            original_id=sig.id,
            run_id=run_id,
            archived_at=now,
            **{f: getattr(sig, f) for f in SIGNAL_FIELDS},
        )
        session.add(archived)
        session.delete(sig)

    session.commit()
    return len(signals)


async def archive_signals_async(db: AsyncSession, user_id=None, run_id: str | None = None) -> int:
    """Async version for use in API endpoints."""
    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]

    stmt = select(Signal)
    if user_id is not None:
        stmt = stmt.where(Signal.user_id == user_id)

    result = await db.execute(stmt)
    signals = result.scalars().all()
    if not signals:
        return 0

    now = datetime.now(timezone.utc)
    for sig in signals:
        archived = ArchivedSignal(
            original_id=sig.id,
            run_id=run_id,
            archived_at=now,
            **{f: getattr(sig, f) for f in SIGNAL_FIELDS},
        )
        db.add(archived)
        await db.delete(sig)

    await db.commit()
    return len(signals)
