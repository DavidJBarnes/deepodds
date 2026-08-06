"""Tests for the Verbatim API: auth boundaries, worker protocol, presigning.

Runs against an in-memory SQLite Verbatim database — the models carry portable
variants (JSON for JSONB, INTEGER for BIGINT PKs) precisely so this works without
a Postgres.

The security-relevant assertions here are the point of the file: every console
route must reject an anonymous caller, every worker route must reject a bad
service token, and a worker must not be able to arm a stream.
"""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.verbatim import require_verbatim_enabled
from app.core.database import VerbatimBase, get_verbatim_db
from app.core.deps import get_current_user
from app.core.verbatim_hub import Hub
from app.models.user import User
from app.models.verbatim import Market, MatchPattern, Stream, StreamStatus

WORKER_TOKEN = "test-worker-token"


@pytest_asyncio.fixture
async def vdb():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(VerbatimBase.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(vdb, monkeypatch):
    """App with the Verbatim DB swapped for SQLite and console auth stubbed."""
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "VERBATIM_WORKER_TOKEN", WORKER_TOKEN)
    monkeypatch.setattr(settings, "VERBATIM_CLIPS_BUCKET", "test-bucket")

    app.dependency_overrides[get_verbatim_db] = lambda: vdb
    app.dependency_overrides[require_verbatim_enabled] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: User(id="u1", email="t@example.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(vdb, monkeypatch):
    """App with NO auth override — used to prove routes actually reject.

    The worker token IS configured here: an unset token makes require_worker
    return 503 (misconfiguration), which would mask whether the token check
    itself rejects.
    """
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "VERBATIM_WORKER_TOKEN", WORKER_TOKEN)
    app.dependency_overrides[get_verbatim_db] = lambda: vdb
    app.dependency_overrides[require_verbatim_enabled] = lambda: None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


V = "/api/v1/verbatim"


# ---------------------------------------------------------------------------
# Auth boundaries — the reason the API moved into DeepOdds at all
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", f"{V}/markets"),
        ("get", f"{V}/streams"),
        ("get", f"{V}/detections"),
        ("get", f"{V}/heartbeats"),
        ("post", f"{V}/streams/arm"),
        ("post", f"{V}/markets/1/arm"),
    ],
)
async def test_console_routes_reject_anonymous(anon_client, method, path):
    """The standalone project had zero auth on these — including arm, which can
    point yt-dlp at an arbitrary URL. None may be reachable unauthenticated."""
    call = getattr(anon_client, method)
    resp = await (call(path, json={}) if method == "post" else call(path))
    assert resp.status_code in (401, 403), f"{method} {path} returned {resp.status_code}"


@pytest.mark.asyncio
async def test_worker_routes_reject_bad_token(anon_client):
    for hdr in ({}, {"Authorization": "Bearer wrong"}):
        resp = await anon_client.get(f"{V}/worker/work", headers=hdr)
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_worker_token_accepted(client, vdb):
    resp = await client.get(f"{V}/worker/work", headers={"Authorization": f"Bearer {WORKER_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["streams"] == [] and body["patterns"] == []


# ---------------------------------------------------------------------------
# Worker protocol
# ---------------------------------------------------------------------------
async def _seed(vdb) -> tuple[Stream, Market, MatchPattern]:
    stream = Stream(url="https://example.com/live", status=StreamStatus.ARMED)
    market = Market(ticker="KXM-1", title="Will they say it?", raw_rules="rules", armed=True)
    vdb.add_all([stream, market])
    await vdb.flush()
    pattern = MatchPattern(
        market_id=market.id, phrase="build the wall", variant="build the wall",
        variant_kind="normalized", active=True,
    )
    vdb.add(pattern)
    await vdb.commit()
    return stream, market, pattern


@pytest.mark.asyncio
async def test_work_payload_is_flattened_for_a_dbless_worker(client, vdb):
    stream, market, pattern = await _seed(vdb)
    resp = await client.get(f"{V}/worker/work", headers={"Authorization": f"Bearer {WORKER_TOKEN}"})
    body = resp.json()
    assert [s["id"] for s in body["streams"]] == [stream.id]
    assert body["patterns"][0]["variant"] == "build the wall"
    # Pre-joined: the worker holds no ORM, so market_id and title must come along.
    assert body["patterns"][0]["market_id"] == market.id
    assert body["market_titles"][str(market.id)] == "Will they say it?"
    assert body["patterns_fingerprint"]


@pytest.mark.asyncio
async def test_work_excludes_expired_armed_until(client, vdb):
    """An armed_until in the past is a disarm nothing got round to applying."""
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    vdb.add(Stream(url="https://ex/1", status=StreamStatus.ARMED, armed_until=past))
    await vdb.commit()
    resp = await client.get(f"{V}/worker/work", headers={"Authorization": f"Bearer {WORKER_TOKEN}"})
    assert resp.json()["streams"] == []


@pytest.mark.asyncio
async def test_fingerprint_changes_only_when_patterns_change(client, vdb):
    _s, market, _p = await _seed(vdb)
    h = {"Authorization": f"Bearer {WORKER_TOKEN}"}
    first = (await client.get(f"{V}/worker/work", headers=h)).json()["patterns_fingerprint"]
    assert (await client.get(f"{V}/worker/work", headers=h)).json()["patterns_fingerprint"] == first
    vdb.add(MatchPattern(market_id=market.id, phrase="p2", variant="v2",
                         variant_kind="normalized", active=True))
    await vdb.commit()
    assert (await client.get(f"{V}/worker/work", headers=h)).json()["patterns_fingerprint"] != first


@pytest.mark.asyncio
async def test_worker_may_not_arm_a_stream(client, vdb):
    """Arming is an operator decision. A compromised worker token must not be
    able to point ingest at a new URL."""
    stream, _m, _p = await _seed(vdb)
    resp = await client.post(
        f"{V}/worker/stream-status",
        json={"stream_id": stream.id, "status": "armed"},
        headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_worker_may_report_live_and_dead(client, vdb):
    stream, _m, _p = await _seed(vdb)
    h = {"Authorization": f"Bearer {WORKER_TOKEN}"}
    for st in ("live", "dead"):
        resp = await client.post(
            f"{V}/worker/stream-status",
            json={"stream_id": stream.id, "status": st, "restart_count": 2}, headers=h,
        )
        assert resp.status_code == 200 and resp.json()["status"] == st


@pytest.mark.asyncio
async def test_transcripts_persist_and_broadcast(client, vdb, monkeypatch):
    from app.core import verbatim_hub

    sent: list[tuple[str, dict]] = []

    async def fake_broadcast(event_type, payload):
        sent.append((event_type, payload))

    monkeypatch.setattr(verbatim_hub.hub, "broadcast", fake_broadcast)
    stream, _m, _p = await _seed(vdb)
    resp = await client.post(
        f"{V}/worker/transcripts",
        headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
        json={"chunks": [{
            "stream_id": stream.id,
            "capture_wallclock_utc": dt.datetime.now(dt.UTC).isoformat(),
            "stream_offset_s": 1.0, "duration_s": 4.0, "text": "hello there",
        }]},
    )
    assert resp.status_code == 202 and resp.json()["accepted"] == 1
    assert sent and sent[0][0] == "transcript"


@pytest.mark.asyncio
async def test_near_miss_is_broadcast_only(client, vdb, monkeypatch):
    """Near misses fire constantly; persisting them would bloat the DB for a UI
    pulse. Assert they are broadcast and never stored."""
    from app.core import verbatim_hub
    from sqlalchemy import func, select

    from app.models.verbatim import Candidate

    sent = []

    async def fake_broadcast(event_type, payload):
        sent.append(event_type)

    monkeypatch.setattr(verbatim_hub.hub, "broadcast", fake_broadcast)
    stream, market, pattern = await _seed(vdb)
    resp = await client.post(
        f"{V}/worker/near-miss",
        headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
        json={"stream_id": stream.id, "market_id": market.id, "pattern_id": pattern.id,
              "score": 0.81, "matched_text": "build a wall",
              "utterance_ts": dt.datetime.now(dt.UTC).isoformat()},
    )
    assert resp.status_code == 202 and sent == ["near_miss"]
    assert (await vdb.execute(select(func.count()).select_from(Candidate))).scalar() == 0


# ---------------------------------------------------------------------------
# Hub
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hub_drops_dead_sockets_without_blocking_others():
    """A browser that closed mid-broadcast must not stall the detection path."""
    hub = Hub()

    class Good:
        def __init__(self):
            self.got = []

        async def send_json(self, data):
            self.got.append(data)

    class Dead:
        async def send_json(self, data):
            raise RuntimeError("peer gone")

    good, dead = Good(), Dead()
    await hub.connect(good)
    await hub.connect(dead)
    await hub.broadcast("detection", {"id": 1})
    assert good.got == [{"type": "detection", "data": {"id": 1}}]
    assert hub.client_count == 1  # dead one evicted


# ---------------------------------------------------------------------------
# Presigning
# ---------------------------------------------------------------------------
def test_presign_is_scoped_and_signed(monkeypatch):
    """Structural check of the SigV4 URL. The real round-trip was verified
    against the live bucket; this guards the shape from regressing."""
    import datetime as _dt
    from urllib.parse import parse_qs, urlparse

    from app.core import s3presign

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    s3presign.reset_credential_cache()

    url = s3presign.presign(
        "PUT", "bkt", "clips/x.wav", "us-west-2", expires_in=600,
        now=_dt.datetime(2026, 8, 6, 12, 0, tzinfo=_dt.timezone.utc),
    )
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert parsed.netloc == "bkt.s3.us-west-2.amazonaws.com"
    assert parsed.path == "/clips/x.wav"
    assert q["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert q["X-Amz-Expires"] == ["600"]
    assert q["X-Amz-SignedHeaders"] == ["host"]
    assert len(q["X-Amz-Signature"][0]) == 64  # hex sha256
    s3presign.reset_credential_cache()


def test_presign_is_deterministic_for_a_fixed_instant(monkeypatch):
    import datetime as _dt

    from app.core import s3presign

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    s3presign.reset_credential_cache()
    at = _dt.datetime(2026, 8, 6, 12, 0, tzinfo=_dt.timezone.utc)
    a = s3presign.presign("GET", "bkt", "clips/x.wav", "us-west-2", now=at)
    b = s3presign.presign("GET", "bkt", "clips/x.wav", "us-west-2", now=at)
    assert a == b
    s3presign.reset_credential_cache()
