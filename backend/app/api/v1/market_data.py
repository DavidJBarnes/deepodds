"""Lightweight market snapshots and scanner health API.

These endpoints replace the heavy market-scanning logic previously
embedded in the dashboard endpoint.  They read pre-computed data
written by the scanner subprocess.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.market_snapshot import MarketSnapshot
from app.models.scanner_heartbeat import ScannerHeartbeat
from app.models.user import User
from app.schemas.dashboard import KalshiFilteredMarket, KalshiMarketSnapshot

router = APIRouter(tags=["market-data"])


@router.get("/market-snapshots")
async def get_market_snapshots(
    venue: str = Query("all", pattern="^(all|kalshi_crypto|kalshi_climate)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return pre-computed market snapshots from the scanner."""
    q = select(MarketSnapshot).where(
        MarketSnapshot.filter_reason.is_(None),
        MarketSnapshot.edge.is_not(None),
    )
    if venue != "all":
        q = q.where(MarketSnapshot.venue == venue)
    q = q.order_by(MarketSnapshot.edge.desc()).limit(200)

    rows = (await db.execute(q)).scalars().all()

    snapshots = []
    for r in rows:
        snapshots.append(KalshiMarketSnapshot(
            ticker=r.ticker,
            series=r.series,
            title=r.title or "",
            price=round(r.ask_price, 2),
            model_prob=round(r.model_prob, 4) if r.model_prob else 0.0,
            edge=round(r.edge, 4) if r.edge else 0.0,
            floor_strike=r.floor_strike,
            cap_strike=r.cap_strike,
            strike_type=r.strike_type or "between",
            underlying_price=round(r.underlying_price, 2) if r.underlying_price else 0.0,
            realized_vol=round(r.realized_vol, 4) if r.realized_vol else 0.0,
            volume_24h=r.volume_24h or 0,
            hours_to_expiry=round(r.hours_to_expiry, 1) if r.hours_to_expiry else 0,
            expiry_time=r.expiry_time,
            would_signal=False,
        ))

    return snapshots


@router.get("/scanner-health")
async def get_scanner_health(
    db: AsyncSession = Depends(get_db),
):
    """Return scanner liveness status from the heartbeat table."""
    hb = (await db.execute(
        select(ScannerHeartbeat).where(ScannerHeartbeat.id == 1)
    )).scalar_one_or_none()

    if hb is None:
        return {
            "status": "offline",
            "last_beat": None,
            "error": None,
        }

    now = datetime.now(timezone.utc)
    age = (now - hb.last_beat).total_seconds()

    if age > 120:
        status = "offline"
    elif age > 60:
        status = "degraded"
    elif hb.status == "warming_up":
        status = "warming_up"
    else:
        status = "online"

    return {
        "status": status,
        "last_beat": hb.last_beat.isoformat(),
        "error": hb.error,
    }
