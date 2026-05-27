import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.archived_signal import ArchivedSignal
from app.models.signal import Signal

SIGNAL_FIELDS = [
    "user_id", "venue", "pair", "side", "signal_type", "status",
    "market_ticker", "event_ticker", "expiry_time",
    "entry_price", "quantity", "cost_usd",
    "exchange_order_id", "fill_price", "fill_quantity", "filled_at",
    "model_prob", "market_prob", "edge",
    "floor_strike", "cap_strike", "strike_type",
    "underlying_price", "realized_vol",
    "exit_price", "pnl_usd", "pnl_pct",
    "error_message", "resolved_at", "created_at", "updated_at",
]


def archive_signals_sync(session: Session, user_id=None, run_id: str | None = None) -> int:
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
