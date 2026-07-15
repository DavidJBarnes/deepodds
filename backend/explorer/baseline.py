"""Per-metric time-series store + robust surprise scoring.

Each daily run appends (date, key, value) rows to `metrics_history.jsonl` (idempotent
per (date, key), so a same-day re-run doesn't duplicate). A metric's surprise today is a
robust z-score against its OWN prior values — median / MAD, not mean / std, so a single
wild day doesn't poison the baseline it's measured against. With only a handful of days
of history the tool flags conservatively (MIN_HISTORY gate) and sharpens as history grows.
"""
from __future__ import annotations

import json
import os

MIN_HISTORY = 3          # need at least this many prior days to score a deviation
_MAD_FLOOR = 1e-9        # guard against zero-dispersion division


def history_path(out_dir: str) -> str:
    return os.path.join(out_dir, "metrics_history.jsonl")


def load_history(out_dir: str) -> list[dict]:
    p = history_path(out_dir)
    out = []
    try:
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
    except Exception:
        return []
    return out


def append_metrics(out_dir: str, date: str, metrics: list, history: list[dict]) -> int:
    """Append today's (date, key, value) rows, skipping keys already stored for `date`
    (idempotent same-day re-run). Returns count newly written."""
    os.makedirs(out_dir, exist_ok=True)
    have = {(r.get("date"), r.get("key")) for r in history}
    new = []
    for m in metrics:
        if (date, m.key) in have:
            continue
        new.append({"date": date, "key": m.key, "value": m.value})
    if new:
        with open(history_path(out_dir), "a") as fh:
            for r in new:
                fh.write(json.dumps(r) + "\n")
        history.extend(new)
    return len(new)


def prior_values(history: list[dict], key: str, before_date: str) -> list[float]:
    return [r["value"] for r in history
            if r.get("key") == key and r.get("date", "") < before_date and r.get("value") is not None]


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2


def robust_z(value: float, prior: list[float]) -> dict | None:
    """z of `value` vs the prior distribution via median/MAD. None if too little history."""
    if len(prior) < MIN_HISTORY:
        return None
    med = _median(prior)
    mad = _median([abs(x - med) for x in prior])
    scale = 1.4826 * mad if mad > _MAD_FLOOR else _MAD_FLOOR
    return {"z": (value - med) / scale, "median": med, "mad": mad, "n": len(prior)}
