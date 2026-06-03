"""Scanner heartbeat — writes liveness to scanner_heartbeat table."""

import logging
from datetime import datetime, timezone

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models.scanner_heartbeat import ScannerHeartbeat

logger = logging.getLogger("scanner.heartbeat")


def init_heartbeat(engine: Engine) -> None:
    """Ensure the heartbeat row exists with warming_up status."""
    with Session(engine) as session:
        hb = session.execute(
            select(ScannerHeartbeat).where(ScannerHeartbeat.id == 1)
        ).scalar_one_or_none()
        if hb is None:
            session.add(ScannerHeartbeat(id=1, status="warming_up"))
            session.commit()
            logger.info("Heartbeat initialized: warming_up")


def write_heartbeat(session: Session, status: str = "online", error: str | None = None) -> None:
    """Update heartbeat timestamp and status."""
    hb = session.execute(
        select(ScannerHeartbeat).where(ScannerHeartbeat.id == 1)
    ).scalar_one_or_none()
    if hb is None:
        hb = ScannerHeartbeat(id=1)
        session.add(hb)

    hb.last_beat = datetime.now(timezone.utc)
    if status is not None:
        hb.status = status
    if error is not None:
        hb.error = error
    session.commit()
