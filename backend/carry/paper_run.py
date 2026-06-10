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
import sys
import time

from carry.config import CarryConfig
from carry.engine import target_notional, tick
from carry.hyperliquid import PERIODS_PER_YEAR, trailing_funding_ann, universe_ctx
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


def run_once(cfg: CarryConfig) -> None:
    pf = load(cfg)
    ctx_all = universe_ctx()
    ctx = {s: ctx_all[s] for s in cfg.symbols if s in ctx_all}
    trailing = {s: trailing_funding_ann(s, cfg.trailing_window_hours) for s in cfg.symbols}
    now = time.time()

    tick(pf, ctx, trailing, cfg, now)
    save(pf)

    marks = {s: c["mark"] for s, c in ctx.items() if c.get("mark")}
    print("\n=== Funding-carry paper status ===")
    print(f"{'sym':5s} {'fundNow%/yr':>11s} {'trail7d%/yr':>11s} {'target$':>8s} {'position':>22s}")
    for s in cfg.symbols:
        c = ctx.get(s, {})
        fn = (c.get("funding") or 0) * PERIODS_PER_YEAR * 100
        tr = trailing.get(s)
        trs = f"{tr*100:+.1f}" if tr is not None else "n/a"
        tgt = target_notional(tr, cfg)
        pos = pf.positions.get(s)
        if pos:
            mark = marks.get(s, pos.entry_perp)
            poss = f"${pos.notional(mark):.0f} mr={pos.margin_ratio(mark):.2f} fund=${pos.accrued_funding:.2f}"
        else:
            poss = "flat"
        print(f"{s:5s} {fn:+11.1f} {trs:>11s} {tgt:8.0f} {poss:>22s}")
    print(f"\ncash=${pf.cash_usd:.2f}  equity=${pf.equity(marks):.2f}  "
          f"accrued_funding=${pf.accrued_funding_total:.2f}  realized=${pf.realized_pnl:.2f}  "
          f"fees=${pf.fees_total:.2f}  killed={pf.killed}")
    for line in pf.log[-5:]:
        print(f"  · {line}")


def main() -> None:
    cfg = CarryConfig()
    if len(sys.argv) >= 3 and sys.argv[1] == "--loop":
        interval = int(sys.argv[2])
        while True:
            try:
                run_once(cfg)
            except Exception:
                logger.exception("paper tick failed")
            time.sleep(interval)
    else:
        run_once(cfg)


if __name__ == "__main__":
    main()
