"""Read-only status API for the longshot harnesses.

Each harness (deepodds-longshot = paper, deepodds-longshot-live = live) writes
JSON to its own host bind-mount; the api container mounts both read-only and
serves them here. No DB.
"""
import json
import os

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/longshot", tags=["longshot"])

# Paper harness state (existing).
STATE_FILE = os.environ.get("LONGSHOT_STATE", "/data/state.json")
HISTORY_FILE = os.environ.get("LONGSHOT_HISTORY", "/data/history.jsonl")
HEARTBEAT_FILE = os.environ.get("LONGSHOT_HEARTBEAT", "/data/heartbeat.json")

# Live harness state (separate container / bind-mount).
LIVE_STATE_FILE = os.environ.get("LONGSHOT_LIVE_STATE", "/longshot-live-data/state.json")
LIVE_HISTORY_FILE = os.environ.get("LONGSHOT_LIVE_HISTORY", "/longshot-live-data/history.jsonl")
LIVE_HEARTBEAT_FILE = os.environ.get("LONGSHOT_LIVE_HEARTBEAT", "/longshot-live-data/heartbeat.json")


def _read_json(path: str):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _read_history(path: str, limit: int = 2000) -> list[dict]:
    try:
        with open(path) as fh:
            lines = fh.readlines()[-limit:]
        return [json.loads(ln) for ln in lines if ln.strip()]
    except Exception:
        return []


def _status_payload(state_file: str, history_file: str, heartbeat_file: str) -> dict:
    heartbeat = _read_json(heartbeat_file)
    state = _read_json(state_file)
    history = _read_history(history_file)
    latest = history[-1] if history else None
    series = [
        {"ts": r.get("ts"), "equity": r.get("equity"),
         "settled": r.get("settled_positions"), "hit_rate_no": r.get("hit_rate_no")}
        for r in history if r.get("ts")
    ]
    positions = (state or {}).get("positions", [])
    return {
        "heartbeat": heartbeat,
        "latest": latest,
        "series": series,
        "open_positions": [p for p in positions if p.get("status") == "open"],
        "settled_positions": [p for p in positions if p.get("status") == "settled"],
    }


@router.get("/status")
async def longshot_status(_user: User = Depends(get_current_user)):
    """Paper harness: liveness + latest snapshot + equity/hit-rate series + positions."""
    return _status_payload(STATE_FILE, HISTORY_FILE, HEARTBEAT_FILE)


@router.get("/live/status")
async def longshot_live_status(_user: User = Depends(get_current_user)):
    """Live harness: same shape; latest snapshot carries balance + slippage stats.
    Empty/absent until the live container is armed (Phase 3)."""
    return _status_payload(LIVE_STATE_FILE, LIVE_HISTORY_FILE, LIVE_HEARTBEAT_FILE)
