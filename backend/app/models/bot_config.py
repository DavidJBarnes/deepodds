import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BotConfig(Base):
    __tablename__ = "bot_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_exposure_cents: Mapped[int] = mapped_column(Integer, default=5000)
    daily_budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    min_edge_cents: Mapped[float] = mapped_column(Float, default=8.0)
    min_liquidity: Mapped[float] = mapped_column(Float, default=10.0)
    max_position_cents: Mapped[int] = mapped_column(Integer, default=500)
    max_contracts_per_signal: Mapped[int] = mapped_column(Integer, default=10)
    max_position_cents_moderate: Mapped[int] = mapped_column(Integer, default=750)
    max_contracts_moderate: Mapped[int] = mapped_column(Integer, default=15)
    max_position_cents_high: Mapped[int] = mapped_column(Integer, default=1000)
    max_contracts_high: Mapped[int] = mapped_column(Integer, default=20)
    max_position_cents_elite: Mapped[int] = mapped_column(Integer, default=2000)
    max_contracts_elite: Mapped[int] = mapped_column(Integer, default=30)
    take_profit_cents: Mapped[int] = mapped_column(Integer, default=15)
    stop_loss_cents: Mapped[int] = mapped_column(Integer, default=10)
    daily_loss_limit_cents: Mapped[int] = mapped_column(Integer, default=2000)
    max_signals_per_hour: Mapped[int] = mapped_column(Integer, default=5)
    tier_budget_pct_elite: Mapped[int] = mapped_column(Integer, default=30)
    tier_budget_pct_high: Mapped[int] = mapped_column(Integer, default=20)
    max_positions_per_asset: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
