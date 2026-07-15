"""Defensive readers for the upstream data the Explorer observes.

Every reader fails soft: a missing dir, absent file, or unparseable line yields an
empty result, never an exception. One rotten source must never sink a daily tick — the
daemon wraps each metric family in try/except too, but the readers are the first line.

Container mount points (docker-compose.prod.yml `explorer` service), overridable by env
for local runs:
  ORACLE_DIR         /oracle-data       (ro mount of /opt/deepodds/oracle)
  LONGSHOT_PAPER_DIR /longshot-data     (ro mount of /opt/deepodds/longshot)
  LONGSHOT_LIVE_DIR  /longshot-live-data(ro mount of /opt/deepodds/longshot-live)
  DERIBIT_DIR        /vrp-data          (ro mount of /opt/deepodds/vrp-data)
  BOOKREC_DIR        /bookrec-data      (ro mount of /opt/deepodds/bookrec)
"""
from __future__ import annotations

import glob
import json
import os

ORACLE_DIR = os.environ.get("EXPLORER_ORACLE_DIR", "/oracle-data")
LONGSHOT_PAPER_DIR = os.environ.get("EXPLORER_LONGSHOT_PAPER_DIR", "/longshot-data")
LONGSHOT_LIVE_DIR = os.environ.get("EXPLORER_LONGSHOT_LIVE_DIR", "/longshot-live-data")
DERIBIT_DIR = os.environ.get("EXPLORER_DERIBIT_DIR", "/vrp-data")
BOOKREC_DIR = os.environ.get("EXPLORER_BOOKREC_DIR", "/bookrec-data")


def _read_jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def _latest(glob_pat: str) -> str | None:
    files = sorted(glob.glob(glob_pat))
    return files[-1] if files else None


# -- oracle -----------------------------------------------------------------
def resolved_tails(oracle_dir: str = ORACLE_DIR) -> list[dict]:
    """Settled BTC/ETH tails: {ticker, result, kalshi_bid, deribit_fair,
    sell_ev_vs_deribit, realized_pnl, resolved_ts}."""
    return _read_jsonl(os.path.join(oracle_dir, "resolved.jsonl"))


def open_tail_snapshots(oracle_dir: str = ORACLE_DIR) -> list[dict]:
    """Today's captured open-tail snapshots: {ticker, close_time, strike, spot,
    kalshi_bid, kalshi_mid, deribit_fair, gap, sell_ev_vs_deribit, captured_ts}."""
    f = _latest(os.path.join(oracle_dir, "oracle_*.jsonl"))
    return _read_jsonl(f) if f else []


# -- longshot ---------------------------------------------------------------
def longshot_history(live: bool = False, paper_dir: str = LONGSHOT_PAPER_DIR,
                     live_dir: str = LONGSHOT_LIVE_DIR) -> list[dict]:
    """The harness tick history (one row per hourly tick)."""
    d = live_dir if live else paper_dir
    return _read_jsonl(os.path.join(d, "history.jsonl"))


# -- deribit chain ----------------------------------------------------------
def deribit_chain_latest(deribit_dir: str = DERIBIT_DIR) -> list[dict]:
    """The most recent daily full-chain capture (one row per currency)."""
    f = _latest(os.path.join(deribit_dir, "chain_*.jsonl"))
    return _read_jsonl(f) if f else []


# -- bookrec (data-quality only in v1) --------------------------------------
def bookrec_latest_stats(bookrec_dir: str = BOOKREC_DIR) -> dict:
    """Population stats on the most recent book file — used only to surface the
    recorder's health as a data-quality observation (the depth endpoint is dead)."""
    f = _latest(os.path.join(bookrec_dir, "book_*.jsonl"))
    if not f:
        return {"file": None, "total": 0, "populated": 0}
    rows = _read_jsonl(f)
    pop = sum(1 for r in rows if r.get("yes") or r.get("no"))
    return {"file": os.path.basename(f), "total": len(rows), "populated": pop}
