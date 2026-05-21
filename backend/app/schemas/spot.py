from pydantic import BaseModel


class SpotTradeResponse(BaseModel):
    id: str
    side: str
    price_usd: float
    quantity_btc: float
    amount_usd: float
    trigger: str
    status: str
    coinbase_order_id: str | None = None
    pnl_usd: float | None = None
    created_at: str


class SpotPositionResponse(BaseModel):
    id: str
    entry_price_usd: float
    quantity_btc: float
    cost_basis_usd: float
    status: str
    unrealized_pnl_usd: float | None = None
    opened_at: str
    closed_at: str | None = None


class SpotPnLStats(BaseModel):
    total_trades: int = 0
    open_position_btc: float = 0.0
    open_position_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0


class SpotPriceResponse(BaseModel):
    price: float | None = None
    high_1h: float | None = None
    high_4h: float | None = None
    dip_pct: float | None = None
    dip_pct_4h: float | None = None
    updated: float | None = None
