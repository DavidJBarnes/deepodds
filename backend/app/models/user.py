import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    # Column names match whichever the DB has — migration renames coinbase→robinhood
    # but we use the old name here so the app works before AND after migration
    robinhood_api_key: Mapped[str | None] = mapped_column(
        "coinbase_api_key", String(256), nullable=True
    )
    robinhood_private_key: Mapped[str | None] = mapped_column(
        "coinbase_private_key", Text, nullable=True
    )
    kalshi_api_key_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    kalshi_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
