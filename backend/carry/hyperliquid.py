"""Hyperliquid public data client for the funding-carry harness.

Read-only, unauthenticated info API. US-accessible (DEX). Provides:
  - universe_ctx(): live per-coin funding rate (hourly) + mark price
  - funding_history(coin, hours): recent hourly funding rates (for the gate)

HL funding is paid HOURLY (period = 1h). funding rate is a per-hour fraction.
"""
import json
import logging
import urllib.request

logger = logging.getLogger("carry.hyperliquid")

INFO_URL = "https://api.hyperliquid.xyz/info"
PERIODS_PER_YEAR = 24 * 365  # hourly funding
_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _post(payload: dict, timeout: float = 20.0):
    req = urllib.request.Request(
        INFO_URL, data=json.dumps(payload).encode(), headers=_HEADERS
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def universe_ctx() -> dict[str, dict]:
    """Return {coin: {"funding": hourly_rate, "mark": px, "oracle": px}}.

    Uses metaAndAssetCtxs: [meta, assetCtxs] where assetCtxs[i] aligns with
    meta["universe"][i].
    """
    meta, ctxs = _post({"type": "metaAndAssetCtxs"})
    out: dict[str, dict] = {}
    for asset, ctx in zip(meta.get("universe", []), ctxs):
        name = asset.get("name")
        if not name:
            continue
        try:
            out[name] = {
                "funding": float(ctx.get("funding", 0.0)),
                "mark": float(ctx["markPx"]) if ctx.get("markPx") else None,
                "oracle": float(ctx["oraclePx"]) if ctx.get("oraclePx") else None,
            }
        except (TypeError, ValueError, KeyError):
            continue
    return out


def l2_quote(coin: str) -> tuple[float | None, float | None]:
    """Best (bid, ask) for the perp from the L2 book. None on failure."""
    try:
        d = _post({"type": "l2Book", "coin": coin})
    except Exception:
        logger.warning("l2Book fetch failed for %s", coin)
        return None, None
    levels = d.get("levels")  # [bids, asks], each sorted best-first
    if not levels or len(levels) < 2 or not levels[0] or not levels[1]:
        return None, None
    try:
        return float(levels[0][0]["px"]), float(levels[1][0]["px"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None, None


def funding_history(coin: str, hours: int = 24 * 7) -> list[float]:
    """Recent hourly funding rates for `coin`, oldest->newest."""
    import time
    start = int(time.time() * 1000) - hours * 3600_000
    rows: dict[int, float] = {}
    cur = start
    for _ in range(20):
        try:
            data = _post({"type": "fundingHistory", "coin": coin, "startTime": cur})
        except Exception:
            logger.warning("funding_history fetch failed for %s", coin)
            break
        if not data:
            break
        for d in data:
            rows[int(d["time"])] = float(d["fundingRate"])
        last = max(int(d["time"]) for d in data)
        if last <= cur:
            break
        cur = last + 1
    return [rows[t] for t in sorted(rows)]


def trailing_funding_ann(coin: str, hours: int = 24 * 7) -> float | None:
    """Annualized mean funding over the trailing window (decimal, e.g. 0.15)."""
    rates = funding_history(coin, hours)
    if not rates:
        return None
    return (sum(rates) / len(rates)) * PERIODS_PER_YEAR
