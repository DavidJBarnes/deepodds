from pydantic import BaseModel, Field


class BotConfigResponse(BaseModel):
    mode: str
    strategy: str = "model"
    enabled: bool
    max_exposure_cents: int
    daily_budget_cents: int
    min_edge_cents: float
    min_liquidity: float
    max_position_cents: int
    max_contracts_per_signal: int
    max_position_cents_moderate: int
    max_contracts_moderate: int
    max_position_cents_high: int
    max_contracts_high: int
    max_position_cents_elite: int
    max_contracts_elite: int
    take_profit_cents: int
    stop_loss_cents: int
    daily_loss_limit_cents: int
    max_signals_per_hour: int
    tier_budget_pct_elite: int
    tier_budget_pct_high: int
    max_positions_per_asset: int = 3
    min_yes_prob: int = 20


class BotConfigUpdate(BaseModel):
    mode: str | None = None
    strategy: str | None = None
    enabled: bool | None = None
    max_exposure_cents: int | None = Field(None, ge=100, le=100000)
    daily_budget_cents: int | None = Field(None, ge=0, le=100000)
    min_edge_cents: float | None = Field(None, ge=1, le=50)
    min_liquidity: float | None = Field(None, ge=0)
    max_position_cents: int | None = Field(None, ge=100, le=10000)
    max_contracts_per_signal: int | None = Field(None, ge=1, le=100)
    max_position_cents_moderate: int | None = Field(None, ge=100, le=10000)
    max_contracts_moderate: int | None = Field(None, ge=1, le=100)
    max_position_cents_high: int | None = Field(None, ge=100, le=10000)
    max_contracts_high: int | None = Field(None, ge=1, le=100)
    max_position_cents_elite: int | None = Field(None, ge=100, le=50000)
    max_contracts_elite: int | None = Field(None, ge=1, le=200)
    take_profit_cents: int | None = Field(None, ge=0, le=50)
    stop_loss_cents: int | None = Field(None, ge=0, le=50)
    daily_loss_limit_cents: int | None = Field(None, ge=0, le=100000)
    max_signals_per_hour: int | None = Field(None, ge=0, le=50)
    tier_budget_pct_elite: int | None = Field(None, ge=0, le=50)
    tier_budget_pct_high: int | None = Field(None, ge=0, le=50)
    max_positions_per_asset: int | None = Field(None, ge=0, le=20)
    min_yes_prob: int | None = Field(None, ge=0, le=100)
