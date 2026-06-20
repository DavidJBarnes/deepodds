"""
Step 2 — collateral-aware bankroll sim for SHORTING longshots (sell YES on
overpriced 1-20c markets).

Short mechanics (Kalshi):
  - Sell 1 YES contract at price p: receive p cash, post collateral (1 - p)
    (your max loss if it resolves YES). Total capital locked = (1 - p).
  - Resolves NO  -> keep p           ; pnl = +p - fee
  - Resolves YES -> pay 1, had p     ; pnl = -(1 - p) - fee
  - Expected pnl/contract = p - realized_yes  (the seller edge), minus fee.

Capital is locked entry->settlement and released at resolution (event-driven
calendar concurrency, same pattern as the fixed favorites sim). Sizing is a
fraction of equity as collateral; per-trade size is also capped at a fraction of
the entry-day traded volume (depth proxy) so we don't assume infinite liquidity.
"""
from __future__ import annotations

import heapq
import logging
import math
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

import kalshi_backtest.ingest_s3 as I
from kalshi_backtest.calibration import kalshi_fee_per_contract as _fee

logger = logging.getLogger("kalshi_backtest.short_sim")

BAND = (1, 20)               # cheap longshot band, cents (mid)
TRADE_FRACTION = 0.02        # collateral per trade as fraction of equity
DEPTH_FRACTION = 0.25        # max fraction of entry-day volume we can sell into
VAL_START_ISO = "2025-07-01"


def build_short_dataset(rows, settle, horizon_d=1, sell_fill="low",
                        band=BAND, vol_floor=500.0) -> pd.DataFrame:
    """One row per (ticker) shorting opportunity at the given horizon."""
    hists = I.build_market_histories(rows)
    vol = {t: sum(float(r.get("daily_volume") or 0) for r in h) for t, h in hists.items()}
    recs = []
    for t, h in hists.items():
        rt = h[0].get("report_ticker", "")
        if I._is_parlay(rt) or vol.get(t, 0) < vol_floor:
            continue
        if settle.get(t) not in ("yes", "no"):
            continue
        active = [r for r in h if float(r.get("daily_volume") or 0) > 0
                  or float(r.get("open_interest") or 0) > 0]
        if len(active) < horizon_d + 1:
            continue
        er = active[len(active) - 1 - horizon_d]
        hi = int(er.get("high_cents") or 0)
        lo = int(er.get("low_cents") or 0)
        if hi <= 0 and lo <= 0:
            continue
        mid = (hi + lo) / 2
        if not (band[0] <= mid <= band[1]):
            continue
        sell_px = (lo if sell_fill == "low" else mid) / 100.0
        if sell_px <= 0 or sell_px >= 1:
            continue
        recs.append({
            "ticker": t,
            "category": I.assign_category(rt, {}) if hasattr(I, "assign_category") else rt[:8],
            "entry_date": er["date"],
            "settle_date": active[-1]["date"],
            "sell_px": round(sell_px, 4),
            "resolved_yes": 1 if settle[t] == "yes" else 0,
            "entry_vol": float(er.get("daily_volume") or 0),
        })
    return pd.DataFrame(recs)


@dataclass
class ShortState:
    bankroll: float
    realized_pnl: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_fees: float = 0.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    peak_collateral: float = 0.0
    skipped_capital: int = 0
    skipped_depth: int = 0
    equity_history: list = field(default_factory=list)

    def update_dd(self, eq):
        self.peak_equity = max(self.peak_equity, eq)
        if self.peak_equity > 0:
            dd = (eq - self.peak_equity) / self.peak_equity
            self.max_drawdown = min(self.max_drawdown, dd)


def run_short_sim(df: pd.DataFrame, bankroll: float,
                  trade_fraction=TRADE_FRACTION, depth_fraction=DEPTH_FRACTION,
                  fee_multiplier=1.0, window="validation") -> ShortState:
    if window == "validation":
        df = df[df["settle_date"] >= VAL_START_ISO]
    if df.empty:
        return ShortState(bankroll=bankroll, peak_equity=bankroll)

    df = df.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_date"], utc=True)
    df["settle_ts"] = pd.to_datetime(df["settle_date"], utc=True)
    df = df.sort_values("entry_ts")

    st = ShortState(bankroll=bankroll, peak_equity=bankroll)
    cash = bankroll          # free capital
    locked = 0.0             # collateral in open shorts
    open_heap: list = []     # (settle_ts, n, sell_px, resolved_yes, collat)
    seen = set()

    def mark(ts):
        st.bankroll = cash + locked
        st.update_dd(st.bankroll)
        st.equity_history.append((str(ts), st.bankroll))

    def settle_due(now):
        nonlocal cash, locked
        while open_heap and open_heap[0][0] <= now:
            s_ts, n, p, ry, collat = heapq.heappop(open_heap)
            # release collateral; realize pnl
            if ry:
                pnl = -(1.0 - p) * n      # pay out
                st.losses += 1
            else:
                pnl = p * n               # keep premium
                st.wins += 1
            cash += collat + pnl          # collateral back + pnl
            locked -= collat
            st.realized_pnl += pnl
            mark(s_ts)

    for _, r in df.iterrows():
        settle_due(r["entry_ts"])
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"])
        p = float(r["sell_px"])
        collat_per = 1.0 - p
        equity = cash + locked
        target_collat = equity * trade_fraction
        n = int(target_collat / collat_per) if collat_per > 0 else 0
        # depth cap: can't sell more than depth_fraction of entry-day volume
        depth_cap = int(depth_fraction * float(r["entry_vol"]))
        if depth_cap < 1:
            st.skipped_depth += 1
            continue
        n = max(1, min(n, depth_cap))
        fee = _fee(p, n) * fee_multiplier
        need = collat_per * n + fee
        if need > cash:
            st.skipped_capital += 1
            continue
        cash -= (collat_per * n) + fee
        locked += collat_per * n
        st.total_fees += fee
        st.realized_pnl -= fee            # fee paid at entry
        st.total_trades += 1
        st.peak_collateral = max(st.peak_collateral, locked)
        heapq.heappush(open_heap, (r["settle_ts"], n, p, int(r["resolved_yes"]), collat_per * n))

    settle_due(pd.Timestamp.max.tz_localize("UTC"))
    st.bankroll = cash + locked
    return st


def annualized(st, start_iso, end_iso, initial):
    s = pd.Timestamp(start_iso); e = pd.Timestamp(end_iso)
    yrs = (e - s).days / 365.25
    if yrs <= 0:
        return 0.0
    return (st.bankroll / initial) ** (1 / yrs) - 1.0


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    I.SHARD_DIR = I.DATA_DIR / "s3_markets_low"
    rows = I.load_s3_shards(start=date(2025, 7, 1))
    settle = I.load_settlement_cache()
    print(f"rows={len(rows)} settled_on_disk={sum(1 for v in set(r['ticker_name'] for r in rows) if settle.get(v) in ('yes','no'))}")
    for hz in (1, 7):
        df = build_short_dataset(rows, settle, horizon_d=hz, sell_fill="low")
        if df.empty:
            print(f"horizon={hz}d: empty"); continue
        for cap in (5_000.0, 8_000.0):
            st = run_short_sim(df, cap)
            roi = annualized(st, VAL_START_ISO, "2025-12-03", cap)
            hr = st.wins / st.total_trades if st.total_trades else 0
            print(f"hz={hz}d cap=${cap:,.0f} | trades={st.total_trades} hit(NO)={hr*100:.1f}% "
                  f"final=${st.bankroll:,.0f} annROI={roi*100:.1f}% MaxDD={abs(st.max_drawdown)*100:.1f}% "
                  f"peakCollat=${st.peak_collateral:,.0f} skip(cap/depth)={st.skipped_capital}/{st.skipped_depth}")


if __name__ == "__main__":
    main()
