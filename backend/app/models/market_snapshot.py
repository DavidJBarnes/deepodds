from datetime import datetime

from sqlalchemy import DateTime, Double, Float, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    series: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    ask_price: Mapped[float] = mapped_column(Double, nullable=False)
    ask_size: Mapped[float | None] = mapped_column(Double)
    bid_price: Mapped[float | None] = mapped_column(Double)
    mid_price: Mapped[float | None] = mapped_column(Double)
    spread_pct: Mapped[float | None] = mapped_column(Double)
    volume_24h: Mapped[float | None] = mapped_column(Double)
    hours_to_expiry: Mapped[float | None] = mapped_column(Float)
    expiry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    floor_strike: Mapped[float | None] = mapped_column(Double)
    cap_strike: Mapped[float | None] = mapped_column(Double)
    strike_type: Mapped[str] = mapped_column(Text, default="between")
    underlying_price: Mapped[float | None] = mapped_column(Double)
    realized_vol: Mapped[float | None] = mapped_column(Double)
    model_prob: Mapped[float | None] = mapped_column(Double)
    edge: Mapped[float | None] = mapped_column(Double)
    filter_reason: Mapped[str | None] = mapped_column(Text)
    # Settlement state, populated by discover.py from the Kalshi market dict.
    # Lets the exit loop decide a position's final outcome without a per-ticker
    # API call. status is "open"/"closed"/"settled"/"finalized"; result is
    # "yes"/"no"/None.
    status: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    last_price: Mapped[float | None] = mapped_column(Double)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
