"""Pydantic models for the Verbatim console API and the GPU-worker wire contract.

Console models are read models over the ORM (``from_attributes=True``), ported
from the standalone project's `verbatim/api/schemas.py`.

Worker models are the new half: the GPU box holds no database and no AWS
credentials, so everything it knows arrives through `WorkPayload` and everything
it produces goes back through these push bodies.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Console read models
# ---------------------------------------------------------------------------


class PatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    market_id: int
    phrase: str
    variant: str
    variant_kind: str
    version: int
    active: bool
    manual: bool


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    title: str
    raw_rules: str
    parse_status: str
    speaker: str | None
    deadline_utc: datetime | None
    armed: bool


class StreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    label: str | None
    status: str
    expected_speaker: str | None
    armed_until: datetime | None
    restart_count: int


class DetectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: int
    market_id: int
    pattern_id: int
    state: str
    utterance_ts: datetime
    stage1_transcript: str
    stage2_transcript: str | None
    matched_span: str | None
    stage1_score: float
    stage2_score: float | None
    speaker_label: str | None
    speaker_is_expected: bool | None
    clip_path: str | None
    chunk_capture_ts: datetime | None
    stage1_done_ts: datetime | None
    candidate_ts: datetime | None
    stage2_done_ts: datetime | None
    alert_sent_ts: datetime | None
    market_reaction_ts: datetime | None
    edge_seconds: float | None


class HeartbeatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service: str
    stream_id: int | None
    ts: datetime
    audio_level: float | None
    chunk_rate: float | None
    restart_count: int | None
    detail: dict | None


# ---------------------------------------------------------------------------
# Console request bodies
# ---------------------------------------------------------------------------


class ArmStreamIn(BaseModel):
    url: str
    market_ids: list[int] = []
    armed_until: datetime | None = None
    expected_speaker: str | None = None
    label: str | None = None


class AddPatternIn(BaseModel):
    phrase: str


class ArmMarketIn(BaseModel):
    armed: bool


class SetPatternIn(BaseModel):
    active: bool


class ClipUrlOut(BaseModel):
    url: str
    expires_in: int
    # Set on PUT (upload) responses: the object key the worker must send back on
    # the detection row. Absent on GET (playback) responses.
    key: str | None = None


# ---------------------------------------------------------------------------
# GPU-worker wire contract
# ---------------------------------------------------------------------------


class WorkPattern(BaseModel):
    """One scannable variant, flattened so the worker needs no joins."""

    id: int
    market_id: int
    phrase: str
    variant: str


class WorkStream(BaseModel):
    id: int
    url: str
    expected_speaker: str | None
    armed_until: datetime | None


class WorkPayload(BaseModel):
    """Everything the GPU worker needs for one poll cycle.

    ``patterns_fingerprint`` lets the worker hot-swap the scan set without
    restarting a stream: if it is unchanged, nothing about matching has changed.
    """

    streams: list[WorkStream]
    patterns: list[WorkPattern]
    market_titles: dict[int, str]
    patterns_fingerprint: str


class TranscriptIn(BaseModel):
    stream_id: int
    capture_wallclock_utc: datetime
    stream_offset_s: float
    duration_s: float
    text: str
    words: list | None = None


class TranscriptBatchIn(BaseModel):
    """Batched to keep the push rate low — one POST per chunk would be ~1 req/4s
    per stream, and batching costs nothing since the console renders on the WS."""

    chunks: list[TranscriptIn] = Field(default_factory=list)


class NearMissIn(BaseModel):
    """Broadcast-only: near misses drive the console's pulse, never persisted."""

    stream_id: int
    market_id: int
    pattern_id: int
    score: float
    matched_text: str
    utterance_ts: datetime


class DetectionIn(BaseModel):
    stream_id: int
    market_id: int
    pattern_id: int
    state: str
    utterance_ts: datetime
    stage1_transcript: str
    stage2_transcript: str | None = None
    matched_span: str | None = None
    stage1_score: float
    stage2_score: float | None = None
    speaker_label: str | None = None
    speaker_is_expected: bool | None = None
    clip_path: str | None = None
    chunk_capture_ts: datetime | None = None
    stage1_done_ts: datetime | None = None
    candidate_ts: datetime | None = None
    stage2_done_ts: datetime | None = None


class HeartbeatIn(BaseModel):
    service: str
    stream_id: int | None = None
    audio_level: float | None = None
    chunk_rate: float | None = None
    restart_count: int | None = None
    detail: dict | None = None


class StreamStatusIn(BaseModel):
    """Worker-reported lifecycle transition (armed -> live, or -> dead)."""

    stream_id: int
    status: str
    restart_count: int | None = None


class ClipUploadIn(BaseModel):
    stream_id: int
    suffix: str = "wav"
