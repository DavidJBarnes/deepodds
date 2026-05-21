from pydantic import BaseModel

from app.schemas.signal import SignalResponse


class BotStatusResponse(BaseModel):
    mode: str
    strategy: str = "model"
    enabled: bool
    has_kalshi_keys: bool
    max_exposure_cents: int
    current_exposure_cents: int
    exposure_remaining_cents: int
    daily_budget_cents: int
    daily_spent_cents: int
    signals_today: int
    active_signals: int
    settlement_arb_enabled: bool = False
    settlement_arb_max_minutes: int = 60
    settlement_arb_min_sigma: float = 1.5


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
    cap_strike: float | None = None
    strike_type: str | None = None
    spot_price: float | None = None
    yes_price: float | None = None
    no_price: float | None = None
    yes_ask: float | None = None
    no_ask: float | None = None
    model_prob: float | None = None
    model_fair_cents: float | None = None
    model_edge_cents: float | None = None
    liquidity: float = 0
    close_time: str | None = None


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
