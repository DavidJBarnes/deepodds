"""Rebuild metrics_history for the windowed / constant-maturity metrics from raw sources.

Those metrics replaced artifacted v1 series under NEW keys (see metrics.py), so they
start with no baseline. Every input they need is retained on the box — resolved.jsonl
(timestamped settlements), the longshot tick histories, and one Deribit chain file per
day — so their history can be recomputed as-of each past day instead of waited for.

    python -m explorer.backfill --out /data --since 2026-07-04

Appends only (date, key) rows not already stored, so it's safe to re-run. Never touches
the ledger or digests — it only gives the baselines their history. Re-run the daemon once
afterwards (`python -m explorer.daemon --out /data`) to re-score today's digest.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

from explorer import baseline, metrics as M, sources

logger = logging.getLogger("explorer.backfill")

RUN_HOUR_UTC = 15  # the daemon's daily tick lands ~15:06 UTC


def metrics_as_of(day: date) -> list:
    """The as-of-`day` panel for every family that can be recomputed historically.
    Open-snapshot gap and bookrec health read 'latest file' state and are excluded."""
    now = datetime.combine(day, time(RUN_HOUR_UTC), tzinfo=timezone.utc)
    out: list = []
    for fam in (lambda: M.oracle_metrics(now, open_snaps=False),
                lambda: M.longshot_metrics(now),
                lambda: M.deribit_metrics(now, sources.deribit_chain_for(day.isoformat()))):
        try:
            out.extend(fam())
        except Exception as e:
            logger.warning("backfill %s: family failed: %s", day, e)
    return out


def backfill(out_dir: str, since: date, until: date) -> int:
    # The sources re-read whole files per call; cache them for the run (one parse each
    # instead of one per day — resolved.jsonl alone is ~25k rows).
    orig = sources.resolved_tails, sources.longshot_history
    sources.resolved_tails = lru_cache(maxsize=None)(orig[0])
    sources.longshot_history = lru_cache(maxsize=None)(orig[1])
    try:
        hist = baseline.load_history(out_dir)
        written = 0
        d = since
        while d <= until:
            written += baseline.append_metrics(out_dir, d.isoformat(), metrics_as_of(d), hist)
            d += timedelta(days=1)
        return written
    finally:
        sources.resolved_tails, sources.longshot_history = orig


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.environ.get("EXPLORER_DATA_DIR", "/data"))
    ap.add_argument("--since", required=True, type=date.fromisoformat)
    ap.add_argument("--until", type=date.fromisoformat,
                    default=datetime.now(timezone.utc).date() - timedelta(days=1))
    args = ap.parse_args()
    n = backfill(args.out, args.since, args.until)
    logger.info("backfilled %d metric rows %s..%s", n, args.since, args.until)


if __name__ == "__main__":
    main()
