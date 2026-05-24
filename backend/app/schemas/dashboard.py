from pydantic import BaseModel

from app.schemas.signal import SignalResponse


class BotStatusResponse(BaseModel):
    mode: str
    enabled: bool
    has_exchange_keys: bool
    exchange_keys_valid: bool = False
    pairs: str
    open_positions: int
    max_open_positions: int
    entry_z_score: float
    exit_z_score: float
    stop_loss_pct: float


class PnLStats(BaseModel):
    total_signals: int
    settled_count: int
    wins: int
    losses: int
    win_rate: float
    total_pnl_usd: float
    total_cost_usd: float
    roi_pct: float
    unrealized_pnl_usd: float = 0.0
    open_positions: int = 0


class MarketSnapshot(BaseModel):
    pair: str
    price: float
    vwap: float
    z_score: float
    std_dev: float
    would_signal: bool


class DailyPnLPoint(BaseModel):
    date: str
    pnl_usd: float
    cumulative_pnl_usd: float
    signals_count: int
    wins: int
    losses: int


class PnLChartResponse(BaseModel):
    daily: list[DailyPnLPoint]
    total_pnl_usd: float
    best_day_usd: float
    worst_day_usd: float
    winning_days: int
    losing_days: int


class KalshiMarketSnapshot(BaseModel):
    ticker: str
    series: str
    title: str
    price: float
    vwap: float
    z_score: float
    std_dev: float
    volume_24h: float
    hours_to_expiry: float
    would_signal: bool


class KalshiStatusResponse(BaseModel):
    enabled: bool
    has_keys: bool
    series_tickers: str
    open_positions: int
    max_open_positions: int
    entry_z_score: float
    exit_z_score: float


class DashboardResponse(BaseModel):
    bot_status: BotStatusResponse
    kalshi_status: KalshiStatusResponse | None = None
    recent_signals: list[SignalResponse]
    markets: list[MarketSnapshot]
    kalshi_markets: list[KalshiMarketSnapshot] = []
    stats: PnLStats
    scanner_health: dict | None = None
