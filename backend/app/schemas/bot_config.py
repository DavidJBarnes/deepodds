from pydantic import BaseModel, Field


class BotConfigResponse(BaseModel):
    mode: str
    enabled: bool
    daily_budget_cents: int
    min_edge_cents: float
    min_liquidity: float
    max_position_cents: int
    max_contracts_per_signal: int


class BotConfigUpdate(BaseModel):
    mode: str | None = None
    enabled: bool | None = None
    daily_budget_cents: int | None = Field(None, ge=100, le=100000)
    min_edge_cents: float | None = Field(None, ge=1, le=50)
    min_liquidity: float | None = Field(None, ge=0)
    max_position_cents: int | None = Field(None, ge=100, le=10000)
    max_contracts_per_signal: int | None = Field(None, ge=1, le=100)
