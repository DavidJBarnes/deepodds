import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.services.binance_client import get_crypto_prices, get_fear_greed
from app.services.deribit_client import get_iv_surface
from app.services.kalshi_client import KalshiClient
from app.services.probability_model import compute_edge, prob_above, prob_below, prob_between, time_to_expiry

logger = logging.getLogger(__name__)

CRYPTO_SERIES = ["KXBTC", "KXBTCD", "KXETH", "KXETHD"]

STRIKE_RE = re.compile(r"[\$]?([\d,]+(?:\.\d+)?)")


def _parse_strike(market: dict) -> float | None:
    strike = market.get("floor_strike")
    if strike is not None:
        try:
            return float(strike)
        except (ValueError, TypeError):
            pass
    for field in ("subtitle", "yes_sub_title", "title"):
        val = market.get(field, "")
        if not val:
            continue
        m = STRIKE_RE.search(val.replace(",", ""))
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def _detect_asset(event_ticker: str) -> str:
    upper = event_ticker.upper()
    if "ETH" in upper:
        return "ETH"
    return "BTC"


def _dollars_to_cents(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val) * 100
    except (ValueError, TypeError):
        return None


def _calc_edge(spot: float, strike: float, yes_cents: float | None) -> tuple[float, str]:
    if spot > strike:
        intrinsic_yes = min(95, max(60, 50 + (spot - strike) / strike * 500))
        direction = "yes"
    else:
        intrinsic_yes = max(5, min(40, 50 - (strike - spot) / strike * 500))
        direction = "no"

    if yes_cents is None:
        return abs(intrinsic_yes - 50), direction

    if direction == "yes":
        edge = intrinsic_yes - yes_cents
    else:
        edge = (100 - intrinsic_yes) - (100 - yes_cents)

    return abs(edge), direction if edge >= 0 else ("no" if direction == "yes" else "yes")


def _rate_quality(volume: float, liquidity: float, edge: float, open_interest: float) -> str:
    score = 0
    if volume > 100:
        score += 1
    if volume > 1000:
        score += 1
    if liquidity > 50:
        score += 1
    if liquidity > 500:
        score += 1
    if edge > 5:
        score += 1
    if edge > 15:
        score += 1
    if open_interest > 50:
        score += 1

    if score >= 5:
        return "excellent"
    if score >= 3:
        return "good"
    if score >= 1:
        return "decent"
    return "low"


def _match_iv(iv_surface: dict, target_expiry: datetime) -> float | None:
    """Find ATM IV from the Deribit surface closest to the target expiry."""
    if not iv_surface:
        return None
    best = None
    best_dist = float("inf")
    for _key, data in iv_surface.items():
        if data.get("expiry_dt") is None:
            continue
        dist = abs((data["expiry_dt"] - target_expiry).total_seconds())
        if dist < best_dist:
            best_dist = dist
            best = data
    if best:
        return best["atm_iv"] / 100.0
    return None


async def scan_opportunities(kalshi: KalshiClient, session: Session) -> int:
    try:
        prices = await get_crypto_prices()
    except Exception:
        logger.warning("Failed to fetch crypto prices, using empty")
        prices = {}

    try:
        fg = await get_fear_greed()
    except Exception:
        fg = {"value": 50, "label": "Neutral"}

    iv_surfaces: dict[str, dict] = {}
    for currency in ("BTC", "ETH"):
        try:
            iv_surfaces[currency] = await get_iv_surface(currency)
        except Exception:
            logger.warning("Failed to fetch IV surface for %s", currency)
            iv_surfaces[currency] = {}

    upserted = 0

    for series in CRYPTO_SERIES:
        try:
            events_list = await _fetch_events(kalshi, series)
        except Exception:
            logger.warning("Failed to fetch events for series %s", series, exc_info=True)
            continue

        for event_data in events_list:
            event_ticker = event_data.get("event_ticker", "")
            if not event_ticker:
                continue
            asset = _detect_asset(event_ticker)
            spot = prices.get(asset)

            try:
                markets = await kalshi.get_markets_for_event(event_ticker)
            except Exception:
                logger.warning("Failed to fetch markets for %s", event_ticker, exc_info=True)
                continue

            active = [m for m in markets if m.get("status") not in ("settled", "finalized")]
            if not active:
                continue

            best = _pick_best_contract(active, spot)
            if not best:
                continue

            strike = _parse_strike(best)
            yes_cents = _dollars_to_cents(best.get("yes_bid_dollars"))
            no_cents = _dollars_to_cents(best.get("no_bid_dollars"))
            yes_ask = _dollars_to_cents(best.get("yes_ask_dollars"))
            no_ask = _dollars_to_cents(best.get("no_ask_dollars"))
            volume = float(best.get("volume_fp", "0") or "0")
            volume_24h = float(best.get("volume_24h_fp", "0") or "0")
            oi = float(best.get("open_interest_fp", "0") or "0")
            liq = float(best.get("liquidity_dollars", "0") or "0")

            model_prob = None
            model_fair = None
            model_edge = None
            iv_used = None
            close_time_str = best.get("close_time")
            s_type = best.get("strike_type")
            cap = best.get("cap_strike")
            cap_val = None
            if cap is not None:
                try:
                    cap_val = float(cap)
                except (ValueError, TypeError):
                    pass

            if spot and strike and close_time_str:
                try:
                    expiry_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
                    iv = _match_iv(iv_surfaces.get(asset, {}), expiry_dt)
                    if iv:
                        iv_used = iv
                        T = time_to_expiry(expiry_dt)
                        if s_type == "between" and cap_val is not None:
                            model_prob = prob_between(spot, strike, cap_val, iv, T)
                        elif s_type == "below":
                            model_prob = prob_below(spot, strike, iv, T)
                        else:
                            model_prob = prob_above(spot, strike, iv, T)
                        model_fair = model_prob * 100
                        model_edge = compute_edge(model_prob, yes_ask, no_ask)
                except Exception:
                    logger.warning("Model calc failed for %s", best.get("ticker"), exc_info=True)

            edge = abs(model_edge) if model_edge is not None else 0.0
            if model_edge is not None:
                direction = "yes" if model_edge > 0 else "no"
            elif spot and strike:
                direction = "yes" if spot > strike else "no"
            else:
                direction = "yes"

            quality = _rate_quality(volume, liq, edge, oi)

            existing = session.execute(
                select(Opportunity).where(Opportunity.ticker == best["ticker"])
            ).scalar_one_or_none()

            if existing:
                existing.cap_strike = cap_val
                existing.strike_type = s_type
                existing.spot_price = spot
                existing.yes_price = yes_cents
                existing.no_price = no_cents
                existing.yes_ask = yes_ask
                existing.no_ask = no_ask
                existing.edge = edge
                existing.edge_direction = direction
                existing.quality = quality
                existing.volume = volume
                existing.volume_24h = volume_24h
                existing.open_interest = oi
                existing.liquidity = liq
                existing.model_prob = model_prob
                existing.model_fair_cents = model_fair
                existing.model_edge_cents = model_edge
                existing.implied_vol = iv_used
                existing.fear_greed_value = fg.get("value")
                existing.fear_greed_label = fg.get("label")
                existing.active_contracts = len(active)
                existing.last_scanned_at = datetime.now(timezone.utc)
                existing.market_data = best
            else:
                opp = Opportunity(
                    event_ticker=event_ticker,
                    ticker=best["ticker"],
                    title=event_data.get("title", best.get("title", event_ticker)),
                    subtitle=best.get("subtitle", best.get("yes_sub_title")),
                    category="Crypto",
                    asset=asset,
                    strike_price=strike,
                    cap_strike=cap_val,
                    strike_type=s_type,
                    spot_price=spot,
                    yes_price=yes_cents,
                    no_price=no_cents,
                    yes_ask=yes_ask,
                    no_ask=no_ask,
                    edge=edge,
                    edge_direction=direction,
                    quality=quality,
                    volume=volume,
                    volume_24h=volume_24h,
                    open_interest=oi,
                    liquidity=liq,
                    close_time=close_time_str,
                    total_contracts=len(markets),
                    active_contracts=len(active),
                    market_data=best,
                    model_prob=model_prob,
                    model_fair_cents=model_fair,
                    model_edge_cents=model_edge,
                    implied_vol=iv_used,
                    fear_greed_value=fg.get("value"),
                    fear_greed_label=fg.get("label"),
                )
                session.add(opp)

            upserted += 1

        session.commit()

    _prune_settled(session)
    return upserted


async def _fetch_events(kalshi: KalshiClient, series_ticker: str) -> list[dict]:
    result = await kalshi._request("GET", f"/events?series_ticker={series_ticker}&status=open&limit=20")
    return result.get("events", [])


def _pick_best_contract(markets: list[dict], spot: float | None) -> dict | None:
    scored = []
    for m in markets:
        vol = float(m.get("volume_fp", "0") or "0")
        liq = float(m.get("liquidity_dollars", "0") or "0")
        bid_size = float(m.get("yes_bid_size_fp", "0") or "0")

        strike = _parse_strike(m)
        edge_bonus = 0.0
        if spot and strike:
            pct_diff = abs(spot - strike) / strike * 100
            if pct_diff < 10:
                edge_bonus = 20 - pct_diff

        score = vol * 0.3 + liq * 0.3 + bid_size * 10 + edge_bonus * 5
        scored.append((score, m))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _prune_settled(session: Session):
    from sqlalchemy import update
    from app.models.signal import Signal

    now = datetime.now(timezone.utc)
    all_opps = session.execute(select(Opportunity)).scalars().all()
    for opp in all_opps:
        expired = opp.close_time and datetime.fromisoformat(opp.close_time.replace("Z", "+00:00")) < now
        dead = opp.quality == "low" and opp.volume == 0 and opp.liquidity == 0
        if expired or dead:
            session.execute(
                update(Signal)
                .where(Signal.opportunity_id == opp.id)
                .values(opportunity_id=None)
            )
            session.delete(opp)
    session.commit()
