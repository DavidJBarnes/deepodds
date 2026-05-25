from pydantic import BaseModel, Field


class KalshiConfigResponse(BaseModel):
    mode: str
    enabled: bool
    series_tickers: str = "KXBTC,KXETH"
    min_volume_24h: int = 100
    min_price: float = 0.15
    max_price: float = 0.85
    min_hours_to_expiry: int = 4
    candle_interval: int = 1
    lookback_periods: int = 60
    entry_z_score: float = -2.5
    exit_z_score: float = -0.3
    contracts_per_signal: int = 50
    max_open_positions: int = 5
    stop_loss_pct: float = 15.0
    daily_loss_limit_usd: float = 25.0
    max_signals_per_hour: int = 3


class KalshiConfigUpdate(BaseModel):
    mode: str | None = None
    enabled: bool | None = None
    series_tickers: str | None = None
    min_volume_24h: int | None = Field(None, ge=0, le=100000)
    min_price: float | None = Field(None, ge=0.01, le=0.50)
    max_price: float | None = Field(None, ge=0.50, le=0.99)
    min_hours_to_expiry: int | None = Field(None, ge=1, le=48)
    candle_interval: int | None = Field(None)
    lookback_periods: int | None = Field(None, ge=10, le=200)
    entry_z_score: float | None = Field(None, ge=-5.0, le=-0.5)
    exit_z_score: float | None = Field(None, ge=-1.0, le=3.0)
    contracts_per_signal: int | None = Field(None, ge=1, le=10000)
    max_open_positions: int | None = Field(None, ge=1, le=20)
    stop_loss_pct: float | None = Field(None, ge=1.0, le=50.0)
    daily_loss_limit_usd: float | None = Field(None, ge=0, le=10000.0)
    max_signals_per_hour: int | None = Field(None, ge=0, le=20)


class KalshiKeysUpdate(BaseModel):
    api_key_id: str
    private_key_pem: str


class KalshiKeysStatus(BaseModel):
    has_keys: bool
    key_preview: str | None = None
    valid: bool = False
