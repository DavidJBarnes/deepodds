from pydantic import BaseModel

from app.schemas.signal import SignalResponse


class BotStatusResponse(BaseModel):
    mode: str
    enabled: bool
    has_kalshi_keys: bool
    daily_budget_cents: int
    daily_spent_cents: int
    daily_remaining_cents: int
    signals_today: int
    active_signals: int


class PaperPnLStats(BaseModel):
    total_signals: int
    settled_count: int
    wins: int
    losses: int
    win_rate: float
    total_pnl_cents: int
    total_cost_cents: int
    roi_pct: float


class OpportunitySummary(BaseModel):
    ticker: str
    asset: str
    title: str
    strike_price: float | None = None
    spot_price: float | None = None
    yes_price: float | None = None
    model_fair_cents: float | None = None
    model_edge_cents: float | None = None
    implied_vol: float | None = None
    liquidity: float = 0
    close_time: str | None = None
    quality: str = "low"


class DashboardResponse(BaseModel):
    bot_status: BotStatusResponse
    recent_signals: list[SignalResponse]
    opportunities: list[OpportunitySummary]
    stats: PaperPnLStats
