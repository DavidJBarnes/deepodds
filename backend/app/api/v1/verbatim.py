"""Verbatim API — console routes plus the GPU-worker wire protocol.

Two audiences, two auth schemes, deliberately separated:

* **Console routes** are gated by the normal DeepOdds JWT (`get_current_user`),
  so the Verbatim tab behaves exactly like Longshot and Edge Explorer.
* **Worker routes** (`/verbatim/worker/*`) are gated by a shared service token.
  The GPU box is not a user: it holds no JWT, no database credentials and no AWS
  credentials. It authenticates with one token and receives short-lived presigned
  URLs for clip upload.

The standalone Verbatim project had *no authentication at all* on any endpoint,
including arm/disarm — which can point `yt-dlp` at an arbitrary URL on the GPU
box. Every route here is authenticated; that is the main security gain of moving
the API into DeepOdds.

Data lives in a separate `verbatim` database on the same RDS instance
(`get_verbatim_db`), so nothing here can touch trading tables.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import s3presign
from app.core.config import settings
from app.core.database import get_verbatim_db, verbatim_sessionmaker
from app.core.deps import get_current_user
from app.core.security import decode_access_token
from app.core.verbatim_hub import hub
from app.models.user import User
from app.models.verbatim import (
    Detection,
    DetectionState,
    Market,
    MatchPattern,
    ServiceHeartbeat,
    Stream,
    StreamStatus,
    TranscriptChunk,
)
from app.schemas.verbatim import (
    AddPatternIn,
    ArmMarketIn,
    ArmStreamIn,
    ClipUploadIn,
    ClipUrlOut,
    DetectionIn,
    DetectionOut,
    HeartbeatIn,
    HeartbeatOut,
    MarketOut,
    NearMissIn,
    PatternOut,
    SetPatternIn,
    StreamOut,
    StreamStatusIn,
    TranscriptBatchIn,
    WorkPattern,
    WorkPayload,
    WorkStream,
)
from app.services.verbatim_variants import expand_phrase

logger = logging.getLogger("app.verbatim")
router = APIRouter(prefix="/verbatim", tags=["verbatim"])

_worker_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_verbatim_enabled() -> None:
    """503 rather than a 500 traceback when the Verbatim DB isn't configured."""
    if not settings.verbatim_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verbatim is not configured on this deployment",
        )


async def require_worker(
    credentials: HTTPAuthorizationCredentials | None = Depends(_worker_scheme),
) -> None:
    """Authenticate the GPU worker by shared service token.

    Compared with `hmac.compare_digest` so a wrong token cannot be recovered by
    timing the response.
    """
    import hmac

    expected = settings.VERBATIM_WORKER_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker token not configured",
        )
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker token"
        )


# ---------------------------------------------------------------------------
# Console — read
# ---------------------------------------------------------------------------
@router.get("/health")
async def verbatim_health(_user: User = Depends(get_current_user)) -> dict:
    """Liveness plus whatever the GPU worker last reported about itself.

    Deliberately reports the *worker's* view: the API being up says nothing about
    whether models are loaded, and the standalone project's `/readyz` returning
    ready while the GPU was down was actively misleading.
    """
    if not settings.verbatim_enabled:
        return {"status": "unconfigured", "degraded": ["verbatim_database"], "worker": None}
    async with verbatim_sessionmaker()() as db:
        rows = (
            await db.execute(
                select(ServiceHeartbeat)
                .where(ServiceHeartbeat.service.in_(("supervisor", "engine")))
                .order_by(desc(ServiceHeartbeat.ts))
                .limit(10)
            )
        ).scalars().all()
    latest: dict[str, dict] = {}
    for hb in rows:
        latest.setdefault(hb.service, {"ts": hb.ts, "detail": hb.detail})
    supervisor = latest.get("supervisor")
    stale = True
    if supervisor and supervisor["ts"]:
        age = (datetime.now(UTC) - supervisor["ts"]).total_seconds()
        stale = age > 60
    return {
        "status": "ok",
        "degraded": ["gpu_worker"] if stale else [],
        "worker": {"seen": supervisor is not None, "stale": stale, **(supervisor or {})},
        "ws_clients": hub.client_count,
    }


@router.get("/markets", response_model=list[MarketOut])
async def list_markets(
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> list[Market]:
    rows = await db.execute(select(Market).order_by(Market.deadline_utc.nulls_last(), Market.id))
    return list(rows.scalars().all())


@router.get("/markets/{market_id}/patterns", response_model=list[PatternOut])
async def list_patterns(
    market_id: int,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> list[MatchPattern]:
    rows = await db.execute(
        select(MatchPattern).where(MatchPattern.market_id == market_id).order_by(MatchPattern.id)
    )
    return list(rows.scalars().all())


@router.get("/detections", response_model=list[DetectionOut])
async def list_detections(
    state: str | None = None,
    market_id: int | None = None,
    limit: int = Query(100, le=500),
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> list[Detection]:
    stmt = select(Detection).order_by(desc(Detection.utterance_ts)).limit(limit)
    if state:
        stmt = stmt.where(Detection.state == state)
    if market_id is not None:
        stmt = stmt.where(Detection.market_id == market_id)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/detections/{detection_id}", response_model=DetectionOut)
async def get_detection(
    detection_id: int,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> Detection:
    det = await db.get(Detection, detection_id)
    if det is None:
        raise HTTPException(status_code=404, detail="detection not found")
    return det


@router.get("/detections/{detection_id}/clip", response_model=ClipUrlOut)
async def get_clip_url(
    detection_id: int,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> ClipUrlOut:
    """Presigned GET for the evidence WAV.

    Short-lived and issued per request, so clip audio is never public and the
    bucket stays fully private.
    """
    det = await db.get(Detection, detection_id)
    if det is None or not det.clip_path:
        raise HTTPException(status_code=404, detail="clip not found")
    if not settings.VERBATIM_CLIPS_BUCKET:
        raise HTTPException(status_code=503, detail="clips bucket not configured")
    ttl = settings.VERBATIM_CLIP_URL_TTL_S
    url = s3presign.presign(
        "GET", settings.VERBATIM_CLIPS_BUCKET, det.clip_path,
        settings.VERBATIM_S3_REGION, expires_in=ttl,
    )
    return ClipUrlOut(url=url, expires_in=ttl)


@router.get("/streams", response_model=list[StreamOut])
async def list_streams(
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> list[Stream]:
    return list((await db.execute(select(Stream).order_by(desc(Stream.id)))).scalars().all())


@router.get("/heartbeats", response_model=list[HeartbeatOut])
async def list_heartbeats(
    limit: int = Query(50, le=200),
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> list[ServiceHeartbeat]:
    rows = await db.execute(
        select(ServiceHeartbeat).order_by(desc(ServiceHeartbeat.ts)).limit(limit)
    )
    return list(rows.scalars().all())


# ---------------------------------------------------------------------------
# Console — write
# ---------------------------------------------------------------------------
@router.post("/markets/{market_id}/arm", response_model=MarketOut)
async def arm_market(
    market_id: int,
    body: ArmMarketIn,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> Market:
    market = await db.get(Market, market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="market not found")
    market.armed = body.armed
    await db.commit()
    await db.refresh(market)
    return market


@router.post("/markets/{market_id}/patterns", response_model=list[PatternOut], status_code=201)
async def add_patterns(
    market_id: int,
    body: AddPatternIn,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> list[MatchPattern]:
    """Add manual variants for a phrase. Manual patterns survive automatic
    rebuilds, so operator fixes are sticky."""
    market = await db.get(Market, market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="market not found")
    created = [
        MatchPattern(
            market_id=market_id, phrase=body.phrase, variant=v.text,
            variant_kind=v.kind, version=1, active=True, manual=True,
        )
        for v in expand_phrase(body.phrase)
    ]
    db.add_all(created)
    await db.commit()
    for p in created:
        await db.refresh(p)
    return created


@router.patch("/patterns/{pattern_id}", response_model=PatternOut)
async def set_pattern(
    pattern_id: int,
    body: SetPatternIn,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> MatchPattern:
    pattern = await db.get(MatchPattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="pattern not found")
    pattern.active = body.active
    await db.commit()
    await db.refresh(pattern)
    return pattern


@router.post("/streams/arm", response_model=StreamOut)
async def arm_stream(
    body: ArmStreamIn,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> Stream:
    """Arm a stream URL and optionally arm an attached set of markets.

    Reuses the existing row for the same URL. Note the upstream schema limitation
    this inherits: arming markets sets `Market.armed` GLOBALLY — there is no
    stream/market association — so every armed market is scanned on every armed
    stream. Correct for one stream at a time; two concurrent streams with
    disjoint watchlists would need a join table.
    """
    stream = (
        await db.execute(select(Stream).where(Stream.url == body.url))
    ).scalar_one_or_none()
    if stream is None:
        stream = Stream(url=body.url)
        db.add(stream)
    stream.status = StreamStatus.ARMED
    stream.armed_until = body.armed_until
    stream.expected_speaker = body.expected_speaker
    if body.label:
        stream.label = body.label
    for market_id in body.market_ids:
        market = await db.get(Market, market_id)
        if market is not None:
            market.armed = True
    await db.commit()
    await db.refresh(stream)
    logger.info("verbatim stream armed url=%s markets=%d", body.url, len(body.market_ids))
    return stream


@router.post("/streams/{stream_id}/disarm", response_model=StreamOut)
async def disarm_stream(
    stream_id: int,
    _user: User = Depends(get_current_user),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> Stream:
    stream = await db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    stream.status = StreamStatus.IDLE
    stream.armed_until = None
    await db.commit()
    await db.refresh(stream)
    return stream


# ---------------------------------------------------------------------------
# WebSocket — live console feed
# ---------------------------------------------------------------------------
@router.websocket("/ws")
async def verbatim_ws(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Live fan-out to the console.

    The JWT arrives as a query parameter because browsers cannot set headers on a
    WebSocket handshake. Validated before `accept()` so an unauthenticated peer is
    never connected, and closed with 4401 (an application close code) rather than
    an HTTP status, which the browser cannot see on a failed upgrade anyway.
    """
    payload = decode_access_token(token) if token else None
    if payload is None or payload.get("sub") is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    await hub.connect(websocket)
    try:
        while True:
            # Client sends nothing meaningful; this is the disconnect detector.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 — never let one socket kill the endpoint
        logger.debug("verbatim ws closed abnormally", exc_info=True)
    finally:
        await hub.disconnect(websocket)


# ---------------------------------------------------------------------------
# Worker protocol
# ---------------------------------------------------------------------------
@router.get("/worker/work", response_model=WorkPayload)
async def worker_work(
    _auth: None = Depends(require_worker),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> WorkPayload:
    """Everything the GPU worker needs for one poll cycle.

    Flattened deliberately: the worker holds no ORM and no database, so patterns
    arrive pre-joined to their market.
    """
    now = datetime.now(UTC)
    streams = list(
        (
            await db.execute(
                select(Stream).where(Stream.status.in_((StreamStatus.ARMED, StreamStatus.LIVE)))
            )
        ).scalars().all()
    )
    # An expired armed_until is a disarm the scheduler never got to.
    # Normalize tz: Postgres returns aware datetimes but SQLite (tests, and any
    # future local run) returns naive ones for the same timezone=True column, and
    # comparing the two raises TypeError.
    def _expired(value: datetime | None) -> bool:
        if value is None:
            return False
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value <= now

    streams = [s for s in streams if not _expired(s.armed_until)]

    rows = list(
        (
            await db.execute(
                select(MatchPattern, Market)
                .join(Market, Market.id == MatchPattern.market_id)
                .where(Market.armed.is_(True), MatchPattern.active.is_(True))
            )
        ).all()
    )
    patterns = [
        WorkPattern(id=p.id, market_id=p.market_id, phrase=p.phrase, variant=p.variant)
        for p, _m in rows
    ]
    titles = {m.id: m.title for _p, m in rows}

    import hashlib

    fp = hashlib.sha256(
        "|".join(f"{p.id}:{p.variant}" for p in sorted(patterns, key=lambda x: x.id)).encode()
    ).hexdigest()[:16]

    return WorkPayload(
        streams=[
            WorkStream(
                id=s.id, url=s.url, expected_speaker=s.expected_speaker,
                armed_until=s.armed_until,
            )
            for s in streams
        ],
        patterns=patterns,
        market_titles=titles,
        patterns_fingerprint=fp,
    )


@router.post("/worker/transcripts", status_code=202)
async def worker_transcripts(
    body: TranscriptBatchIn,
    _auth: None = Depends(require_worker),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> dict:
    rows = [
        TranscriptChunk(
            stream_id=c.stream_id,
            capture_wallclock_utc=c.capture_wallclock_utc,
            stream_offset_s=c.stream_offset_s,
            duration_s=c.duration_s,
            text=c.text,
            words=c.words,
        )
        for c in body.chunks
    ]
    db.add_all(rows)
    await db.commit()
    for c in body.chunks:
        await hub.broadcast(
            "transcript",
            {
                "stream_id": c.stream_id,
                "text": c.text,
                "ts": c.capture_wallclock_utc.isoformat(),
                "duration_s": c.duration_s,
            },
        )
    return {"accepted": len(rows)}


@router.post("/worker/near-miss", status_code=202)
async def worker_near_miss(
    body: NearMissIn,
    _auth: None = Depends(require_worker),
) -> dict:
    """Broadcast-only — near misses drive the console pulse and are never stored."""
    await hub.broadcast("near_miss", body.model_dump(mode="json"))
    return {"ok": True}


@router.post("/worker/detections", response_model=DetectionOut, status_code=201)
async def worker_detection(
    body: DetectionIn,
    _auth: None = Depends(require_worker),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> Detection:
    det = Detection(
        stream_id=body.stream_id,
        market_id=body.market_id,
        pattern_id=body.pattern_id,
        state=DetectionState(body.state),
        utterance_ts=body.utterance_ts,
        stage1_transcript=body.stage1_transcript,
        stage2_transcript=body.stage2_transcript,
        matched_span=body.matched_span,
        stage1_score=body.stage1_score,
        stage2_score=body.stage2_score,
        speaker_label=body.speaker_label,
        speaker_is_expected=body.speaker_is_expected,
        clip_path=body.clip_path,
        chunk_capture_ts=body.chunk_capture_ts,
        stage1_done_ts=body.stage1_done_ts,
        candidate_ts=body.candidate_ts,
        stage2_done_ts=body.stage2_done_ts,
        alert_sent_ts=datetime.now(UTC),
    )
    db.add(det)
    await db.commit()
    await db.refresh(det)
    await hub.broadcast(
        "detection",
        {
            "id": det.id,
            "market_id": det.market_id,
            "state": det.state.value,
            "matched_span": det.matched_span,
            "utterance_ts": det.utterance_ts.isoformat(),
        },
    )
    return det


@router.post("/worker/heartbeats", status_code=202)
async def worker_heartbeat(
    body: HeartbeatIn,
    _auth: None = Depends(require_worker),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> dict:
    hb = ServiceHeartbeat(
        service=body.service,
        stream_id=body.stream_id,
        ts=datetime.now(UTC),
        audio_level=body.audio_level,
        chunk_rate=body.chunk_rate,
        restart_count=body.restart_count,
        detail=body.detail,
    )
    db.add(hb)
    await db.commit()
    await hub.broadcast("heartbeat", body.model_dump(mode="json"))
    return {"ok": True}


@router.post("/worker/stream-status", response_model=StreamOut)
async def worker_stream_status(
    body: StreamStatusIn,
    _auth: None = Depends(require_worker),
    _on: None = Depends(require_verbatim_enabled),
    db: AsyncSession = Depends(get_verbatim_db),
) -> Stream:
    """Worker-reported lifecycle transition (armed -> live, or -> dead).

    A worker may only report *operational* states; it must never be able to arm a
    stream, which is an operator decision made through the console.
    """
    stream = await db.get(Stream, body.stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    try:
        new_status = StreamStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid status") from None
    if new_status not in (StreamStatus.LIVE, StreamStatus.DEAD, StreamStatus.IDLE):
        raise HTTPException(status_code=403, detail="worker may not set that status")
    stream.status = new_status
    if body.restart_count is not None:
        stream.restart_count = body.restart_count
    await db.commit()
    await db.refresh(stream)
    return stream


@router.post("/worker/clip-url", response_model=ClipUrlOut)
async def worker_clip_url(
    body: ClipUploadIn,
    _auth: None = Depends(require_worker),
) -> ClipUrlOut:
    """Issue a short-lived presigned PUT so the worker can upload evidence audio
    straight to S3 — clip bytes never transit this box."""
    if not settings.VERBATIM_CLIPS_BUCKET:
        raise HTTPException(status_code=503, detail="clips bucket not configured")
    key = f"clips/stream{body.stream_id}_{int(time.time() * 1000)}.{body.suffix}"
    ttl = settings.VERBATIM_CLIP_URL_TTL_S
    url = s3presign.presign(
        "PUT", settings.VERBATIM_CLIPS_BUCKET, key,
        settings.VERBATIM_S3_REGION, expires_in=ttl,
    )
    # `key` is the durable identifier that goes on the detection row; `url` is
    # single-use upload scaffolding that expires.
    return ClipUrlOut(url=url, expires_in=ttl, key=key)
