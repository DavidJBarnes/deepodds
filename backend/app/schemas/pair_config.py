from pydantic import BaseModel, Field


class PairConfigResponse(BaseModel):
    venue: str
    pair: str
    entry_z_score: float | None = None
    exit_z_score: float | None = None
    position_size_usd: float | None = None
    contracts_per_signal: int | None = None
    stop_loss_pct: float | None = None
    min_edge: float | None = None
    exit_edge: float | None = None


class PairConfigUpdate(BaseModel):
    entry_z_score: float | None = Field(None, ge=-5.0, le=-0.5)
    exit_z_score: float | None = Field(None, ge=-1.0, le=3.0)
    position_size_usd: float | None = Field(None, ge=5.0, le=1000.0)
    contracts_per_signal: int | None = Field(None, ge=1, le=10000)
    stop_loss_pct: float | None = Field(None, ge=0.5, le=50.0)
    min_edge: float | None = Field(None, ge=0.01, le=0.50)
    exit_edge: float | None = Field(None, ge=-0.50, le=0.0)
