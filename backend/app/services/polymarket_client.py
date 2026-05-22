import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"


class PolymarketClient:
    """Read-only client for Polymarket's Gamma API.

    Discovers neg-risk events and fetches outcome prices. Order placement
    uses the CLOB API separately (not yet implemented).
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=GAMMA_BASE,
            timeout=30,
            headers={"User-Agent": "DeepOdds/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    #  Event discovery
    # ------------------------------------------------------------------ #

    async def get_open_events(
        self,
        tag: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Fetch open events, optionally filtered by tag."""
        params: dict[str, str | int] = {"closed": "false", "limit": limit}
        if tag:
            params["tag"] = tag
        resp = await self._client.get("/events", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_event(self, event_id: int) -> dict[str, Any]:
        """Fetch a single event with its markets/outcomes."""
        resp = await self._client.get(f"/events/{event_id}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    #  Neg-risk edge scanning
    # ------------------------------------------------------------------ #

    async def scan_neg_risk_edges(
        self,
        min_edge_cents: float = 1.0,
        min_volume: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Discover neg-risk events where outcome prices diverge from $1.00.

        Returns a list of edge opportunities with outcome-level detail.
        """
        events = await self.get_open_events(limit=200)
        neg_risk = [e for e in events if e.get("negRisk")]

        opportunities: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for e in neg_risk:
            eid = e.get("id")
            if not eid:
                continue

            try:
                edata = await self.get_event(eid)
            except Exception:
                logger.debug("Failed to fetch event %s", eid)
                continue

            markets = edata.get("markets", [])
            if len(markets) < 2:
                continue

            total_price = 0.0
            total_volume = 0.0
            total_liquidity = 0.0
            outcomes: list[dict[str, Any]] = []

            for m in markets:
                prices = m.get("outcomePrices", "[]")
                if isinstance(prices, str):
                    import json as _json
                    prices = _json.loads(prices)
                price = float(prices[0]) if prices else 0.0

                vol = float(m.get("volumeNum", 0) or 0)
                total_price += price
                total_volume += vol
                total_liquidity += float(m.get("liquidityNum", 0) or 0)

                outcomes.append({
                    "question": m.get("question", ""),
                    "price": price,
                    "volume": vol,
                    "token_id": m.get("clobTokenIds", "[]") if isinstance(m.get("clobTokenIds"), str) else None,
                })

            edge_cents = (total_price - 1.0) * 100
            abs_edge = abs(edge_cents)

            if abs_edge < min_edge_cents:
                continue
            if total_volume < min_volume:
                continue

            # Determine end date
            end_str = edata.get("endDate") or e.get("endDate") or ""
            end_dt: datetime | None = None
            if end_str:
                try:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            opportunities.append({
                "event_id": eid,
                "slug": e.get("slug", ""),
                "title": e.get("title", ""),
                "sum_price": total_price,
                "edge_cents": edge_cents,
                "abs_edge_cents": abs_edge,
                "direction": "short" if edge_cents > 0 else "long",
                "outcome_count": len(markets),
                "total_volume": total_volume,
                "total_liquidity": total_liquidity,
                "end_date": end_str,
                "end_dt": end_dt,
                "outcomes": outcomes[:10],  # top 10 for display
                "scanned_at": now,
            })

            # Rate limit: respect the API
            time.sleep(0.15)

        opportunities.sort(key=lambda o: o["abs_edge_cents"], reverse=True)
        return opportunities
