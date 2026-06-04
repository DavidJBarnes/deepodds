from pydantic import BaseModel, Field


class ClimateConfigResponse(BaseModel):
    mode: str
    enabled: bool
    series_tickers: str = "KXHIGHTSFO,KXHIGHTATL,KXHIGHTNOLA,KXHIGHTPHX,KXLOWTNYC,KXLOWTCHI"
    min_volume_24h: int = 20
    min_price: float = 0.05
    max_price: float = 0.80
    min_hours_to_expiry: int = 2
    min_edge: float = 0.08
    exit_edge: float = -0.02
    contracts_per_signal: int = 25
    max_cost_per_signal: float = 15.0
    max_open_positions: int = 5
    max_positions_per_event: int = 1
    stop_loss_pct: float = 15.0
    take_profit_pct: float = 25.0
    daily_loss_limit_usd: float = 15.0
    max_signals_per_hour: int = 3
    min_hold_minutes: int = 15
    low_balance_warning_threshold_usd: float = 20.0


class ClimateConfigUpdate(BaseModel):
    mode: str | None = None
    enabled: bool | None = None
    series_tickers: str | None = None
    min_volume_24h: int | None = Field(None, ge=0, le=100000)
    min_price: float | None = Field(None, ge=0.0, le=0.50)
    max_price: float | None = Field(None, ge=0.50, le=0.99)
    min_hours_to_expiry: int | None = Field(None, ge=0, le=48)
    min_edge: float | None = Field(None, ge=0.01, le=0.50)
    exit_edge: float | None = Field(None, ge=-0.50, le=0.0)
    contracts_per_signal: int | None = Field(None, ge=1, le=10000)
    max_cost_per_signal: float | None = Field(None, ge=1.0, le=1000.0)
    max_open_positions: int | None = Field(None, ge=1, le=100)
    max_positions_per_event: int | None = Field(None, ge=1, le=20)
    stop_loss_pct: float | None = Field(None, ge=0.0, le=50.0)
    take_profit_pct: float | None = Field(None, ge=0.0, le=500.0)
    daily_loss_limit_usd: float | None = Field(None, ge=0, le=10000.0)
    max_signals_per_hour: int | None = Field(None, ge=0, le=20)
    min_hold_minutes: int | None = Field(None, ge=0, le=480)
    low_balance_warning_threshold_usd: float | None = Field(None, ge=0.0, le=10000.0)
