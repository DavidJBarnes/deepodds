"""
Walk-forward bankroll simulation for Kalshi favorites strategy.

Only cells that calibration shows as net-positive with CI support on the
selection window are traded. Validation results are the headline numbers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import numpy as np

from kalshi_backtest.calibration import (
    SELECTION_END, VALIDATION_START, HORIZONS, BUCKETS,
    net_edge_per_contract, kalshi_fee_per_contract,
    calibrate, build_dataset, adverse_selection_analysis,
)

logger = logging.getLogger("kalshi_backtest.simulate")

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = DATA_DIR / "output"

# Sim parameters
TRADE_FRACTION = 0.02       # max 2% of bankroll per trade
VOLUME_CAP_FRAC = 0.25      # max 25% of candle volume
CAPITAL_LEVELS = [5_000.0, 8_000.0]

# Doubled-fee sensitivity
FEE_MULTIPLIER_DOUBLED = 2.0


# ---------------------------------------------------------------------------
# Eligible-cell selection (on selection window only)
# ---------------------------------------------------------------------------

def select_cells(df_sel_calib: pd.DataFrame,
                 df_adv_sel: pd.DataFrame | None = None) -> set[tuple]:
    """
    Return set of (horizon_h, bucket, category) tuples that are tradeable:
    - net_edge > 0
    - ci_excludes_breakeven == True
    - category == "ALL" or specific category cell (we check both; prefer specific)

    Also enforces non-negative momentum if adverse_selection shows falling favorites
    lose badly (net_edge < 0 for 'falling' momentum).
    """
    if df_sel_calib.empty:
        return set()

    # Positive net edge + CI excludes breakeven
    eligible = df_sel_calib[
        (df_sel_calib["net_edge"] > 0) &
        (df_sel_calib["ci_excl_breakeven"] == True)  # noqa: E712
    ]

    cells: set[tuple] = set()
    for _, row in eligible.iterrows():
        cells.add((int(row["horizon_h"]), row["bucket"], row["category"]))

    # Check momentum filter: if falling cells exist and are negative, require rising
    require_rising_momentum: set[tuple] = set()
    if df_adv_sel is not None and not df_adv_sel.empty:
        falling = df_adv_sel[df_adv_sel["momentum"] == "falling"]
        for _, row in falling.iterrows():
            key = (int(row["horizon_h"]), row["bucket"])
            if row["net_edge"] < 0:
                require_rising_momentum.add(key)

    return cells, require_rising_momentum


# ---------------------------------------------------------------------------
# Portfolio state
# ---------------------------------------------------------------------------

@dataclass
class SimState:
    bankroll: float
    open_positions: list[dict] = field(default_factory=list)  # not used for hold-to-settle sim
    realized_pnl: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_fees: float = 0.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    peak_concurrent_exposure: float = 0.0
    skipped_volume_cap: int = 0
    skipped_cash: int = 0
    equity_history: list[tuple[str, float]] = field(default_factory=list)

    def equity(self) -> float:
        return self.bankroll

    def update_drawdown(self) -> None:
        eq = self.equity()
        if eq > self.peak_equity:
            self.peak_equity = eq
        dd = (eq - self.peak_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        if dd < self.max_drawdown:
            self.max_drawdown = dd


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------

def run_simulation(
    df_dataset: pd.DataFrame,
    cells: set[tuple],
    require_rising_momentum: set[tuple],
    bankroll: float,
    window: str = "validation",
    fee_multiplier: float = 1.0,
) -> SimState:
    """
    Simulate the strategy on the given window.
    Positions are held to settlement (we just record entry + outcome).
    Cash tracks deployed capital.
    """
    if window == "selection":
        df = df_dataset[df_dataset["close_time"] <= SELECTION_END].copy()
    elif window == "validation":
        df = df_dataset[df_dataset["close_time"] >= VALIDATION_START].copy()
    else:
        df = df_dataset.copy()

    if df.empty:
        return SimState(bankroll=bankroll, peak_equity=bankroll)

    # Sort by effective entry time: close_time - horizon_h
    df = df.copy()
    df["entry_time"] = pd.to_datetime(df["close_time"], utc=True) - pd.to_timedelta(df["horizon_h"], unit="h")
    df = df.sort_values("entry_time")

    import heapq

    state = SimState(bankroll=bankroll, peak_equity=bankroll)

    # Event-driven calendar sim. Capital is locked from entry_time to the
    # settlement (close_time) and only freed when the position resolves, so
    # concurrent positions genuinely compete for cash. Settlements are applied
    # in calendar order *before* each new entry, which is what makes this a
    # walk-forward sim rather than the old per-trade compounding loop.
    cash = bankroll          # free cash
    open_cost = 0.0          # cost basis of currently-open positions
    # min-heap of (settle_ts, n_contracts, cost, resolved_yes)
    open_heap: list[tuple] = []

    # Dedup: only one entry per (ticker, horizon)
    seen_entries: set[tuple[str, int]] = set()

    def _mark(ts: str) -> None:
        # Mark equity at cost basis (no interim marks available from daily data)
        state.bankroll = cash + open_cost
        state.update_drawdown()
        state.equity_history.append((ts, state.bankroll))

    def _settle_due(now) -> None:
        nonlocal cash, open_cost
        while open_heap and open_heap[0][0] <= now:
            settle_ts, n_contracts, cost, resolved_yes = heapq.heappop(open_heap)
            payout = n_contracts * 1.0 if resolved_yes else 0.0
            cash += payout
            open_cost -= cost
            pnl = payout - cost
            state.realized_pnl += pnl
            if pnl > 0:
                state.wins += 1
            else:
                state.losses += 1
            _mark(str(settle_ts))

    for _, row in df.iterrows():
        entry_ts = row["entry_time"]
        # Free capital from anything that settled on/before this entry
        _settle_due(entry_ts)

        horizon_h = int(row["horizon_h"])
        bucket = row["bucket"]
        cat = row["category"]
        ask = float(row["ask_price"])
        resolved_yes = int(row["resolved_yes"])
        mom = float(row.get("momentum_24h", 0))
        ticker = row["ticker"]
        settle_ts = pd.to_datetime(row["close_time"], utc=True)

        # Dedup: only one entry per (ticker, horizon)
        entry_key = (ticker, horizon_h)
        if entry_key in seen_entries:
            continue

        # Cell eligibility: (horizon, bucket, category) or (horizon, bucket, ALL)
        cat_key = (horizon_h, bucket, cat)
        all_key = (horizon_h, bucket, "ALL")
        if cat_key not in cells and all_key not in cells:
            continue

        # Momentum filter
        mom_key = (horizon_h, bucket)
        if mom_key in require_rising_momentum and mom < 0:
            continue

        seen_entries.add(entry_key)

        # Size off current equity (2% fraction). Compounding here is calendar
        # compounding — bounded by how fast capital actually recycles.
        equity = cash + open_cost
        size_cash = equity * TRADE_FRACTION
        if size_cash < 1.0:
            state.skipped_cash += 1
            continue

        n_contracts = max(1, int(size_cash / ask))
        cost = n_contracts * ask
        fee = kalshi_fee_per_contract(ask, n_contracts) * fee_multiplier
        total_cost = cost + fee

        # Cash gate: can't deploy more than we have free
        if total_cost > cash:
            state.skipped_cash += 1
            continue

        cash -= total_cost
        open_cost += total_cost
        state.total_trades += 1
        state.total_fees += fee
        if open_cost > state.peak_concurrent_exposure:
            state.peak_concurrent_exposure = open_cost

        heapq.heappush(open_heap, (settle_ts, n_contracts, total_cost, resolved_yes))

    # Settle everything still open at end of window
    _settle_due(pd.Timestamp.max.tz_localize("UTC"))
    state.bankroll = cash + open_cost  # open_cost == 0 here

    return state


# ---------------------------------------------------------------------------
# Annualized ROI
# ---------------------------------------------------------------------------

def annualized_roi(state: SimState, start_date: str, end_date: str, initial: float) -> float:
    try:
        from datetime import datetime
        s = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        years = (e - s).days / 365.25
        if years <= 0:
            return 0.0
        total_return = (state.equity() - initial) / initial
        return (1 + total_return) ** (1 / years) - 1
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Run the full walk-forward simulation
# ---------------------------------------------------------------------------

def run_all(markets: list[dict], candles: dict[str, list[dict]]) -> dict:
    """
    Full pipeline: build dataset, select cells, run val simulation.
    Returns result dict for report.
    """
    from kalshi_backtest.calibration import run_calibration
    df_sel_calib, df_val_calib, df_adv = run_calibration(markets, candles)

    df_dataset = build_dataset(markets, candles)

    cells, require_rising = select_cells(df_sel_calib, df_adv)
    logger.info("Selected %d eligible cells (selection window)", len(cells))
    logger.info("Momentum filter required for %d (horizon, bucket) pairs", len(require_rising))

    results = {}
    for capital in CAPITAL_LEVELS:
        # Validation sim
        val_state = run_simulation(
            df_dataset, cells, require_rising, capital, window="validation"
        )
        val_state_doubled = run_simulation(
            df_dataset, cells, require_rising, capital, window="validation",
            fee_multiplier=FEE_MULTIPLIER_DOUBLED,
        )
        results[capital] = {
            "cells": cells,
            "require_rising": require_rising,
            "val": val_state,
            "val_doubled": val_state_doubled,
            "df_sel_calib": df_sel_calib,
            "df_val_calib": df_val_calib,
            "df_adv": df_adv,
        }

    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    from kalshi_backtest.ingest import load_markets, load_candles
    markets = load_markets()
    candles = {m["ticker"]: rows
               for m in markets
               if (rows := load_candles(m["ticker"])) is not None}
    run_all(markets, candles)


if __name__ == "__main__":
    main()
