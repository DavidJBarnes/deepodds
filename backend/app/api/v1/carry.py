"""Read-only status API for the funding-carry harness.

The carry loop (deepodds-carry container) writes JSON to a host bind-mount;
the api container mounts the same dir read-only and serves it here. No DB.
"""
import json
import os

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/carry", tags=["carry"])

STATE_FILE = os.environ.get("CARRY_STATE", "/data/state.json")
HISTORY_FILE = os.environ.get("CARRY_HISTORY", "/data/history.jsonl")
HEARTBEAT_FILE = os.environ.get("CARRY_HEARTBEAT", "/data/heartbeat.json")


def _read_json(path: str):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _read_history(path: str, limit: int = 1000) -> list[dict]:
    try:
        with open(path) as fh:
            lines = fh.readlines()[-limit:]
        return [json.loads(ln) for ln in lines if ln.strip()]
    except Exception:
        return []


@router.get("/status")
async def carry_status(_user: User = Depends(get_current_user)):
    """Liveness + latest snapshot + history series + open positions."""
    heartbeat = _read_json(HEARTBEAT_FILE)
    state = _read_json(STATE_FILE)
    history = _read_history(HISTORY_FILE)
    latest = history[-1] if history else None
    series = [
        {"ts": r.get("ts"), "equity": r.get("equity"), "accrued_funding": r.get("accrued_funding_total")}
        for r in history if r.get("ts")
    ]
    return {
        "heartbeat": heartbeat,
        "latest": latest,
        "series": series,
        "positions": (state or {}).get("positions", {}),
    }
