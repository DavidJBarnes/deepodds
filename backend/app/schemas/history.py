from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HistoryCreate(BaseModel):
    text: str


class HistoryResponse(BaseModel):
    id: UUID
    user_id: UUID
    text: str
    created_at: datetime


class HistoryListResponse(BaseModel):
    items: list[HistoryResponse]
    total: int
