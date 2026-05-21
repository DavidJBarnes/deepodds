from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SignalResponse(BaseModel):
    id: UUID
    ticker: str
    side: str
    action: str
    limit_price_cents: int
    quantity: int
    cost_cents: int
    signal_type: str
    status: str
    model_prob: float | None = None
    model_fair_cents: float | None = None
    model_edge_cents: float | None = None
    edge_tier: str | None = None
    implied_vol: float | None = None
    market_yes_price_cents: float | None = None
    spot_price: float | None = None
    strike_price: float | None = None
    cap_strike: float | None = None
    kalshi_order_id: str | None = None
    fill_price_cents: int | None = None
    exit_price_cents: int | None = None
    filled_at: datetime | None = None
    unrealized_pnl_cents: int | None = None
    pnl_cents: int | None = None
    settled_side: str | None = None
    close_time: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    total: int
