"""Retention pruning for the Verbatim tables.

`transcript_chunks` grows continuously while a stream is live — roughly one row
every 4 seconds per stream — and the standalone project configured
`TRANSCRIPT_CHUNK_RETENTION_HOURS` but **never implemented anything that reads
it**. On a 20GB db.t4g.micro shared with the trading database, that is unbounded
growth against storage the trading system also depends on.

Deletes are chunked rather than issued as one big statement: a single
`DELETE FROM transcript_chunks WHERE ts < …` over days of backlog takes a long
lock on an instance that is also serving live order-placement queries.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verbatim import OrderbookDelta, TranscriptChunk

logger = logging.getLogger("app.verbatim.retention")

# Rows per statement. Small enough that each lock is brief.
_BATCH = 5_000


async def _prune_batched(session: AsyncSession, model, ts_column, cutoff: datetime,
                         extra_where=None) -> int:
    """Delete rows older than `cutoff` in bounded batches. Returns rows removed."""
    removed = 0
    while True:
        stmt = select(model.id).where(ts_column < cutoff)
        if extra_where is not None:
            stmt = stmt.where(extra_where)
        ids = (await session.execute(stmt.limit(_BATCH))).scalars().all()
        if not ids:
            break
        await session.execute(delete(model).where(model.id.in_(ids)))
        await session.commit()
        removed += len(ids)
        if len(ids) < _BATCH:
            break
    return removed


async def prune_transcripts(session: AsyncSession, retention_hours: int,
                            now: datetime | None = None) -> int:
    """Drop transcript chunks older than the retention window."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=retention_hours)
    n = await _prune_batched(
        session, TranscriptChunk, TranscriptChunk.capture_wallclock_utc, cutoff
    )
    if n:
        logger.info("verbatim pruned %d transcript chunk(s) older than %dh", n, retention_hours)
    return n


async def prune_orderbook_deltas(session: AsyncSession, retention_days: int,
                                 now: datetime | None = None) -> int:
    """Drop orderbook deltas older than the window, EXCEPT those flagged
    high-res — those are the evidence behind an edge_seconds measurement and
    outliving the generic window is the whole point of the flag."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    n = await _prune_batched(
        session, OrderbookDelta, OrderbookDelta.ts, cutoff,
        extra_where=OrderbookDelta.high_res_retain.is_(False),
    )
    if n:
        logger.info("verbatim pruned %d orderbook delta(s) older than %dd", n, retention_days)
    return n
