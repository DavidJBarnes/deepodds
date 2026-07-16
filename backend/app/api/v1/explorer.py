"""Read-only API for the Edge Explorer.

The explorer daemon (deepodds-explorer) writes a ranked daily `digest_YYYYMMDD.json`
plus an append-only `observations.jsonl` ledger to its own host bind-mount; the api
container mounts that dir read-only and serves it here. Same posture as longshot.py:
env-driven path, defensive reads that never raise, plain-dict payloads, auth-gated. No DB.
"""
import glob
import json
import os

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/explorer", tags=["explorer"])

EXPLORER_DIR = os.environ.get("EXPLORER_DIR", "/explorer-data")


def _read_json(path: str):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _resolutions(explorer_dir: str) -> dict:
    return _read_json(os.path.join(explorer_dir, "resolutions.json")) or {}


def _latest_digest(explorer_dir: str) -> dict | None:
    files = sorted(glob.glob(os.path.join(explorer_dir, "digest_*.json")))
    digest = _read_json(files[-1]) if files else None
    if not digest:
        return digest
    # Drop resolved rules from the served digest so a mid-day verdict takes effect now,
    # not just on the next daemon tick.
    res = _resolutions(explorer_dir)
    obs = [o for o in digest.get("observations", []) if o.get("rule_key") not in res]
    digest["observations"] = obs
    digest["n_observations"] = len(obs)
    return digest


def _read_ledger(explorer_dir: str, limit: int = 500) -> list[dict]:
    path = os.path.join(explorer_dir, "observations.jsonl")
    try:
        with open(path) as fh:
            lines = fh.readlines()[-limit:]
        rows = [json.loads(ln) for ln in lines if ln.strip()]
    except Exception:
        return []
    # Overlay recorded verdicts (non-destructive: observations.jsonl stays append-only).
    res = _resolutions(explorer_dir)
    for r in rows:
        v = res.get(r.get("rule_key"))
        if v:
            r["status"] = v.get("status", "resolved")
            r["resolution_note"] = v.get("note")
    rows.sort(key=lambda r: (r.get("date", ""), r.get("score", 0)), reverse=True)
    return rows


@router.get("/digest")
async def explorer_digest(_user: User = Depends(get_current_user)):
    """The latest daily digest: ranked observations (surprise x persistence) with framing.
    Empty until the explorer daemon has produced at least one tick."""
    digest = _latest_digest(EXPLORER_DIR)
    if digest is None:
        return {"date": None, "n_metrics": 0, "n_observations": 0, "observations": []}
    return digest


@router.get("/ledger")
async def explorer_ledger(_user: User = Depends(get_current_user)):
    """The full observation ledger, newest/highest-score first — every observation ever
    surfaced, with its lifecycle status."""
    return {"observations": _read_ledger(EXPLORER_DIR)}
