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
_MAD_FLOOR = 1e-9        # below this a dispersion estimate counts as zero (see robust_z)
_REL_FLOOR = 0.01        # last-resort scale: 1% of the metric's own magnitude
_ABS_FLOOR = 1e-6        # ...and a hard floor for metrics whose median is ~0
Z_CAP = 25.0             # ranking cap: past ~25 sigma "more extreme" carries no extra
                         # information, but an uncapped z permanently owns rank 1


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


def _stdev(xs: list[float], med: float) -> float:
    """Population sigma about the median. Non-robust by design — only used when MAD has
    degenerated to zero, where it is the *less* degenerate of the two estimators."""
    if len(xs) < 2:
        return 0.0
    return (sum((x - med) ** 2 for x in xs) / len(xs)) ** 0.5


def robust_z(value: float, prior: list[float]) -> dict | None:
    """z of `value` vs the prior distribution via median/MAD. None if too little history.

    MAD is zero whenever *more than half* the baseline is one repeated value — routine
    here, since a stuck metric (a dead recorder banking 0.0 for two weeks) is exactly the
    condition we most want to score. Dividing by a bare epsilon in that case produced
    z ~ 1e9: dq.bookrec.populated_frac went 0.0 -> 1.0 when the bookrec key rename was
    fixed (#231) and pinned rank 1 of the digest at 2.6e9 for five straight days, burying
    every real observation beneath a metric that had just gone *healthy*.

    So the scale falls back in order — MAD, then sigma-about-the-median (degenerate only
    for a truly constant series), then a floor relative to the metric's own magnitude —
    and the result is capped. Recovery-from-stuck now scores ~2.4 sigma (under threshold,
    correctly silent) instead of a billion.
    """
    if len(prior) < MIN_HISTORY:
        return None
    med = _median(prior)
    mad = _median([abs(x - med) for x in prior])
    scale = 1.4826 * mad
    if scale <= _MAD_FLOOR:
        scale = _stdev(prior, med)
    if scale <= _MAD_FLOOR:                       # constant series: no dispersion at all
        scale = max(_REL_FLOOR * abs(med), _ABS_FLOOR)
    z = (value - med) / scale
    z = max(-Z_CAP, min(Z_CAP, z))
    return {"z": z, "median": med, "mad": mad, "n": len(prior)}
