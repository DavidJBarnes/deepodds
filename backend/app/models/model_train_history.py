import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModelTrainHistory(Base):
    __tablename__ = "model_train_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=True
    )
    model_type: Mapped[str] = mapped_column(String(20))
    crypto_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    climate_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    crypto_size_kb: Mapped[float | None] = mapped_column(Float, nullable=True)
    climate_size_kb: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_size_kb: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
