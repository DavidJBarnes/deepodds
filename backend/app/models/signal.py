import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True)
    ticker: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    action: Mapped[str] = mapped_column(String(8), default="buy")
    limit_price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    cost_cents: Mapped[int] = mapped_column(Integer)
    signal_type: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="signaled", index=True)

    model_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_fair_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_edge_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_tier: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    implied_vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_yes_price_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    spot_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    strike_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_strike: Mapped[float | None] = mapped_column(Float, nullable=True)

    kalshi_order_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    fill_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fill_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    settled_side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pnl_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    close_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
