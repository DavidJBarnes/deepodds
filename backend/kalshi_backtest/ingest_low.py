"""
Longshot test — re-ingest the CHEAP band (mid 1-25c) that the favorites ingest
discarded (PRICE_FLOOR_CENTS=75), resolve settlements, and stress the seller-side
edge (sell YES on overpriced longshots) at mid vs daily-low (pessimistic bid fill).

Scoped to the validation window 2025-07-01 → 2025-12-03 to keep the download cheap.
Writes to a separate shard dir / manifest so it never touches the favorites data.

    KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=... \
        uv run python -m kalshi_backtest.ingest_low
"""
import logging
import math
from collections import defaultdict
from datetime import date

import kalshi_backtest.ingest_s3 as I

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("ingest_low")

# Redirect storage + widen band to the cheap longshot range
I.SHARD_DIR = I.DATA_DIR / "s3_markets_low"
I.MANIFEST = I.DATA_DIR / "s3_manifest_low.json"
I.PRICE_FLOOR_CENTS = 1
I.PRICE_CEIL_CENTS = 25

VAL_START = date(2025, 7, 1)
VAL_END = date(2025, 12, 3)
BUCKETS = [(1, 5), (5, 10), (10, 15), (15, 20), (20, 25)]


def _bucket(pc):
    for lo, hi in BUCKETS:
        if lo <= pc < hi:
            return f"{lo}-{hi}c"
    return None


def main():
    from kalshi_backtest.ingest import KalshiClient, fetch_historical_cutoff, _load_creds

    # 1) Re-ingest cheap band, validation window only
    logger.info("Ingesting cheap band [1,25]c for %s → %s", VAL_START, VAL_END)
    I.run_ingest(start=VAL_START, end=VAL_END)

    rows = I.load_s3_shards(start=VAL_START)
    logger.info("Loaded %d cheap-band rows", len(rows))
    if not rows:
        logger.error("No cheap-band rows — aborting")
        return

    # 2) Scope + resolve settlements (non-parlay, lifetime vol>=500, ever in band)
    vol = defaultdict(float)
    parlay = {}
    for r in rows:
        t = r["ticker_name"]
        parlay[t] = I._is_parlay(r["report_ticker"])
        vol[t] += float(r.get("daily_volume") or 0)
    tickers = [t for t in vol if not parlay[t] and vol[t] >= 500]
    logger.info("Cheap-band tradeable tickers to resolve: %d", len(tickers))

    key_id, pem = _load_creds()
    client = KalshiClient(key_id, pem)
    cutoff = fetch_historical_cutoff(client)
    settle = I.resolve_settlements(tickers, client, cutoff)
    client.close()

    # 3) Seller-side fill stress (1d horizon, validation window)
    hists = I.build_market_histories(rows)
    for fill in ("mid", "low"):
        d = defaultdict(lambda: [0, 0, 0.0])  # bucket -> [n_yes, n, sum_sellpx]
        for t, h in hists.items():
            if parlay.get(t) or vol.get(t, 0) < 500:
                continue
            if settle.get(t) not in ("yes", "no"):
                continue
            active = [r for r in h if float(r.get("daily_volume") or 0) > 0
                      or float(r.get("open_interest") or 0) > 0]
            if len(active) < 2:
                continue
            er = active[len(active) - 2]  # 1d horizon
            hi = int(er.get("high_cents") or 0)
            lo = int(er.get("low_cents") or 0)
            if hi <= 0 and lo <= 0:
                continue
            mid = (hi + lo) / 2
            b = _bucket(mid)
            if b is None:
                continue
            sell = (mid / 100) if fill == "mid" else (lo / 100)  # seller fills at bid≈low
            if sell <= 0:
                continue
            y = 1 if settle[t] == "yes" else 0
            d[b][0] += y
            d[b][1] += 1
            d[b][2] += sell

        print(f"\n=== SHORT longshots: sell YES at daily {fill} (1d, validation) ===")
        print(f'{"bucket":8} {"n":>5} {"sellPx":>7} {"realizedYes":>11} {"edge/ct":>8} {"CI95lo":>8}')
        for lo_, hi_ in BUCKETS:
            b = f"{lo_}-{hi_}c"
            if b not in d:
                continue
            ny, nt, ss = d[b]
            if nt < 30:
                print(f"{b:8} {nt:5d}   (n<30, skipped)")
                continue
            sp = ss / nt
            real = ny / nt
            edge = sp - real  # collect sp, pay 1*real
            sd = math.sqrt(real * (1 - real) / nt)
            print(f"{b:8} {nt:5d} {sp:7.3f} {real:11.3f} {edge:+8.3f} {edge - 1.96*sd:+8.3f}")

    logger.info("DONE")


if __name__ == "__main__":
    main()
