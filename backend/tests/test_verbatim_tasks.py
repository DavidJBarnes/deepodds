"""Tests for the Verbatim background tasks.

The rate-limit protections carry the weight here. The Kalshi API key is SHARED
with `longshot-live`, which places real orders with `retry=False` — a 429 there
means the entry is skipped for that tick and the premium is lost. So "discovery
does not burst" is a correctness property of the trading system, not a nicety.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import VerbatimBase
from app.models.verbatim import Market, OrderbookDelta, ParseStatus, TranscriptChunk
from app.services.verbatim import retention, watchlist


@pytest_asyncio.fixture
async def vdb():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(VerbatimBase.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


class FakeKalshi:
    """Stands in for DeepOdds' synchronous KalshiClient."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls: list[dict] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        self.calls.append({"path": path, **(params or {})})
        return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]


def _mkt(ticker: str, title: str, **kw) -> dict:
    return {"ticker": ticker, "title": title, "rules_primary": kw.pop("rules", ""), **kw}


# ---------------------------------------------------------------------------
# Discovery heuristic
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "market,expected",
    [
        ({"title": "Will the President say 'wall'?"}, True),
        ({"title": "Fed mention of inflation"}, True),
        ({"title": "Highest temperature in Denver"}, False),
        ({"title": "BTC above 100k", "rules_primary": "Resolves if he says it"}, True),
        ({}, False),
    ],
)
def test_mention_heuristic(market, expected):
    assert watchlist.is_mention_market(market, "say") is expected


def test_heuristic_tolerates_none_fields():
    """Kalshi returns explicit nulls for absent rules; str(None) would make every
    market match on the literal 'none'."""
    assert watchlist.is_mention_market(
        {"title": None, "subtitle": None, "rules_primary": None}, "say"
    ) is False


# ---------------------------------------------------------------------------
# Pagination safety — the trading-adjacent property
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_discovery_sleeps_between_pages(monkeypatch):
    """A tight sweep of every open Kalshi market is what could 429 an order tick."""
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    pages = [
        {"markets": [_mkt("A", "Will he say it")], "cursor": "c1"},
        {"markets": [_mkt("B", "temperature")], "cursor": "c2"},
        {"markets": [_mkt("C", "Will she say it")], "cursor": None},
    ]
    client = FakeKalshi(pages)
    found = await watchlist.discover_markets(client, "say", page_sleep_s=1.0)
    assert [m["ticker"] for m in found] == ["A", "C"]
    # One sleep per page boundary, not per market.
    assert slept == [1.0, 1.0]


@pytest.mark.asyncio
async def test_discovery_is_page_capped(monkeypatch, caplog):
    """A cursor that never terminates must stop, not poll Kalshi forever."""
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    endless = [{"markets": [_mkt("A", "say")], "cursor": "always"}]
    client = FakeKalshi(endless)
    with caplog.at_level("WARNING"):
        await watchlist.discover_markets(client, "say", page_sleep_s=0, max_pages=5)
    assert len(client.calls) == 5
    assert any("page cap" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_discovery_passes_cursor_through(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client = FakeKalshi([
        {"markets": [], "cursor": "next-1"},
        {"markets": [], "cursor": None},
    ])
    await watchlist.discover_markets(client, "say", page_sleep_s=0)
    assert "cursor" not in client.calls[0]        # first page has none
    assert client.calls[1]["cursor"] == "next-1"  # second uses what page 1 returned


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_never_arms_a_market(vdb):
    """Arming points a GPU at a live stream. Discovery must not decide that."""
    await watchlist.ingest_market(vdb, _mkt("KXSAY-1", "Will he say it", rules="rules"))
    await vdb.commit()
    m = (await vdb.execute(select(Market))).scalar_one()
    assert m.armed is False
    assert m.parse_status == ParseStatus.NEEDS_REVIEW


@pytest.mark.asyncio
async def test_ingest_is_idempotent_and_preserves_operator_state(vdb):
    """A re-sweep must refresh the title and rules but never undo a human's arm."""
    await watchlist.ingest_market(vdb, _mkt("KXSAY-1", "Old title", rules="old"))
    await vdb.commit()
    m = (await vdb.execute(select(Market))).scalar_one()
    m.armed = True
    await vdb.commit()

    await watchlist.ingest_market(vdb, _mkt("KXSAY-1", "New title", rules="new"))
    await vdb.commit()
    rows = (await vdb.execute(select(Market))).scalars().all()
    assert len(rows) == 1                 # upsert, not duplicate
    assert rows[0].title == "New title"
    assert rows[0].raw_rules == "new"
    assert rows[0].armed is True          # operator state survives


@pytest.mark.asyncio
async def test_disarm_passed_deadlines(vdb):
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    future = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    vdb.add_all([
        Market(ticker="OLD", title="t", raw_rules="r", armed=True, deadline_utc=past),
        Market(ticker="NEW", title="t", raw_rules="r", armed=True, deadline_utc=future),
        Market(ticker="NONE", title="t", raw_rules="r", armed=True, deadline_utc=None),
    ])
    await vdb.commit()
    n = await watchlist.disarm_passed_deadlines(vdb)
    assert n == 1
    by = {m.ticker: m.armed for m in (await vdb.execute(select(Market))).scalars().all()}
    assert by == {"OLD": False, "NEW": True, "NONE": True}


# ---------------------------------------------------------------------------
# Retention — the table upstream configured but never pruned
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_prune_transcripts_respects_the_window(vdb):
    now = dt.datetime.now(dt.UTC)
    for hours, text in ((100, "old"), (1, "fresh")):
        vdb.add(TranscriptChunk(
            stream_id=1, capture_wallclock_utc=now - dt.timedelta(hours=hours),
            stream_offset_s=0.0, duration_s=4.0, text=text,
        ))
    await vdb.commit()
    removed = await retention.prune_transcripts(vdb, retention_hours=48, now=now)
    assert removed == 1
    kept = (await vdb.execute(select(TranscriptChunk))).scalars().all()
    assert [c.text for c in kept] == ["fresh"]


@pytest.mark.asyncio
async def test_prune_keeps_high_res_deltas(vdb):
    """high_res_retain marks the evidence behind an edge_seconds measurement.
    Outliving the generic window is the entire purpose of the flag."""
    now = dt.datetime.now(dt.UTC)
    old = now - dt.timedelta(days=90)
    vdb.add_all([
        OrderbookDelta(ticker="T", ts=old, side="yes", price=5, delta=1, high_res_retain=False),
        OrderbookDelta(ticker="T", ts=old, side="yes", price=6, delta=1, high_res_retain=True),
    ])
    await vdb.commit()
    removed = await retention.prune_orderbook_deltas(vdb, retention_days=14, now=now)
    assert removed == 1
    left = (await vdb.execute(select(OrderbookDelta))).scalars().all()
    assert len(left) == 1 and left[0].high_res_retain is True


@pytest.mark.asyncio
async def test_prune_batches_large_backlogs(vdb, monkeypatch):
    """One DELETE over days of backlog holds a long lock on the same RDS instance
    the trading database lives on."""
    monkeypatch.setattr(retention, "_BATCH", 10)
    now = dt.datetime.now(dt.UTC)
    for i in range(25):
        vdb.add(TranscriptChunk(
            stream_id=1, capture_wallclock_utc=now - dt.timedelta(hours=100),
            stream_offset_s=float(i), duration_s=4.0, text=f"c{i}",
        ))
    await vdb.commit()
    removed = await retention.prune_transcripts(vdb, retention_hours=48, now=now)
    assert removed == 25
    assert (await vdb.execute(select(func.count()).select_from(TranscriptChunk))).scalar() == 0
