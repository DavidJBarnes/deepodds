from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SignalResponse(BaseModel):
    id: UUID
    pair: str
    side: str
    signal_type: str
    status: str
    entry_price: float
    quantity: float
    cost_usd: float
    z_score: float | None = None
    vwap: float | None = None
    exchange_order_id: str | None = None
    fill_price: float | None = None
    fill_quantity: float | None = None
    filled_at: datetime | None = None
    exit_price: float | None = None
    exit_z_score: float | None = None
    pnl_usd: float | None = None
    pnl_pct: float | None = None
    unrealized_pnl_usd: float | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    total: int
