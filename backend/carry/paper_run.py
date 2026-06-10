"""Run one paper tick of the funding-carry harness against live Hyperliquid
data, persisting portfolio state between invocations.

Usage:
    python -m carry.paper_run            # one tick + status
    python -m carry.paper_run --loop 3600  # tick every N seconds
Env: CARRY_STATE=/path/to/state.json (default /tmp/carry_paper_state.json)
"""
import dataclasses
import json
import logging
import os
import time

from carry.config import CarryConfig
from carry.engine import build_snapshot, tick
from carry.hyperliquid import trailing_funding_ann, universe_ctx
from carry.models import CarryPosition, PaperPortfolio

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("carry.paper")

STATE_FILE = os.environ.get("CARRY_STATE", "/tmp/carry_paper_state.json")


def load(cfg: CarryConfig) -> PaperPortfolio:
    if not os.path.exists(STATE_FILE):
        return PaperPortfolio(cash_usd=cfg.paper_capital_usd)
    with open(STATE_FILE) as fh:
        d = json.load(fh)
    pf = PaperPortfolio(
        cash_usd=d["cash_usd"], realized_pnl=d["realized_pnl"],
        accrued_funding_total=d["accrued_funding_total"], fees_total=d["fees_total"],
        killed=d["killed"], last_tick_ts=d["last_tick_ts"], log=d.get("log", []),
    )
    pf.positions = {s: CarryPosition(**p) for s, p in d["positions"].items()}
    return pf


def save(pf: PaperPortfolio) -> None:
    d = dataclasses.asdict(pf)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh, indent=2)
    os.replace(tmp, STATE_FILE)


def run_once(cfg: CarryConfig) -> dict:
    """Stateless tick: load -> fetch live HL -> tick -> save. Returns snapshot."""
    pf = load(cfg)
    ctx_all = universe_ctx()
    ctx = {s: ctx_all[s] for s in cfg.symbols if s in ctx_all}
    trailing = {s: trailing_funding_ann(s, cfg.trailing_window_hours) for s in cfg.symbols}
    tick(pf, ctx, trailing, cfg, time.time())
    save(pf)
    snap = build_snapshot(pf, ctx, trailing, cfg)
    snap["log_tail"] = pf.log[-5:]
    return snap


def print_snapshot(snap: dict) -> None:
    print("\n=== Funding-carry paper status ===")
    print(f"{'sym':5s} {'fundNow%/yr':>11s} {'trail%/yr':>11s} {'target$':>8s} {'position':>26s}")
    for s, d in snap["symbols"].items():
        tr = d["trailing_ann"]
        trs = f"{tr*100:+.1f}" if tr is not None else "n/a"
        if d["notional"]:
            poss = f"${d['notional']:.0f} mr={d['margin_ratio']:.2f} fund=${d['accrued_funding']:.4f}"
        else:
            poss = "flat"
        print(f"{s:5s} {d['funding_ann']*100:+11.1f} {trs:>11s} {d['target']:8.0f} {poss:>26s}")
    print(f"\ncash=${snap['cash']:.2f}  equity=${snap['equity']:.2f}  "
          f"accrued_funding=${snap['accrued_funding_total']:.4f}  realized=${snap['realized_pnl']:.2f}  "
          f"fees=${snap['fees_total']:.2f}  killed={snap['killed']}")
    for line in snap.get("log_tail", []):
        print(f"  · {line}")


def main() -> None:
    """One-shot tick + status. For the continuous loop use `python -m carry.loop`."""
    print_snapshot(run_once(CarryConfig()))


if __name__ == "__main__":
    main()
