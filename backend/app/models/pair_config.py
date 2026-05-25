import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PairConfig(Base):
    __tablename__ = "pair_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "venue", "pair", name="uq_pair_config_user_venue_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    venue: Mapped[str] = mapped_column(String(16))
    pair: Mapped[str] = mapped_column(String(64))

    entry_z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_size_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracts_per_signal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
