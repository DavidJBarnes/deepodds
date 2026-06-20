"""
Step 1 — de-biased settlement resolution for the cheap (1-25c) band.

The first ~21.7k resolutions were in shard-insertion order (early months,
temperature-heavy). This resolves a RANDOM sample of the remaining cheap-band
universe so the dataset is representative across the full validation window and
all categories. Resumable: resolve_settlements skips anything already cached.

    KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=... \
        uv run python -m kalshi_backtest.resolve_low
"""
import logging
import random
from collections import defaultdict
from datetime import date

import kalshi_backtest.ingest_s3 as I

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("resolve_low")

I.SHARD_DIR = I.DATA_DIR / "s3_markets_low"

TARGET_TOTAL = 55_000   # total resolved tickers we want on disk
SEED = 42


def main():
    from kalshi_backtest.ingest import KalshiClient, fetch_historical_cutoff, _load_creds

    rows = I.load_s3_shards(start=date(2025, 7, 1))
    cache = I.load_settlement_cache()

    vol = defaultdict(float)
    parlay = {}
    for r in rows:
        t = r["ticker_name"]
        parlay[t] = I._is_parlay(r["report_ticker"])
        vol[t] += float(r.get("daily_volume") or 0)
    universe = [t for t in vol if not parlay[t] and vol[t] >= 500]

    cached = [t for t in universe if t in cache]
    uncached = [t for t in universe if t not in cache]
    random.seed(SEED)
    random.shuffle(uncached)

    need = max(0, TARGET_TOTAL - len(cached))
    batch = uncached[:need]
    logger.info("Universe %d | already cached %d | resolving random %d more (target total %d)",
                len(universe), len(cached), len(batch), TARGET_TOTAL)

    if not batch:
        logger.info("Target already met — nothing to resolve.")
        return

    key_id, pem = _load_creds()
    client = KalshiClient(key_id, pem)
    cutoff = fetch_historical_cutoff(client)
    I.resolve_settlements(batch, client, cutoff)
    client.close()
    logger.info("DONE — total cheap-band resolved now ~%d", len(cached) + len(batch))


if __name__ == "__main__":
    main()
