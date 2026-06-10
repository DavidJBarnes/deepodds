"""Coinbase Exchange public spot quotes for the carry's long leg.

US-accessible (Coinbase is the US-compliant venue) and reachable from the prod
EC2. Read-only, unauthenticated — paper harness only models fills off these
quotes; live order placement is a separate (authenticated) adapter.
"""
import json
import logging
import urllib.request

logger = logging.getLogger("carry.coinbase")

PRODUCT = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}


def spot_quote(symbol: str) -> tuple[float | None, float | None]:
    """Best (bid, ask) for the spot product. None on failure/unmapped symbol."""
    product = PRODUCT.get(symbol)
    if not product:
        return None, None
    url = f"https://api.exchange.coinbase.com/products/{product}/ticker"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        return float(d["bid"]), float(d["ask"])
    except Exception:
        logger.warning("coinbase spot_quote failed for %s", symbol)
        return None, None
