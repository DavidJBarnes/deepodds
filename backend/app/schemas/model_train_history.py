from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ModelTrainHistoryCreate(BaseModel):
    model_type: str
    crypto_ok: bool | None = None
    climate_ok: bool | None = None
    crypto_size_kb: float | None = None
    climate_size_kb: float | None = None
    total_size_kb: float | None = None
    message: str
    trigger: str
    started_at: datetime


class ModelTrainHistoryResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    model_type: str
    crypto_ok: bool | None
    climate_ok: bool | None
    crypto_size_kb: float | None
    climate_size_kb: float | None
    total_size_kb: float | None
    crypto_model_path: str | None = None
    climate_model_path: str | None = None
    crypto_active: bool = False
    climate_active: bool = False
    crypto_snapshot_exists: bool = False
    climate_snapshot_exists: bool = False
    message: str
    trigger: str
    started_at: datetime
    completed_at: datetime


class ModelTrainHistoryListResponse(BaseModel):
    items: list[ModelTrainHistoryResponse]
    total: int
