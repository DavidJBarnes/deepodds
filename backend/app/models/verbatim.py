"""Verbatim ORM models — the system of record for speech surveillance.

Ported from the standalone Verbatim project (`DavidJBarnes/verbatim`,
`backend/verbatim/core/models.py`). DeepOdds now owns the data; the GPU box runs
only inference and pushes results here over HTTPS, so these tables live in a
separate `verbatim` database on the same RDS instance.

Bound to `VerbatimBase`, NOT the trading `Base` — see the note in
`app/core/database.py` for why that separation is load-bearing.

The schema is deliberately denormalized in places (both stage-1 and stage-2
transcripts sit on the detection row) so the console can render a full audit
trail from a single row without joins.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import VerbatimBase

# Portable JSON: native JSONB on Postgres, plain JSON elsewhere (SQLite in tests).
JSONB_ = JSON().with_variant(JSONB(), "postgresql")

# Portable big-int PK: BIGINT on Postgres, INTEGER on SQLite — SQLite only
# autoincrements INTEGER primary keys, so the in-memory test DB needs the variant.
BigIntPk = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    """Current timezone-aware UTC time (default for created_at)."""
    return datetime.now(tz=UTC)


class ParseStatus(str, Enum):
    """Lifecycle of a market's rules parse."""

    PENDING = "pending"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    RAW_RULES = "raw_rules"  # produced in degraded (no Anthropic key) mode


class StreamStatus(str, Enum):
    """Operational status of an ingest stream."""

    IDLE = "idle"
    ARMED = "armed"
    LIVE = "live"
    DEAD = "dead"


class DetectionState(str, Enum):
    """Whether a candidate became a confirmed detection."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class AlertKind(str, Enum):
    """Alert category, controlling ntfy priority."""

    DETECTION = "detection"
    STREAM_DIED = "stream_died"
    NEEDS_REVIEW = "needs_review"
    GPU_RESTART = "gpu_restart"
    SCHEDULE_SCRAPE_FAILED = "schedule_scrape_failed"


class TimestampMixin:
    """Adds a ``created_at`` column defaulting to now (UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Stream(TimestampMixin, VerbatimBase):
    """A live audio source that can be armed for ingest."""

    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[StreamStatus] = mapped_column(
        SAEnum(StreamStatus, name="stream_status"), default=StreamStatus.IDLE, nullable=False
    )
    expected_speaker: Mapped[str | None] = mapped_column(String(200))
    armed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restart_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    heartbeats: Mapped[list[ServiceHeartbeat]] = relationship(back_populates="stream")


class ListeningWindow(TimestampMixin, VerbatimBase):
    """A scheduled span during which a speaker is expected to be live."""

    __tablename__ = "listening_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_speaker: Mapped[str | None] = mapped_column(String(200))
    stream_hint: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50), default="scrape", nullable=False)

    __table_args__ = (Index("ix_listening_windows_start", "start_utc"),)


class Market(TimestampMixin, VerbatimBase):
    """A Kalshi mention market plus its raw rules and parse status."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    event_ticker: Mapped[str | None] = mapped_column(String(120))
    series_ticker: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_rules: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[ParseStatus] = mapped_column(
        SAEnum(ParseStatus, name="parse_status"), default=ParseStatus.PENDING, nullable=False
    )
    parsed: Mapped[dict | None] = mapped_column(JSONB_)  # {phrases, speaker, ...}
    speaker: Mapped[str | None] = mapped_column(String(200))
    deadline_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    armed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    patterns: Mapped[list[MatchPattern]] = relationship(back_populates="market")

    __table_args__ = (Index("ix_markets_armed_deadline", "armed", "deadline_utc"),)


class MatchPattern(TimestampMixin, VerbatimBase):
    """A versioned, normalized phrase variant the matcher scans for."""

    __tablename__ = "match_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)
    phrase: Mapped[str] = mapped_column(Text, nullable=False)  # canonical phrase
    variant: Mapped[str] = mapped_column(Text, nullable=False)  # normalized variant
    variant_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    market: Mapped[Market] = relationship(back_populates="patterns")

    __table_args__ = (Index("ix_match_patterns_market_active", "market_id", "active"),)


class TranscriptChunk(TimestampMixin, VerbatimBase):
    """A stage-1 transcript chunk (rolling retention — see the pruning task)."""

    __tablename__ = "transcript_chunks"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), nullable=False)
    capture_wallclock_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    stream_offset_s: Mapped[float] = mapped_column(Float, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words: Mapped[list | None] = mapped_column(JSONB_)  # [{word, start, end}, ...]

    __table_args__ = (
        Index("ix_transcript_chunks_stream_ts", "stream_id", "capture_wallclock_utc"),
    )


class Candidate(TimestampMixin, VerbatimBase):
    """A near/candidate match found by stage-1 scanning (pre-confirmation)."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), nullable=False)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)
    pattern_id: Mapped[int] = mapped_column(ForeignKey("match_patterns.id"), nullable=False)
    utterance_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stage1_score: Mapped[float] = mapped_column(Float, nullable=False)
    matched_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_candidate: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (Index("ix_candidates_market_ts", "market_id", "utterance_ts"),)


class Detection(TimestampMixin, VerbatimBase):
    """A stage-2 confirmation decision (confirmed or rejected) with full evidence."""

    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"))
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), nullable=False)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)
    pattern_id: Mapped[int] = mapped_column(ForeignKey("match_patterns.id"), nullable=False)
    state: Mapped[DetectionState] = mapped_column(
        SAEnum(DetectionState, name="detection_state"), nullable=False
    )

    utterance_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stage1_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    stage2_transcript: Mapped[str | None] = mapped_column(Text)
    matched_span: Mapped[str | None] = mapped_column(Text)
    stage1_score: Mapped[float] = mapped_column(Float, nullable=False)
    stage2_score: Mapped[float | None] = mapped_column(Float)
    speaker_label: Mapped[str | None] = mapped_column(String(100))
    speaker_is_expected: Mapped[bool | None] = mapped_column(Boolean)
    # S3 object key for the evidence WAV (the standalone project stored a local
    # filesystem path; clips now go straight to S3 and never touch the API box).
    clip_path: Mapped[str | None] = mapped_column(Text)

    # Latency instrumentation — every hop persisted, so edge_seconds is auditable.
    chunk_capture_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage1_done_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage2_done_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_sent_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Market-reaction scoreboard.
    market_reaction_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edge_seconds: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_detections_market_ts", "market_id", "utterance_ts"),
        Index("ix_detections_state", "state"),
    )


class OrderbookSnapshot(TimestampMixin, VerbatimBase):
    """A full orderbook snapshot for a market ticker."""

    __tablename__ = "orderbook_snapshots"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(120), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    yes: Mapped[list | None] = mapped_column(JSONB_)  # [[price, size], ...]
    no: Mapped[list | None] = mapped_column(JSONB_)
    reason: Mapped[str] = mapped_column(String(40), default="interval", nullable=False)

    __table_args__ = (Index("ix_orderbook_snapshots_ticker_ts", "ticker", "ts"),)


class OrderbookDelta(TimestampMixin, VerbatimBase):
    """A single orderbook delta (price-level change) for a ticker."""

    __tablename__ = "orderbook_deltas"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(120), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # "yes" | "no"
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # cents
    delta: Mapped[int] = mapped_column(Integer, nullable=False)  # contract count change
    high_res_retain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (Index("ix_orderbook_deltas_ticker_ts", "ticker", "ts"),)


class Alert(TimestampMixin, VerbatimBase):
    """A record of an alert send (push or operational), with latency."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True)
    kind: Mapped[AlertKind] = mapped_column(SAEnum(AlertKind, name="alert_kind"), nullable=False)
    detection_id: Mapped[int | None] = mapped_column(ForeignKey("detections.id"))
    priority: Mapped[str] = mapped_column(String(20), default="default", nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    click_url: Mapped[str | None] = mapped_column(Text)
    sent_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    send_latency_ms: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("ix_alerts_kind_created", "kind", "created_at"),)


class ServiceHeartbeat(TimestampMixin, VerbatimBase):
    """Per-service (and per-stream) health heartbeat."""

    __tablename__ = "service_heartbeats"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True)
    service: Mapped[str] = mapped_column(String(60), nullable=False)
    stream_id: Mapped[int | None] = mapped_column(ForeignKey("streams.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    audio_level: Mapped[float | None] = mapped_column(Float)
    chunk_rate: Mapped[float | None] = mapped_column(Float)
    restart_count: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSONB_)

    stream: Mapped[Stream | None] = relationship(back_populates="heartbeats")

    __table_args__ = (Index("ix_service_heartbeats_service_ts", "service", "ts"),)
