import redis
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.spot_position import SpotPosition
from app.models.spot_trade import SpotTrade
from app.models.user import User
from app.schemas.spot import SpotPnLStats, SpotPositionResponse, SpotPriceResponse, SpotTradeResponse

router = APIRouter(prefix="/spot", tags=["spot"])


def _get_redis():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/price", response_model=SpotPriceResponse)
async def get_spot_price():
    r = _get_redis()
    price_str = r.get("spot:btc:price")
    high_1h_str = r.get("spot:btc:high_1h")
    high_4h_str = r.get("spot:btc:high_4h")
    updated_str = r.get("spot:btc:updated")
    price = float(price_str) if price_str else None
    high_1h = float(high_1h_str) if high_1h_str else None
    high_4h = float(high_4h_str) if high_4h_str else None
    dip_1h = ((high_1h - price) / high_1h * 100) if price and high_1h and high_1h > 0 else None
    dip_4h = ((high_4h - price) / high_4h * 100) if price and high_4h and high_4h > 0 else None
    return SpotPriceResponse(
        price=price, high_1h=high_1h, high_4h=high_4h,
        dip_pct=round(dip_1h, 2) if dip_1h else None,
        dip_pct_4h=round(dip_4h, 2) if dip_4h else None,
        updated=float(updated_str) if updated_str else None,
    )


@router.get("/price/stream")
async def stream_spot_price(user: User = Depends(get_current_user)):
    import asyncio
    import json

    async def event_generator():
        r = _get_redis()
        last_price = None
        while True:
            price_str = r.get("spot:btc:price")
            high_1h_str = r.get("spot:btc:high_1h")
            high_4h_str = r.get("spot:btc:high_4h")
            price = float(price_str) if price_str else None
            if price and price != last_price:
                high_1h = float(high_1h_str) if high_1h_str else None
                high_4h = float(high_4h_str) if high_4h_str else None
                dip = ((high_1h - price) / high_1h * 100) if high_1h and high_1h > 0 else None
                dip_4h = ((high_4h - price) / high_4h * 100) if high_4h and high_4h > 0 else None
                last_price = price
                yield {
                    "event": "price",
                    "data": json.dumps({
                        "price": price,
                        "high_1h": high_1h,
                        "high_4h": high_4h,
                        "dip_pct": round(dip, 2) if dip else None,
                        "dip_pct_4h": round(dip_4h, 2) if dip_4h else None,
                    }),
                }
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())


@router.get("/trades", response_model=list[SpotTradeResponse])
async def get_spot_trades(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trades = (await db.execute(
        select(SpotTrade)
        .where(SpotTrade.user_id == user.id)
        .order_by(SpotTrade.created_at.desc())
        .limit(50)
    )).scalars().all()
    return [
        SpotTradeResponse(
            id=str(t.id), side=t.side, price_usd=t.price_usd,
            quantity_btc=t.quantity_btc, amount_usd=t.amount_usd,
            trigger=t.trigger, status=t.status,
            coinbase_order_id=t.coinbase_order_id, pnl_usd=t.pnl_usd,
            created_at=t.created_at.isoformat(),
        )
        for t in trades
    ]


@router.get("/position", response_model=SpotPositionResponse | None)
async def get_spot_position(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pos = (await db.execute(
        select(SpotPosition).where(
            SpotPosition.user_id == user.id,
            SpotPosition.status == "open",
        )
    )).scalar_one_or_none()
    if not pos:
        return None

    r = _get_redis()
    price_str = r.get("spot:btc:price")
    unrealized = None
    if price_str:
        current = float(price_str)
        unrealized = round((current - pos.entry_price_usd) * pos.quantity_btc, 2)

    return SpotPositionResponse(
        id=str(pos.id), entry_price_usd=pos.entry_price_usd,
        quantity_btc=pos.quantity_btc, cost_basis_usd=pos.cost_basis_usd,
        status=pos.status, unrealized_pnl_usd=unrealized,
        opened_at=pos.opened_at.isoformat(),
        closed_at=pos.closed_at.isoformat() if pos.closed_at else None,
    )


@router.get("/stats", response_model=SpotPnLStats)
async def get_spot_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    total_trades = (await db.execute(
        select(func.count()).select_from(SpotTrade).where(SpotTrade.user_id == user.id)
    )).scalar()

    realized_pnl = (await db.execute(
        select(func.coalesce(func.sum(SpotTrade.pnl_usd), 0.0))
        .where(SpotTrade.user_id == user.id, SpotTrade.pnl_usd.isnot(None))
    )).scalar()

    pos = (await db.execute(
        select(SpotPosition).where(
            SpotPosition.user_id == user.id,
            SpotPosition.status == "open",
        )
    )).scalar_one_or_none()

    open_btc = pos.quantity_btc if pos else 0.0
    open_usd = pos.cost_basis_usd if pos else 0.0
    unrealized = 0.0
    if pos:
        r = _get_redis()
        price_str = r.get("spot:btc:price")
        if price_str:
            unrealized = round((float(price_str) - pos.entry_price_usd) * pos.quantity_btc, 2)

    return SpotPnLStats(
        total_trades=total_trades,
        open_position_btc=round(open_btc, 8),
        open_position_usd=round(open_usd, 2),
        unrealized_pnl_usd=unrealized,
        realized_pnl_usd=round(realized_pnl, 2),
    )
