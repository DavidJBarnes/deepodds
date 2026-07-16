"""Orchestrate a daily tick: compute metrics, apply rules, rank, and persist.

Outputs in the out dir:
  metrics_history.jsonl   append-only (date,key,value) series feeding baselines
  observations.jsonl      the durable ledger — append-only, idempotent per (date,rule)
  digest_YYYYMMDD.json    the ranked top-N for that day (rewritten each run) — API source

Ranking = surprise x persistence: score = surprise * (1 + ln(streak)), where streak is
the count of trailing consecutive daily runs (incl. today) in which the same rule fired.
A one-off blip (streak 1) sits below a repeat surprise; that is the free out-of-sample
filter that keeps the digest honest.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone

from explorer import baseline, metrics as metrics_mod, rules

DIGEST_TOP_N = 12
# Rules that should land in the ledger pre-marked (else default "new").
STATUS_DEFAULTS = {"oracle.tail_thesis_inverted": "investigate"}


def _streak(prior_dates: set[str], today: str) -> int:
    try:
        d = date.fromisoformat(today)
    except Exception:
        return 1
    n = 1
    while True:
        d = d - timedelta(days=1)
        if d.isoformat() in prior_dates:
            n += 1
        else:
            return n


def _load_ledger(out_dir: str) -> list[dict]:
    p = os.path.join(out_dir, "observations.jsonl")
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


def _dates_by_rule(ledger: list[dict]) -> dict[str, set]:
    by: dict[str, set] = {}
    for r in ledger:
        by.setdefault(r.get("rule_key"), set()).add(r.get("date"))
    return by


def load_resolutions(out_dir: str) -> dict:
    """Verdicts marked on observations: {rule_key: {status, note, resolved_ts}}. A
    resolved rule stops surfacing in the daily digest (it's understood, not open) and
    stops appending new ledger rows, but its history and verdict remain readable."""
    try:
        with open(os.path.join(out_dir, "resolutions.json")) as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def generate_observations(out_dir: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    os.makedirs(out_dir, exist_ok=True)

    # 1. metrics + persist the day's series (idempotent)
    hist = baseline.load_history(out_dir)
    metrics = metrics_mod.all_metrics(now)
    baseline.append_metrics(out_dir, today, metrics, hist)

    # 2. apply rules -> observations
    fired: list[dict] = []
    structural_keys: set[str] = set()
    for m in metrics:
        for obs in rules.structural_rules(m):
            fired.append(obs)
            structural_keys.add(m.key)
    for m in metrics:
        if m.key in structural_keys:
            continue  # a structural rule already spoke for this metric today
        z_info = baseline.robust_z(m.value, baseline.prior_values(hist, m.key, today))
        obs = rules.deviation_rule(m, z_info)
        if obs:
            fired.append(obs)

    # 3. streak + score, then append to the ledger (idempotent per date:rule_key).
    # Resolved rules (a recorded verdict) drop out of the active flow entirely.
    resolved = set(load_resolutions(out_dir))
    ledger = _load_ledger(out_dir)
    have_ids = {r.get("id") for r in ledger}
    by_rule = _dates_by_rule(ledger)
    records = []
    for obs in fired:
        rk = obs["rule_key"]
        oid = f"{today}:{rk}"
        streak = _streak(by_rule.get(rk, set()), today)
        score = obs["surprise"] * (1 + math.log(streak))
        rec = {"id": oid, "date": today, "streak": streak, "score": round(score, 3),
               "status": STATUS_DEFAULTS.get(rk, "new"),
               "created_ts": now.isoformat(), **obs}
        if oid not in have_ids and rk not in resolved:
            records.append(rec)
        # rank on the freshly computed values regardless of whether it's new to the ledger
        obs["_rank"] = {"streak": streak, "score": round(score, 3), "id": oid,
                        "status": STATUS_DEFAULTS.get(rk, "new")}

    if records:
        with open(os.path.join(out_dir, "observations.jsonl"), "a") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    # 4. ranked digest for today (rewritten each run) — resolved rules excluded (they
    # are understood, not open questions); they remain in the ledger with their verdict.
    active = [o for o in fired if o["rule_key"] not in resolved]
    ranked = sorted(active, key=lambda o: o["_rank"]["score"], reverse=True)[:DIGEST_TOP_N]
    digest = {
        "date": today,
        "generated_ts": now.isoformat(),
        "n_metrics": len(metrics),
        "n_observations": len(active),
        "n_resolved": len(fired) - len(active),
        "observations": [{
            "id": o["_rank"]["id"], "rule_key": o["rule_key"], "metric_key": o["metric_key"],
            "value": o["value"], "kind": o["kind"], "status": o["_rank"]["status"],
            "streak": o["_rank"]["streak"], "score": o["_rank"]["score"],
            "what": o["what"], "why_notable": o["why_notable"],
            "next_step": o["next_step"], "caveat": o["caveat"],
        } for o in ranked],
    }
    with open(os.path.join(out_dir, f"digest_{today}.json"), "w") as fh:
        json.dump(digest, fh, indent=2)

    return {"date": today, "n_metrics": len(metrics),
            "n_observations": len(active), "n_new_ledger": len(records)}
