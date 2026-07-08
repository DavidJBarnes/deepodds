"""One tick of the longshot paper harness: resolve matured shorts, then discover
and open new ones against the live Kalshi order book. Pure paper — no orders."""
import json
import logging
import os
from datetime import datetime, timezone

from longshot.kalshi_client import KalshiClient, kalshi_fee_per_contract as fee
from longshot.config import LongshotConfig, load_kalshi_creds
from longshot.reconcile import net_pnl

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
        p["pnl"] = net_pnl(p["sell_price"], p["size"], p["fee"], res)
        p["status"] = "settled"
        p["result"] = res
        p["settled_ts"] = now.isoformat()   # enables time-windowed live-vs-paper reporting
        settled += 1
    return settled


def size_candidate(cfg, m: dict, series: str, now, acct: float, deployed: float) -> dict | None:
    """Per-market filter + sizing (pure). Returns a sized candidate or None.
    Shared by paper discovery and live placement so the signal is identical."""
    ya, yb, bs, ct = (m.get("yes_ask_dollars"), m.get("yes_bid_dollars"),
                      m.get("yes_bid_size_fp"), m.get("close_time"))
    if None in (ya, yb, bs, ct):
        return None
    ya, yb, bs = float(ya), float(yb), float(bs)
    if not (cfg.band[0] <= ya <= cfg.band[1]) or yb <= 0:
        return None
    # Open interest at entry — always recorded; only filters when explicitly enabled.
    # keep_high=False -> trade only LOW-OI (skip oi>oi_max); keep_high=True -> trade
    # only HIGH-OI (skip oi<=oi_max). Default OFF so live behavior is unchanged.
    oi = float(m.get("open_interest_fp") or 0.0)
    if cfg.oi_filter_enabled:
        skip = (oi <= cfg.oi_max) if cfg.oi_keep_high else (oi > cfg.oi_max)
        if skip:
            return None
    hrs = (datetime.fromisoformat(ct.replace("Z", "+00:00")) - now).total_seconds() / 3600
    if hrs <= 0 or hrs > cfg.max_hours_to_close:
        return None
    collat_per = 1.0 - yb
    n = int(acct * cfg.trade_fraction / collat_per) if collat_per > 0 else 0
    n = max(1, min(n, int(cfg.max_depth_frac * bs)))
    collat = collat_per * n
    if collat < 0.01 or deployed + collat > acct:
        return None
    return {
        "ticker": m["ticker"], "series": series, "close_time": ct,
        "sell_price": yb, "size": n, "bid_depth": bs, "open_interest": oi,
        "collateral": round(collat, 2), "fee": round(fee(yb, n), 4),
    }


def underlying_key(ticker: str) -> str:
    """Correlation group for a market. All BTC tails (every strike/expiry) are the
    SAME trade — one big BTC day resolves them together — so they collapse to 'BTC';
    likewise ETH. Everything else groups by its event family (series prefix), which
    is ~independent (temp cities, distinct games) so the cap barely binds there."""
    t = (ticker or "").upper()
    if t.startswith("KXBTC"):
        return "BTC"
    if t.startswith("KXETH"):
        return "ETH"
    return t.split("-")[0]


def deployed_by_underlying(positions: list[dict]) -> dict:
    """Open collateral grouped by correlation key — the state the cap reads."""
    out: dict = {}
    for p in positions:
        if p.get("status") == "open":
            k = underlying_key(p.get("ticker", ""))
            out[k] = out.get(k, 0.0) + (p.get("collateral") or 0.0)
    return out


def discover_candidates(cfg, client, now, exclude: set, deployed: float,
                        account: float | None = None,
                        by_underlying: dict | None = None) -> list[dict]:
    """Shared discovery + sizing — the strategy signal, identical for paper and
    live. Reads the live book and returns sized candidates; performs NO fill and
    mutates no state. Paper simulates the fill; live executes it (interleaving
    fetch+place per series to avoid stale prices — see live_run).

    `account` is the capital base for sizing + the deployed guard. Paper passes
    None (uses the simulated cfg.account); LIVE passes the REAL Kalshi balance so
    no made-up account size influences real orders.

    `by_underlying` seeds the per-correlation-group deployed collateral; when
    cfg.max_underlying_collateral > 0 a candidate is skipped if it would push its
    group over the cap (defends against a single fat BTC day resolving every tail)."""
    acct = account if account is not None else cfg.account
    cap = cfg.max_underlying_collateral
    have = set(exclude)
    dbu = dict(by_underlying or {})
    cands: list[dict] = []
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
            c = size_candidate(cfg, m, series, now, acct, deployed)
            if not c:
                continue
            if cap > 0:
                uk = underlying_key(c["ticker"])
                if dbu.get(uk, 0.0) + c["collateral"] > cap:
                    logger.debug("underlying cap skip %s (%s)", c["ticker"], uk)
                    continue
                dbu[uk] = dbu.get(uk, 0.0) + c["collateral"]
            cands.append(c)
            deployed += c["collateral"]
            have.add(m["ticker"])
    return cands


def _discover(cfg, client, state, now) -> int:
    have = {p["ticker"] for p in state["positions"]}
    deployed = sum(p["collateral"] for p in state["positions"] if p["status"] == "open")
    cands = discover_candidates(cfg, client, now, have, deployed,
                                by_underlying=deployed_by_underlying(state["positions"]))
    for c in cands:
        state["positions"].append({
            "ticker": c["ticker"], "series": c["series"],
            "entry_ts": now.isoformat(), "close_time": c["close_time"],
            "sell_price": c["sell_price"], "size": c["size"], "fee": c["fee"],
            "collateral": c["collateral"], "bid_depth_at_entry": c["bid_depth"],
            "entry_oi": c["open_interest"],
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
