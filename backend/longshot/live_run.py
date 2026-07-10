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
from longshot import paper_run
from longshot.paper_run import _load_state, _save_state, size_candidate

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
        healed = reconcile.heal_settled_pnl(state)   # self-correct any stale-booked pnl
        if healed:
            logger.warning("healed %d stale settled-pnl record(s)", healed)
        adopted = reconcile.adopt_orphans(state, truth["positions"], now)
        if adopted:
            logger.error("%d orphan position(s) adopted this tick", adopted)

        # --- 2. Risk pre-tick (kill switch / daily loss) -------------------
        # Capital base is the REAL Kalshi balance — never the hardcoded account.
        balance = truth.get("balance_dollars")
        have = {p["ticker"] for p in state["positions"]}
        deployed = sum(p.get("collateral") or 0 for p in _open_positions(state))
        pr = PortfolioRisk(deployed_collateral=deployed,
                           open_positions=len(_open_positions(state)),
                           realized_pnl_today=reconcile.realized_pnl_today(state, now),
                           available_balance=balance)
        pre = gate.pretick(pr)
        if balance is None:
            logger.warning("no Kalshi balance this tick — skipping discovery (can't size safely)")

        # --- 3. Discover + place, INTERLEAVED per series ------------------
        # Fetch each series and place its orders immediately, so the price we
        # send is the price we just read (avoids the stale-quote 400s that the
        # fetch-all-then-place pattern caused).
        dbu = paper_run.deployed_by_underlying(state["positions"])  # per-correlation-group open collateral
        surfaces = paper_run._oracle_surfaces(cfg)   # None=off, dict=on, []=fail-closed
        if surfaces == []:
            logger.warning("oracle gate on but Deribit unreachable — no discovery this tick")
        if pre.allow and balance is not None and surfaces != []:
            for series in sorted(set(cfg.whitelist)):
                try:
                    r = client.get("/markets", params={"series_ticker": series,
                                                       "status": "open", "limit": 100})
                except Exception as e:
                    logger.debug("%s: %s", series, e)
                    continue
                for m in r.get("markets", []):
                    if m["ticker"] in have:
                        continue
                    if surfaces is not None and not paper_run._oracle.market_passes(
                            surfaces, m, now, cfg.oracle_min_edge, cfg.oracle_min_otm):
                        continue
                    c = size_candidate(cfg, m, series, now, balance, pr.deployed_collateral)
                    if not c:
                        continue
                    if cfg.max_underlying_collateral > 0:
                        uk = paper_run.underlying_key(c["ticker"])
                        if dbu.get(uk, 0.0) + c["collateral"] > cfg.max_underlying_collateral:
                            logger.info("underlying cap skip %s (%s)", c["ticker"], uk)
                            continue
                    d = gate.check_order(pr, contracts=c["size"], collateral=c["collateral"])
                    if not d.allow:
                        logger.info("risk skip %s: %s", c["ticker"], d.reason)
                        continue
                    res = executor.place_short(ticker=c["ticker"], sell_price=c["sell_price"],
                                               count=c["size"], tick_epoch=tick_epoch)
                    have.add(c["ticker"])
                    if res.status in ("filled", "partial"):
                        collat = round((1 - res.avg_price) * res.filled_count, 2)
                        state["positions"].append({
                            "ticker": c["ticker"], "series": c["series"],
                            "entry_ts": now.isoformat(), "close_time": c["close_time"],
                            "sell_price": res.avg_price, "size": res.filled_count,
                            "filled_size": res.filled_count, "fee": res.fee,
                            "collateral": collat, "bid_depth_at_entry": c["bid_depth"],
                            "entry_oi": c["open_interest"],
                            "status": "open", "result": None, "pnl": None,
                            "intended_price": c["sell_price"], "intended_size": c["size"],
                            "avg_fill_price": res.avg_price,
                            "client_order_id": res.client_order_id, "order_id": res.order_id,
                        })
                        pr.deployed_collateral += collat
                        pr.open_positions += 1
                        dbu[paper_run.underlying_key(c["ticker"])] = \
                            dbu.get(paper_run.underlying_key(c["ticker"]), 0.0) + collat
                        opened += 1
                    elif res.status == "dryrun":
                        opened += 1
                    else:
                        logger.warning("no fill for %s: %s", c["ticker"], res.status)
        else:
            logger.warning("pretick blocked: %s", pre.reason)

        # Re-fetch balance AFTER placing orders. The start-of-tick balance predates this
        # tick's fills; placing a short moves cash->collateral 1:1, so pairing the stale
        # (higher) balance with the fresh (higher) deployed collateral double-counts each
        # new order and INFLATES equity. Re-read so equity = post-fill cash + deployed.
        if opened and not dry_run:
            try:
                truth["balance_dollars"] = float(client.get_balance().get("balance", 0)) / 100.0
            except Exception as e:
                logger.debug("post-fill balance refetch failed, keeping start-of-tick: %s", e)

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
