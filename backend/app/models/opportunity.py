import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_ticker: Mapped[str] = mapped_column(String(64), index=True)
    ticker: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="Crypto")
    asset: Mapped[str] = mapped_column(String(16), index=True)
    strike_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    strike_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    spot_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    yes_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    yes_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    edge_direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quality: Mapped[str] = mapped_column(String(16), default="low")
    volume: Mapped[float] = mapped_column(Float, default=0)
    volume_24h: Mapped[float] = mapped_column(Float, default=0)
    open_interest: Mapped[float] = mapped_column(Float, default=0)
    liquidity: Mapped[float] = mapped_column(Float, default=0)
    close_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_contracts: Mapped[int] = mapped_column(Integer, default=0)
    active_contracts: Mapped[int] = mapped_column(Integer, default=0)
    market_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_fair_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_edge_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    fear_greed_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fear_greed_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
