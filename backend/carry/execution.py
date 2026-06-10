"""Cross-venue market context for the carry harness.

Assembles, per symbol, the live two-venue picture the engine needs:
  - funding (HL hourly) + mark/oracle (HL)
  - perp bid/ask  (Hyperliquid L2)  -> short fills at perp_bid, buys back at perp_ask
  - spot bid/ask  (Coinbase)        -> long fills at spot_ask,  sells at spot_bid

Captures the real costs the single-mark model ignored: perp spread and the
perp-vs-spot basis. Falls back to oracle +/- a modeled spread if a spot quote
is unavailable, so a Coinbase hiccup degrades gracefully rather than halting.
"""
import logging

from carry import coinbase
from carry.config import CarryConfig
from carry.hyperliquid import l2_quote, universe_ctx

logger = logging.getLogger("carry.execution")


def market_ctx(symbols: list[str], cfg: CarryConfig) -> dict[str, dict]:
    uni = universe_ctx()
    out: dict[str, dict] = {}
    for s in symbols:
        u = uni.get(s)
        if not u or u.get("mark") is None:
            logger.warning("no HL ctx for %s — skipping", s)
            continue
        mark = u["mark"]
        oracle = u.get("oracle") or mark
        perp_bid, perp_ask = l2_quote(s)
        spot_bid, spot_ask = coinbase.spot_quote(s)
        if spot_bid is None or spot_ask is None:
            half = cfg.spot_spread_bps / 10_000 * oracle
            spot_bid, spot_ask = oracle - half, oracle + half
            logger.info("%s spot fallback: oracle +/- %.1fbps", s, cfg.spot_spread_bps)
        out[s] = {
            "funding": u["funding"],
            "mark": mark,
            "oracle": oracle,
            "perp_bid": perp_bid if perp_bid is not None else mark,
            "perp_ask": perp_ask if perp_ask is not None else mark,
            "spot_bid": spot_bid,
            "spot_ask": spot_ask,
        }
    return out


def entry_fills(c: dict) -> tuple[float, float]:
    """(perp short fill, spot long fill) = (perp_bid, spot_ask)."""
    return c["perp_bid"], c["spot_ask"]


def exit_fills(c: dict) -> tuple[float, float]:
    """(perp buy-back fill, spot sell fill) = (perp_ask, spot_bid)."""
    return c["perp_ask"], c["spot_bid"]
