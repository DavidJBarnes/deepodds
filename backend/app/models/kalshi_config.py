import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KalshiConfig(Base):
    __tablename__ = "kalshi_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    series_tickers: Mapped[str] = mapped_column(String(256), default="KXBTC,KXETH")
    min_volume_24h: Mapped[int] = mapped_column(Integer, default=0)
    min_price: Mapped[float] = mapped_column(Float, default=0.01)
    max_price: Mapped[float] = mapped_column(Float, default=0.95)
    min_hours_to_expiry: Mapped[int] = mapped_column(Integer, default=2)

    candle_interval: Mapped[int] = mapped_column(Integer, default=60)
    lookback_periods: Mapped[int] = mapped_column(Integer, default=6)
    entry_z_score: Mapped[float] = mapped_column(Float, default=-2.0)
    exit_z_score: Mapped[float] = mapped_column(Float, default=-0.3)

    contracts_per_signal: Mapped[int] = mapped_column(Integer, default=50)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=5)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=15.0)
    daily_loss_limit_usd: Mapped[float] = mapped_column(Float, default=25.0)
    max_signals_per_hour: Mapped[int] = mapped_column(Integer, default=3)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
