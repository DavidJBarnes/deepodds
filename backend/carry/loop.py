"""Continuous funding-carry paper loop.

Runs run_once() on an interval with: graceful SIGTERM/SIGINT shutdown,
per-tick error isolation (a bad tick never kills the loop), a heartbeat file
(liveness), and an append-only per-tick history (JSONL) so the numbers —
equity, accrued funding, per-symbol state — are auditable over time.

Usage:
    python -m carry.loop                      # tick every 600s forever
    python -m carry.loop --interval 300
    python -m carry.loop --interval 5 --max-ticks 4   # bounded (validation)
Env: CARRY_STATE, CARRY_HISTORY, CARRY_HEARTBEAT (defaults under /tmp).
"""
import argparse
import json
import logging
import os
import signal
import time

from carry.config import CarryConfig
from carry.paper_run import print_snapshot, run_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("carry.loop")

HISTORY_FILE = os.environ.get("CARRY_HISTORY", "/tmp/carry_paper_history.jsonl")
HEARTBEAT_FILE = os.environ.get("CARRY_HEARTBEAT", "/tmp/carry_paper_heartbeat.json")

_STOP = False


def _handle_signal(signum, _frame):
    global _STOP
    _STOP = True
    logger.info("signal %s received — finishing current tick then stopping", signum)


def _append_history(snap: dict) -> None:
    rec = {k: v for k, v in snap.items() if k != "log_tail"}
    with open(HISTORY_FILE, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def _write_heartbeat(snap: dict, status: str, err: str | None = None) -> None:
    hb = {
        "wall_ts": time.time(),
        "tick_ts": snap.get("ts") if snap else None,
        "status": status,
        "equity": snap.get("equity") if snap else None,
        "killed": snap.get("killed") if snap else None,
        "error": err,
    }
    tmp = HEARTBEAT_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(hb, fh)
    os.replace(tmp, HEARTBEAT_FILE)


def run_loop(cfg: CarryConfig, interval: int, max_ticks: int | None = None) -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("carry loop start: interval=%ss max_ticks=%s symbols=%s",
                interval, max_ticks, cfg.symbols)
    ticks = 0
    while not _STOP:
        t0 = time.monotonic()
        try:
            snap = run_once(cfg)
            _append_history(snap)
            _write_heartbeat(snap, "ok")
            print_snapshot(snap)
            if snap["killed"]:
                ticks += 1
                logger.error("kill-switch tripped — stopping loop")
                break
        except Exception as e:
            logger.exception("tick failed")
            _write_heartbeat({}, "error", repr(e))
        ticks += 1
        if max_ticks and ticks >= max_ticks:
            logger.info("reached max_ticks=%d — stopping", max_ticks)
            break
        if _STOP:
            break
        sleep = max(0.0, interval - (time.monotonic() - t0))
        # interruptible sleep so signals stop us promptly
        slept = 0.0
        while slept < sleep and not _STOP:
            time.sleep(min(1.0, sleep - slept))
            slept += 1.0
    logger.info("carry loop stopped after %d ticks", ticks)
    return ticks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--max-ticks", type=int, default=None)
    args = ap.parse_args()
    run_loop(CarryConfig(), args.interval, args.max_ticks)


if __name__ == "__main__":
    main()
