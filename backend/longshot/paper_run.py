"""One tick of the longshot paper harness: resolve matured shorts, then discover
and open new ones against the live Kalshi order book. Pure paper — no orders."""
import json
import logging
import os
from datetime import datetime, timezone

from longshot.kalshi_client import KalshiClient, kalshi_fee_per_contract as fee
from longshot.config import LongshotConfig, load_kalshi_creds

logger = logging.getLogger("longshot.paper_run")


def _load_state(path: str) -> dict:
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {"positions": []}


def _save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)


def _resolve(cfg, client, state, now) -> int:
    settled = 0
    for p in state["positions"]:
        if p["status"] != "open":
            continue
        if datetime.fromisoformat(p["close_time"].replace("Z", "+00:00")) > now:
            continue
        try:
            m = client.get(f"/markets/{p['ticker']}").get("market", {})
        except Exception as e:
            logger.debug("resolve %s: %s", p["ticker"], e)
            continue
        res = (m.get("result") or "").lower()
        if res not in ("yes", "no"):
            continue
        n, sp = p["size"], p["sell_price"]
        p["pnl"] = round((sp * n - p["fee"]) if res == "no"
                         else (-(1 - sp) * n - p["fee"]), 4)
        p["status"] = "settled"
        p["result"] = res
        settled += 1
    return settled


def discover_candidates(cfg, client, now, exclude: set, deployed: float,
                        account: float | None = None) -> list[dict]:
    """Shared discovery + sizing — the strategy signal, identical for paper and
    live. Reads the live book and returns sized candidates; performs NO fill and
    mutates no state. Paper simulates the fill; live executes it.

    `account` is the capital base for sizing + the deployed guard. Paper passes
    None (uses the simulated cfg.account); LIVE passes the REAL Kalshi balance so
    no made-up account size influences real orders."""
    acct = account if account is not None else cfg.account
    have = set(exclude)
    cands: list[dict] = []
    for series in sorted(set(cfg.whitelist)):
        try:
            r = client.get("/markets", params={"series_ticker": series,
                                               "status": "open", "limit": 100})
        except Exception as e:
            logger.debug("%s: %s", series, e)
            continue
        for m in r.get("markets", []):
            tk = m["ticker"]
            if tk in have:
                continue
            ya, yb, bs, ct = (m.get("yes_ask_dollars"), m.get("yes_bid_dollars"),
                              m.get("yes_bid_size_fp"), m.get("close_time"))
            if None in (ya, yb, bs, ct):
                continue
            ya, yb, bs = float(ya), float(yb), float(bs)
            if not (cfg.band[0] <= ya <= cfg.band[1]) or yb <= 0:
                continue
            hrs = (datetime.fromisoformat(ct.replace("Z", "+00:00")) - now).total_seconds() / 3600
            if hrs <= 0 or hrs > cfg.max_hours_to_close:
                continue
            collat_per = 1.0 - yb
            n = int(acct * cfg.trade_fraction / collat_per) if collat_per > 0 else 0
            n = max(1, min(n, int(cfg.max_depth_frac * bs)))
            collat = collat_per * n
            if collat < 0.01 or deployed + collat > acct:
                continue
            cands.append({
                "ticker": tk, "series": series, "close_time": ct,
                "sell_price": yb, "size": n, "bid_depth": bs,
                "collateral": round(collat, 2), "fee": round(fee(yb, n), 4),
            })
            deployed += collat
            have.add(tk)
    return cands


def _discover(cfg, client, state, now) -> int:
    have = {p["ticker"] for p in state["positions"]}
    deployed = sum(p["collateral"] for p in state["positions"] if p["status"] == "open")
    cands = discover_candidates(cfg, client, now, have, deployed)
    for c in cands:
        state["positions"].append({
            "ticker": c["ticker"], "series": c["series"],
            "entry_ts": now.isoformat(), "close_time": c["close_time"],
            "sell_price": c["sell_price"], "size": c["size"], "fee": c["fee"],
            "collateral": c["collateral"], "bid_depth_at_entry": c["bid_depth"],
            "status": "open", "result": None, "pnl": None,
        })
        logger.info("PAPER SELL %-34s %d @ %.2f (depth %.0f, close %s)",
                    c["ticker"], c["size"], c["sell_price"], c["bid_depth"], c["close_time"][:16])
    return len(cands)


def run_once(cfg: LongshotConfig | None = None) -> dict:
    cfg = cfg or LongshotConfig()
    key_id, pem = load_kalshi_creds()
    client = KalshiClient(key_id, pem)
    now = datetime.now(timezone.utc)
    try:
        state = _load_state(cfg.state_file)
        settled_now = _resolve(cfg, client, state, now)
        opened_now = _discover(cfg, client, state, now)
        _save_state(cfg.state_file, state)
    finally:
        client.close()

    pos = state["positions"]
    settled = [p for p in pos if p["status"] == "settled"]
    openp = [p for p in pos if p["status"] == "open"]
    realized = round(sum(p["pnl"] for p in settled), 2)
    wins = sum(1 for p in settled if p["result"] == "no")
    collat_settled = sum(p["collateral"] for p in settled)
    return {
        "ts": now.isoformat(),
        "equity": round(cfg.account + realized, 2),
        "realized_pnl": realized,
        "open_positions": len(openp),
        "settled_positions": len(settled),
        "opened_this_tick": opened_now,
        "settled_this_tick": settled_now,
        "hit_rate_no": round(wins / len(settled), 4) if settled else None,
        "roi_on_settled_collateral": round(realized / collat_settled, 4) if collat_settled else None,
        "deployed_collateral": round(sum(p["collateral"] for p in openp), 2),
    }


def print_snapshot(snap: dict) -> None:
    logger.info(
        "tick: equity=$%.2f realized=$%.2f open=%d settled=%d (+%d/+%d this tick) "
        "hit(NO)=%s roi/collat=%s",
        snap["equity"], snap["realized_pnl"], snap["open_positions"],
        snap["settled_positions"], snap["opened_this_tick"], snap["settled_this_tick"],
        snap["hit_rate_no"], snap["roi_on_settled_collateral"],
    )
