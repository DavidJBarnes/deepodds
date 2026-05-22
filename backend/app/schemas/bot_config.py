from pydantic import BaseModel, Field


class BotConfigResponse(BaseModel):
    mode: str
    enabled: bool
    pairs: str = "BTC-USD,ETH-USD"
    lookback_periods: int = 16
    entry_z_score: float = -2.0
    exit_z_score: float = 0.0
    position_size_usd: float = 25.0
    max_open_positions: int = 3
    stop_loss_pct: float = 3.0
    daily_loss_limit_usd: float = 50.0
    max_signals_per_hour: int = 5


class BotConfigUpdate(BaseModel):
    mode: str | None = None
    enabled: bool | None = None
    pairs: str | None = None
    lookback_periods: int | None = Field(None, ge=4, le=96)
    entry_z_score: float | None = Field(None, ge=-5.0, le=-0.5)
    exit_z_score: float | None = Field(None, ge=-1.0, le=3.0)
    position_size_usd: float | None = Field(None, ge=5.0, le=1000.0)
    max_open_positions: int | None = Field(None, ge=1, le=10)
    stop_loss_pct: float | None = Field(None, ge=0.5, le=20.0)
    daily_loss_limit_usd: float | None = Field(None, ge=0, le=10000.0)
    max_signals_per_hour: int | None = Field(None, ge=0, le=20)
