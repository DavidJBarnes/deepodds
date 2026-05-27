from pydantic import BaseModel, Field


class PairConfigResponse(BaseModel):
    venue: str
    pair: str
    contracts_per_signal: int | None = None
    stop_loss_pct: float | None = None
    min_edge: float | None = None
    exit_edge: float | None = None


class PairConfigUpdate(BaseModel):
    contracts_per_signal: int | None = Field(None, ge=1, le=10000)
    stop_loss_pct: float | None = Field(None, ge=0.5, le=50.0)
    min_edge: float | None = Field(None, ge=0.01, le=0.50)
    exit_edge: float | None = Field(None, ge=-0.50, le=0.0)
