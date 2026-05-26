from pydantic import BaseModel, Field


class KalshiConfigResponse(BaseModel):
    mode: str
    enabled: bool
    series_tickers: str = "KXBTC,KXETH"
    min_volume_24h: int = 0
    min_price: float = 0.01
    max_price: float = 0.95
    min_hours_to_expiry: int = 2
    min_edge: float = 0.05
    vol_lookback_hours: int = 24
    vol_interval: str = "15m"
    exit_edge: float = -0.02
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
    min_price: float | None = Field(None, ge=0.0, le=0.50)
    max_price: float | None = Field(None, ge=0.50, le=0.99)
    min_hours_to_expiry: int | None = Field(None, ge=0, le=48)
    min_edge: float | None = Field(None, ge=0.01, le=0.50)
    vol_lookback_hours: int | None = Field(None, ge=1, le=168)
    vol_interval: str | None = None
    exit_edge: float | None = Field(None, ge=-0.50, le=0.0)
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
