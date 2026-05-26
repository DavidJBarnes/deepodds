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
    min_z_24h: float = 0.0
    z_distance: float = 0.0
    effective_entry_z: float = -2.0


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
    model_prob: float
    edge: float
    floor_strike: float | None = None
    cap_strike: float | None = None
    strike_type: str = "between"
    underlying_price: float = 0.0
    realized_vol: float = 0.0
    volume_24h: float
    hours_to_expiry: float
    would_signal: bool


class KalshiFilteredMarket(BaseModel):
    ticker: str
    series: str
    title: str
    price: float
    volume_24h: float
    hours_to_expiry: float | None = None
    filter_reason: str


class KalshiStatusResponse(BaseModel):
    mode: str
    enabled: bool
    has_keys: bool
    series_tickers: str
    open_positions: int
    max_open_positions: int
    min_edge: float
    exit_edge: float
    current_exposure_usd: float = 0.0
    max_payout_usd: float = 0.0


class DashboardResponse(BaseModel):
    bot_status: BotStatusResponse
    kalshi_status: KalshiStatusResponse | None = None
    recent_signals: list[SignalResponse]
    markets: list[MarketSnapshot]
    kalshi_markets: list[KalshiMarketSnapshot] = []
    kalshi_filtered: list[KalshiFilteredMarket] = []
    stats: PnLStats
    scanner_health: dict | None = None
