"""Continuous longshot paper loop. Mirrors carry/loop.py: interval ticks,
graceful SIGTERM/SIGINT, per-tick error isolation, heartbeat + append-only
JSONL history. State persists in a host bind-mount (NOT a named volume) so the
deploy's `docker system prune --volumes` never wipes it.

    python -m longshot.loop --interval 3600
    python -m longshot.loop --interval 5 --max-ticks 1   # bounded (validation)
"""
import argparse
import json
import logging
import os
import signal
import time

from longshot.config import LongshotConfig
from longshot.paper_run import print_snapshot, run_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("longshot.loop")

_STOP = False


def _handle_signal(signum, _frame):
    global _STOP
    _STOP = True
    logger.info("signal %s received — finishing current tick then stopping", signum)


def _append_history(path: str, snap: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(snap) + "\n")


def _write_heartbeat(path: str, snap: dict, status: str, err: str | None = None) -> None:
    hb = {
        "wall_ts": time.time(),
        "tick_ts": snap.get("ts") if snap else None,
        "status": status,
        "equity": snap.get("equity") if snap else None,
        "open_positions": snap.get("open_positions") if snap else None,
        "error": err,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(hb, fh)
    os.replace(tmp, path)


def run_loop(cfg: LongshotConfig, interval: int, max_ticks: int | None = None) -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("longshot loop start: interval=%ss max_ticks=%s whitelist=%d series",
                interval, max_ticks, len(cfg.whitelist))
    ticks = 0
    while not _STOP:
        t0 = time.monotonic()
        try:
            snap = run_once(cfg)
            _append_history(cfg.history_file, snap)
            _write_heartbeat(cfg.heartbeat_file, snap, "ok")
            print_snapshot(snap)
        except Exception as e:
            logger.exception("tick failed")
            _write_heartbeat(cfg.heartbeat_file, {}, "error", repr(e))
        ticks += 1
        if max_ticks and ticks >= max_ticks:
            logger.info("reached max_ticks=%d — stopping", max_ticks)
            break
        if _STOP:
            break
        sleep = max(0.0, interval - (time.monotonic() - t0))
        slept = 0.0
        while slept < sleep and not _STOP:
            time.sleep(min(1.0, sleep - slept))
            slept += 1.0
    logger.info("longshot loop stopped after %d ticks", ticks)
    return ticks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=3600)
    ap.add_argument("--max-ticks", type=int, default=None)
    args = ap.parse_args()
    run_loop(LongshotConfig(), args.interval, args.max_ticks)


if __name__ == "__main__":
    main()
