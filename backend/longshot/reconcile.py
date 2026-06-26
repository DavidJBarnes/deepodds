"""Reconciliation: in live mode, Kalshi is the source of truth. The local state
file is an intent-log + cache; every tick (and at startup) we pull real balance,
positions, and settlements from Kalshi and merge them in.

The merge functions are pure (state + truth dicts in, mutated state out) so they
are unit-testable without a broker. The exact Kalshi field names are parsed
defensively with .get() and VERIFIED against the real account in Phase 1 — adjust
the small number of accessor helpers below if Phase 1 shows different keys.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from longshot.kalshi_client import KalshiClient

logger = logging.getLogger("longshot.reconcile")


# -- defensive accessors (single place to fix if Phase 1 reveals other keys) --
def _pos_ticker(p: dict) -> str:
    return p.get("ticker") or p.get("market_ticker") or ""


def _pos_count(p: dict) -> int:
    # Kalshi position count; shorts show as negative position / positive 'no'.
    for k in ("position", "market_position", "count"):
        if p.get(k) is not None:
            return int(p[k])
    return 0


def _settle_ticker(s: dict) -> str:
    return s.get("ticker") or s.get("market_ticker") or ""


def _settle_result(s: dict) -> str:
    return (s.get("market_result") or s.get("result") or "").lower()


def _settle_pnl_dollars(s: dict) -> float | None:
    # Kalshi reports settlement money in cents; prefer revenue/pnl if present.
    for k in ("realized_pnl", "pnl", "revenue"):
        if s.get(k) is not None:
            return float(s[k]) / 100.0
    return None


def net_pnl(sell_price: float, size: float, fee: float, result: str) -> float:
    """Canonical NET P&L for a short-YES position (the paper convention) — NOT
    Kalshi's gross settlement `revenue` ($1/contract payout). Win (NO) keeps the
    premium; loss (YES) loses the collateral; both minus fee. Single source of
    truth used by apply_settlements, heal_settled_pnl, and paper resolution."""
    if result == "no":
        return round(sell_price * size - fee, 4)
    return round(-(1 - sell_price) * size - fee, 4)


def heal_settled_pnl(state: dict) -> int:
    """Idempotently re-derive settled P&L from the canonical formula. Self-corrects
    records booked by OLDER reconcile logic: a position that settles in the window
    before a fix deploys stays mis-booked forever, because apply_settlements only
    touches OPEN positions. Running this every live tick makes that class of stale
    record self-heal instead of needing a manual recompute (cf. the 2026-06-25
    gross-revenue artifact). A no-op once values are correct.

    Only heals positions with a known entry price; adopted orphans (sell_price None,
    settled from gross revenue) are left untouched."""
    n = 0
    for p in state.get("positions", []):
        if p.get("status") != "settled" or p.get("sell_price") is None:
            continue
        res = p.get("result")
        if res not in ("yes", "no"):
            continue
        sz = p.get("filled_size") or p.get("size") or 0
        want = net_pnl(p["sell_price"], sz, p.get("fee") or 0, res)
        if p.get("pnl") is None or abs((p.get("pnl") or 0) - want) > 1e-6:
            logger.warning("heal stale pnl %s: %s -> %s", p.get("ticker"), p.get("pnl"), want)
            p["pnl"] = want
            n += 1
    return n


def fetch_truth(client: KalshiClient) -> dict:
    """Read-only pull of everything Kalshi knows. Used in Phase 1/2 verification
    and every live tick."""
    truth = {"balance_dollars": None, "positions": [], "settlements": []}
    try:
        bal = client.get_balance()
        truth["balance_dollars"] = float(bal.get("balance", 0)) / 100.0
    except Exception as e:
        logger.warning("balance fetch failed: %s", e)
    try:
        truth["positions"] = client.get_positions(limit=1000).get("market_positions",
                              client.get_positions(limit=1000).get("positions", []))
    except Exception as e:
        logger.warning("positions fetch failed: %s", e)
    try:
        truth["settlements"] = client.get_settlements(limit=1000).get("settlements", [])
    except Exception as e:
        logger.warning("settlements fetch failed: %s", e)
    return truth


def apply_settlements(state: dict, settlements: list[dict]) -> int:
    """Move local open positions to settled using Kalshi's real outcome + money."""
    by_ticker = {_settle_ticker(s): s for s in settlements if _settle_ticker(s)}
    n = 0
    for p in state.get("positions", []):
        if p.get("status") != "open":
            continue
        s = by_ticker.get(p["ticker"])
        if not s:
            continue
        res = _settle_result(s)
        if res not in ("yes", "no"):
            continue
        # NET P&L (matches the paper convention) — NOT Kalshi's gross settlement
        # `revenue` (which is the $1/contract payout, not profit). For a short YES:
        # win (NO) keeps the premium; loss (YES) loses the collateral; minus fee.
        sp, sz, fee = p.get("sell_price"), p.get("filled_size") or p.get("size") or 0, p.get("fee") or 0
        if sp is not None:
            pnl = net_pnl(sp, sz, fee, res)
        else:
            # adopted orphan (unknown entry): net = gross revenue - collateral - fee
            rev, collat = _settle_pnl_dollars(s), p.get("collateral") or 0
            pnl = round((rev - collat - fee), 4) if rev is not None else 0.0
        p["status"] = "settled"
        p["result"] = res
        p["pnl"] = pnl
        p["settled_ts"] = datetime.now(timezone.utc).isoformat()
        n += 1
    return n


def realized_pnl_today(state: dict, now: datetime | None = None) -> float:
    """Sum of pnl for positions settled since UTC midnight — feeds the daily-loss
    kill limit."""
    now = now or datetime.now(timezone.utc)
    day = now.date().isoformat()
    return round(sum(
        p.get("pnl") or 0 for p in state.get("positions", [])
        if p.get("status") == "settled" and (p.get("settled_ts") or "").startswith(day)
    ), 4)


def adopt_orphans(state: dict, positions: list[dict], now: datetime | None = None) -> int:
    """Safety net: any non-zero Kalshi position we have no local record for gets
    adopted so it shows up and can't silently drift. Indicates an idempotency or
    crash-recovery event worth alerting on."""
    now = now or datetime.now(timezone.utc)
    known = {p["ticker"] for p in state.get("positions", [])}
    n = 0
    for kp in positions:
        tk = _pos_ticker(kp)
        cnt = _pos_count(kp)
        if not tk or cnt == 0 or tk in known:
            continue
        state.setdefault("positions", []).append({
            "ticker": tk, "series": tk.split("-")[0],
            "entry_ts": now.isoformat(), "close_time": None,
            "sell_price": None, "size": abs(cnt), "filled_size": abs(cnt),
            "fee": 0.0, "collateral": None, "bid_depth_at_entry": None,
            "status": "open", "result": None, "pnl": None,
            "adopted": True,
        })
        known.add(tk)
        n += 1
        logger.error("ORPHAN ADOPTED %s count=%d — investigate idempotency/crash", tk, cnt)
    return n


def slippage_stats(state: dict) -> dict:
    """Aggregate intended-vs-actual across filled live positions — the core
    paper->live gap metric driving the Phase 4 gate."""
    fills = [p for p in state.get("positions", [])
             if p.get("intended_price") is not None and p.get("avg_fill_price") is not None]
    if not fills:
        return {"orders": 0, "fill_rate": None, "avg_slippage_c": None}
    intended = sum(p["intended_size"] for p in fills)
    filled = sum(p.get("filled_size", 0) for p in fills)
    # slippage in cents: how much worse our actual sell price was vs intended
    slip = [(p["intended_price"] - p["avg_fill_price"]) * 100
            for p in fills if p.get("filled_size", 0) > 0]
    return {
        "orders": len(fills),
        "fill_rate": round(filled / intended, 4) if intended else None,
        "avg_slippage_c": round(sum(slip) / len(slip), 3) if slip else None,
    }


def live_snapshot(cfg, state: dict, truth: dict, now: datetime | None = None) -> dict:
    """Build the dashboard snapshot from Kalshi truth (NOT a simulation)."""
    now = now or datetime.now(timezone.utc)
    pos = state.get("positions", [])
    settled = [p for p in pos if p.get("status") == "settled"]
    openp = [p for p in pos if p.get("status") == "open"]
    realized = round(sum(p.get("pnl") or 0 for p in settled), 2)
    wins = sum(1 for p in settled if p.get("result") == "no")
    bal = truth.get("balance_dollars")
    deployed = round(sum(p.get("collateral") or 0 for p in openp), 2)
    # Equity is the REAL Kalshi account value — never a hardcoded account size.
    # balance (available cash) + collateral locked in open shorts reconstructs the
    # total. If Kalshi is unreachable this tick, report null rather than a made-up
    # number. (Collateral treatment vs Kalshi's displayed portfolio value is
    # confirmed against the first open live position — Phase 1.)
    equity = round(bal + deployed, 2) if bal is not None else None
    return {
        "ts": now.isoformat(),
        "mode": "live",
        "balance": bal,
        "equity": equity,
        "realized_pnl": realized,
        "open_positions": len(openp),
        "settled_positions": len(settled),
        "hit_rate_no": round(wins / len(settled), 4) if settled else None,
        "deployed_collateral": deployed,
        "slippage": slippage_stats(state),
    }
