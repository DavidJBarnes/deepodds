"""One tick of the LIVE longshot harness.

Same discovery/sizing signal as paper (`paper_run.discover_candidates`), but the
fill is a real Kalshi order and the books (balance/positions/settlements) are the
source of truth (`reconcile`). Every order passes the `RiskGate` first; the kill
switch fails closed.

    python -m longshot.live_run --dry-run   # Phase 1: place nothing, log intent
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from longshot.config import LongshotConfig, load_kalshi_creds
from longshot.kalshi_client import KalshiClient
from longshot.execution import Executor
from longshot.risk import RiskGate, PortfolioRisk, is_killed
from longshot import reconcile
from longshot.paper_run import _load_state, _save_state, discover_candidates

logger = logging.getLogger("longshot.live_run")


def _open_positions(state):
    return [p for p in state.get("positions", []) if p.get("status") == "open"]


def run_once(cfg: LongshotConfig | None = None, dry_run: bool = False) -> dict:
    cfg = cfg or LongshotConfig()
    key_id, pem = load_kalshi_creds()
    client = KalshiClient(key_id, pem)
    now = datetime.now(timezone.utc)
    tick_epoch = int(now.timestamp() // 3600)   # hourly bucket = cross-restart idempotency
    gate = RiskGate(cfg)
    executor = Executor(client, cfg.order_id_prefix, dry_run=dry_run)
    opened = 0

    try:
        state = _load_state(cfg.state_file)
        state.setdefault("positions", [])

        # --- 1. Reconcile against Kalshi truth (settle + adopt orphans) -----
        truth = reconcile.fetch_truth(client)
        settled_now = reconcile.apply_settlements(state, truth["settlements"])
        adopted = reconcile.adopt_orphans(state, truth["positions"], now)
        if adopted:
            logger.error("%d orphan position(s) adopted this tick", adopted)

        # --- 2. Risk pre-tick (kill switch / daily loss) -------------------
        have = {p["ticker"] for p in state["positions"]}
        deployed = sum(p.get("collateral") or 0 for p in _open_positions(state))
        pr = PortfolioRisk(deployed_collateral=deployed,
                           open_positions=len(_open_positions(state)),
                           realized_pnl_today=reconcile.realized_pnl_today(state, now))
        pre = gate.pretick(pr)

        # --- 3. Discover + place (only if allowed) -------------------------
        if pre.allow:
            for c in discover_candidates(cfg, client, now, have, deployed):
                d = gate.check_order(pr, contracts=c["size"], collateral=c["collateral"])
                if not d.allow:
                    logger.info("risk skip %s: %s", c["ticker"], d.reason)
                    continue
                res = executor.place_short(ticker=c["ticker"], sell_price=c["sell_price"],
                                           count=c["size"], tick_epoch=tick_epoch)
                if res.status in ("filled", "partial"):
                    collat = round((1 - res.avg_price) * res.filled_count, 2)
                    state["positions"].append({
                        "ticker": c["ticker"], "series": c["series"],
                        "entry_ts": now.isoformat(), "close_time": c["close_time"],
                        "sell_price": res.avg_price, "size": res.filled_count,
                        "filled_size": res.filled_count, "fee": res.fee,
                        "collateral": collat, "bid_depth_at_entry": c["bid_depth"],
                        "status": "open", "result": None, "pnl": None,
                        # intended-vs-actual for the slippage gate
                        "intended_price": c["sell_price"], "intended_size": c["size"],
                        "avg_fill_price": res.avg_price,
                        "client_order_id": res.client_order_id, "order_id": res.order_id,
                    })
                    pr.deployed_collateral += collat
                    pr.open_positions += 1
                    opened += 1
                elif res.status == "dryrun":
                    opened += 1   # count intents in dry-run for visibility
                else:
                    logger.warning("no fill for %s: %s", c["ticker"], res.status)
        else:
            logger.warning("pretick blocked: %s", pre.reason)

        snap = reconcile.live_snapshot(cfg, state, truth, now)
        snap["opened_this_tick"] = opened
        snap["settled_this_tick"] = settled_now
        snap["killed"] = is_killed(cfg)
        snap["dry_run"] = dry_run
        _save_state(cfg.state_file, state)
        return snap
    finally:
        client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="place no orders; log intended orders only")
    args = ap.parse_args()
    cfg = LongshotConfig()
    snap = run_once(cfg, dry_run=args.dry_run)
    logger.info("live tick: %s", snap)


if __name__ == "__main__":
    main()
