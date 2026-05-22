import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.services.polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


async def scan_polymarket(session: Session) -> int:
    """Discover Polymarket neg-risk events and upsert them as opportunities.

    Neg-risk events guarantee mutually exclusive outcomes summing to $1.00.
    When the sum drifts above/below $1.00, there's a mechanical arbitrage edge.
    """
    client = PolymarketClient()
    try:
        opportunities = await client.scan_neg_risk_edges(
            min_edge_cents=1.0,
            min_volume=100,
        )
    finally:
        await client.close()

    upserted = 0
    for opp in opportunities:
        import json as _json

        ticker = f"pm_{opp['event_id']}"
        existing = session.execute(
            select(Opportunity).where(Opportunity.ticker == ticker)
        ).scalar_one_or_none()

        if existing:
            existing.edge = opp["abs_edge_cents"]
            existing.edge_direction = opp["direction"]
            existing.volume = opp["total_volume"]
            existing.liquidity = opp["total_liquidity"]
            existing.close_time = opp["end_date"]
            existing.total_contracts = opp["outcome_count"]
            existing.active_contracts = opp["outcome_count"]
            existing.market_data = {
                "outcomes": opp["outcomes"],
                "sum_price": opp["sum_price"],
                "edge_cents": opp["edge_cents"],
                "slug": opp["slug"],
            }
            existing.last_scanned_at = datetime.now(timezone.utc)
        else:
            pm_opp = Opportunity(
                source="polymarket",
                event_ticker=opp.get("slug", "") or ticker,
                ticker=ticker,
                title=opp["title"],
                subtitle=f"{opp['outcome_count']} outcomes · {'SHORT' if opp['direction'] == 'short' else 'LONG'} {opp['abs_edge_cents']:.1f}c edge",
                category="NegRisk",
                asset="",
                strike_price=None,
                cap_strike=None,
                strike_type=None,
                spot_price=None,
                yes_price=None,
                no_price=None,
                yes_ask=None,
                no_ask=None,
                edge=opp["abs_edge_cents"],
                edge_direction=opp["direction"],
                quality=_edge_quality(opp["abs_edge_cents"], opp["total_volume"]),
                volume=opp["total_volume"],
                volume_24h=opp["total_volume"],
                open_interest=0,
                liquidity=opp["total_liquidity"],
                close_time=opp.get("end_date", ""),
                total_contracts=opp["outcome_count"],
                active_contracts=opp["outcome_count"],
                market_data={
                    "outcomes": opp["outcomes"],
                    "sum_price": opp["sum_price"],
                    "edge_cents": opp["edge_cents"],
                    "slug": opp["slug"],
                },
            )
            session.add(pm_opp)

        upserted += 1

    session.commit()
    logger.info("Polymarket scanner upserted %d opportunities", upserted)
    return upserted


def _edge_quality(edge_cents: float, volume: float) -> str:
    if edge_cents >= 10 and volume > 1_000_000:
        return "excellent"
    if edge_cents >= 5 and volume > 100_000:
        return "good"
    if edge_cents >= 2:
        return "decent"
    return "low"
