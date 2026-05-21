from pydantic import BaseModel

from app.schemas.signal import SignalResponse
from app.schemas.spot import SpotPnLStats


class BotStatusResponse(BaseModel):
    mode: str
    enabled: bool
    has_kalshi_keys: bool
    has_coinbase_keys: bool = False
    spot_enabled: bool = False
    spot_mode: str = "paper"
    spot_dip_pct: float = 3.0
    spot_take_profit_pct: float = 2.0
    spot_stop_loss_pct: float = 5.0
    max_exposure_cents: int
    current_exposure_cents: int
    exposure_remaining_cents: int
    daily_budget_cents: int
    daily_spent_cents: int
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
    unrealized_pnl_cents: int = 0
    open_positions: int = 0


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


class DailyPnLPoint(BaseModel):
    date: str
    pnl_cents: int
    cumulative_pnl_cents: int
    signals_count: int
    wins: int
    losses: int


class PnLChartResponse(BaseModel):
    daily: list[DailyPnLPoint]
    total_pnl_cents: int
    best_day_cents: int
    worst_day_cents: int
    winning_days: int
    losing_days: int


class DashboardResponse(BaseModel):
    bot_status: BotStatusResponse
    recent_signals: list[SignalResponse]
    opportunities: list[OpportunitySummary]
    stats: PaperPnLStats
    spot_stats: SpotPnLStats | None = None
