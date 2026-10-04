"""Edge Explorer daemon — a daily observation tick.

Reads the (read-only-mounted) upstream data dirs, computes the metric panel, applies the
rules, and writes the ledger + digest. Pure file I/O — no Kalshi/Deribit client, no
orders. Mirrors the vrp.oracle_daemon loop shape (run-once-on-start, --loop --interval).

    python -m explorer.daemon --loop --interval 86400 --out /data

On start it backfills missing metric history (explorer.backfill) before the first tick.
"""
from __future__ import annotations

import argparse
import logging
import os
import time

from datetime import datetime, timedelta, timezone

from explorer.backfill import backfill
from explorer.observe import generate_observations

logger = logging.getLogger("explorer.daemon")


def run_once(out_dir: str) -> dict:
    r = generate_observations(out_dir)
    logger.info("explorer tick: metrics=%d observations=%d new_ledger=%d",
                r["n_metrics"], r["n_observations"], r["n_new_ledger"])
    return r


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.environ.get("EXPLORER_DATA_DIR", "/data"))
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=86400)
    ap.add_argument("--backfill-days", type=int, default=100,
                    help="on start, rebuild missing metric history this far back (idempotent; 0=off)")
    args = ap.parse_args()
    if args.backfill_days > 0:
        # New metric keys arrive with no baseline; their inputs are all retained, so fill
        # it before the first tick scores against it. Only missing (date,key) rows are written.
        try:
            today = datetime.now(timezone.utc).date()
            n = backfill(args.out, today - timedelta(days=args.backfill_days), today - timedelta(days=1))
            logger.info("explorer backfill: %d metric rows written", n)
        except Exception as e:
            logger.error("explorer backfill failed: %s", e)
    while True:
        try:
            run_once(args.out)
        except Exception as e:
            logger.error("explorer run failed: %s", e)
        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
