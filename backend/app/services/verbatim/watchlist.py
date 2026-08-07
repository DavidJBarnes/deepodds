"""Kalshi mention-market discovery for Verbatim.

Ported from the standalone project's `watchlist/service.py`, with two deliberate
changes:

1. **It uses DeepOdds' Kalshi client, not Verbatim's.** Verbatim's
   `core/kalshi.py` has no 429 handling at all — `raise_for_status()` straight
   through. DeepOdds' client already respects `Retry-After` and spaces requests by
   `_REQUEST_DELAY_SEC`. Since the API key is SHARED with the live trading harness,
   the client that already knows how to back off is the only safe one to use.

2. **Pagination is throttled and bounded.** The original walked every open Kalshi
   market in a tight loop with no cap — thousands of markets, a burst of ~30-100+
   requests in seconds. If that lands in the same second as `longshot-live`'s order
   tick, a 429 on an order POST means the entry is silently skipped for that tick
   (post() uses retry=False, correctly, because a retried POST can double-submit).
   Lost premium on a strategy whose deployed-collateral cap already binds.

The Anthropic rules parser is not ported: without a key the upstream project runs
in "raw-rules" mode anyway, flagging markets `needs_review` with no phrase
extraction. That is exactly the behaviour here — an operator adds phrases by hand
on the Watchlist tab, which is the safer default for something that arms a GPU.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verbatim import Market, ParseStatus

logger = logging.getLogger("app.verbatim.watchlist")

# Kalshi returns up to 100 markets a page. Sleep between pages so a full sweep is
# spread over time instead of arriving as a burst next to an order tick.
_PAGE_SLEEP_S = 1.0
# Hard cap. A sweep that wants more pages than this is either a Kalshi change or a
# bug; either way it should stop and say so rather than hammer the API.
_MAX_PAGES = 60


def is_mention_market(market: dict[str, Any], query: str) -> bool:
    """Does a Kalshi market look like a 'will they say it' market?

    Same heuristic as upstream: the configurable query (default "say") or the word
    "mention", case-insensitively, across title/subtitle/rules.
    """
    haystack = " ".join(
        str(market.get(k, "") or "")
        for k in ("title", "subtitle", "yes_sub_title", "rules_primary", "rules_secondary")
    ).lower()
    return query.lower() in haystack or "mention" in haystack


def raw_rules_text(market: dict[str, Any]) -> str:
    """Concatenate the rules fields Kalshi provides into one blob."""
    primary = market.get("rules_primary") or ""
    secondary = market.get("rules_secondary") or ""
    return "\n".join(p for p in (primary, secondary) if p).strip() or market.get("title", "")


async def discover_markets(client: Any, query: str, *, page_sleep_s: float = _PAGE_SLEEP_S,
                           max_pages: int = _MAX_PAGES) -> list[dict[str, Any]]:
    """Page through open Kalshi markets and return mention-type candidates.

    `client` is DeepOdds' synchronous KalshiClient; each page is run in a thread so
    a multi-second sweep never blocks the event loop.
    """
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    pages = 0
    while pages < max_pages:
        params: dict[str, Any] = {"status": "open", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = await asyncio.to_thread(client.get, "/markets", params)
        for market in page.get("markets", []):
            if is_mention_market(market, query):
                found.append(market)
        pages += 1
        cursor = page.get("cursor")
        if not cursor:
            break
        await asyncio.sleep(page_sleep_s)
    else:
        # Loop exhausted without a break: we hit the cap with a cursor still live.
        logger.warning(
            "verbatim discovery hit the %d-page cap with more pages available; "
            "stopping rather than continuing to poll", max_pages
        )
    logger.info("verbatim discovery: %d candidates over %d pages", len(found), pages)
    return found


def _parse_deadline(market: dict[str, Any]) -> datetime | None:
    for key in ("close_time", "expiration_time", "latest_expiration_time"):
        raw = market.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


async def ingest_market(session: AsyncSession, market: dict[str, Any]) -> Market:
    """Upsert one discovered market. Never arms it — arming is an operator action.

    Markets land as `needs_review` with no extracted phrases: pointing a GPU at a
    live stream on the strength of an automatic rules parse is not a decision this
    should make on its own.
    """
    ticker = market["ticker"]
    existing = (
        await session.execute(select(Market).where(Market.ticker == ticker))
    ).scalar_one_or_none()

    rules = raw_rules_text(market)
    deadline = _parse_deadline(market)

    if existing is None:
        existing = Market(
            ticker=ticker,
            event_ticker=market.get("event_ticker"),
            series_ticker=market.get("series_ticker"),
            title=market.get("title") or ticker,
            raw_rules=rules,
            parse_status=ParseStatus.NEEDS_REVIEW,
            deadline_utc=deadline,
            armed=False,
        )
        session.add(existing)
    else:
        # Refresh the mutable fields; never touch `armed` or a human's parse verdict.
        existing.title = market.get("title") or existing.title
        existing.raw_rules = rules
        existing.deadline_utc = deadline
    return existing


async def refresh_once(session: AsyncSession, client: Any, query: str = "say") -> int:
    """One discovery sweep. Returns the number of markets ingested."""
    candidates = await discover_markets(client, query)
    for market in candidates:
        await ingest_market(session, market)
    await session.commit()
    return len(candidates)


async def disarm_passed_deadlines(session: AsyncSession, now: datetime | None = None) -> int:
    """Disarm markets whose deadline has passed.

    Left armed, they would keep a GPU scanning for a phrase that can no longer
    settle anything.
    """
    now = now or datetime.now(UTC)
    rows = (
        await session.execute(select(Market).where(Market.armed.is_(True)))
    ).scalars().all()
    n = 0
    for market in rows:
        deadline = market.deadline_utc
        if deadline is None:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if deadline <= now:
            market.armed = False
            n += 1
    if n:
        await session.commit()
        logger.info("verbatim disarmed %d market(s) past deadline", n)
    return n
