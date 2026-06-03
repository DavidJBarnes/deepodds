from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScannerHeartbeat(Base):
    __tablename__ = "scanner_heartbeat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_beat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(Text, default="warming_up")
    error: Mapped[str | None] = mapped_column(Text)
