"""Read-only status API for the longshot paper harness.

The longshot loop (deepodds-longshot container) writes JSON to a host bind-mount;
the api container mounts the same dir read-only and serves it here. No DB.
"""
import json
import os

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/longshot", tags=["longshot"])

STATE_FILE = os.environ.get("LONGSHOT_STATE", "/data/state.json")
HISTORY_FILE = os.environ.get("LONGSHOT_HISTORY", "/data/history.jsonl")
HEARTBEAT_FILE = os.environ.get("LONGSHOT_HEARTBEAT", "/data/heartbeat.json")


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


@router.get("/status")
async def longshot_status(_user: User = Depends(get_current_user)):
    """Liveness + latest snapshot + equity/hit-rate series + positions."""
    heartbeat = _read_json(HEARTBEAT_FILE)
    state = _read_json(STATE_FILE)
    history = _read_history(HISTORY_FILE)
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
