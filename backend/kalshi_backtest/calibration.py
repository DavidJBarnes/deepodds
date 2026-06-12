"""
Calibration analysis: implied probability vs realized YES rate by price bucket.

Inputs: cached markets + candles from ingest.py
Output: calibration.csv + calibration.png
"""
from __future__ import annotations

import csv
import logging
import math
from pathlib import Path

import pandas as pd
import numpy as np

logger = logging.getLogger("kalshi_backtest.calibration")

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = DATA_DIR / "output"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Entry horizons (hours before close)
HORIZONS = [48, 24, 6, 1]

# Price buckets (ask price bands, in ¢ = cents out of 100)
BUCKETS = [
    (0.80, 0.84, "80–84¢"),
    (0.85, 0.89, "85–89¢"),
    (0.90, 0.93, "90–93¢"),
    (0.94, 0.97, "94–97¢"),
]

# Walk-forward split
SELECTION_END = "2025-06-30"
VALIDATION_START = "2025-07-01"

CALIBRATION_CSV = OUTPUT_DIR / "calibration.csv"
CALIBRATION_PNG = OUTPUT_DIR / "calibration.png"

# Minimum n to include a cell in output
MIN_CELL_N = 30


# ---------------------------------------------------------------------------
# Kalshi fee calculation — exact per spec
# ---------------------------------------------------------------------------

def kalshi_fee_per_contract(ask_price: float, n_contracts: int = 1) -> float:
    """
    Fee per trade on Kalshi.
    fee = ceil_to_cent(0.07 * n_contracts * P * (1 - P))
    where P = ask_price (in dollars, 0 < P < 1).
    """
    p = ask_price
    raw = 0.07 * n_contracts * p * (1 - p)
    # ceil to cent
    return math.ceil(raw * 100) / 100


def net_edge_per_contract(realized_rate: float, ask_price: float) -> float:
    """
    Expected P&L per $1 contract position, net of Kalshi fee.
    Payout is $1 if YES, $0 if NO. Cost = ask_price + fee.
    Edge = realized_rate * 1.0 - ask_price - fee
    """
    fee = kalshi_fee_per_contract(ask_price, n_contracts=1)
    return realized_rate - ask_price - fee


# ---------------------------------------------------------------------------
# Wilson confidence interval
# ---------------------------------------------------------------------------

def wilson_ci(n: int, k: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson CI for proportion k/n."""
    if n == 0:
        return (0.0, 1.0)
    p_hat = k / n
    denom = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / denom
    spread = z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def ci_excludes_breakeven(ci_lo: float, ci_hi: float, ask_price: float) -> bool:
    """
    Does the 95% CI for the realized rate exclude the break-even rate?
    Break-even rate: buy is profitable if realized_rate > ask_price + fee.
    """
    breakeven = ask_price + kalshi_fee_per_contract(ask_price)
    return ci_lo > breakeven


# ---------------------------------------------------------------------------
# Build calibration dataset from cached data
# ---------------------------------------------------------------------------

def _parse_close_ts(close_time_str: str) -> float:
    """Return Unix timestamp from ISO close_time string."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _bucket_label(ask: float) -> str | None:
    for lo, hi, lbl in BUCKETS:
        if lo <= ask <= hi:
            return lbl
    return None


def build_dataset(markets: list[dict], candles: dict[str, list[dict]]) -> pd.DataFrame:
    """
    For each market × horizon, find the last candle at-or-before the entry horizon
    and record: ticker, close_time, category, horizon, ask_price, result, momentum_24h.
    """
    rows = []
    missing_candles = 0
    for m in markets:
        ticker = m["ticker"]
        result = m.get("result", "")
        if result not in ("yes", "no"):
            continue
        resolved_yes = result == "yes"
        close_ts = _parse_close_ts(m.get("close_time", ""))
        if close_ts == 0:
            continue

        candle_list = candles.get(ticker)
        if not candle_list:
            missing_candles += 1
            continue

        # Sort by ts ascending
        clist = sorted(candle_list, key=lambda c: int(c.get("ts", 0)))

        for horizon_h in HORIZONS:
            cutoff_ts = close_ts - horizon_h * 3600
            # Last candle at or before cutoff
            entry_candle = None
            for c in clist:
                if int(c.get("ts", 0)) <= cutoff_ts:
                    entry_candle = c
                else:
                    break

            if entry_candle is None:
                continue
            ask = float(entry_candle.get("yes_ask") or entry_candle.get("price") or 0)
            if ask <= 0 or ask >= 1:
                continue

            bucket = _bucket_label(ask)
            if bucket is None:
                continue

            # Momentum: price change over prior 24h (at entry point)
            momentum_ts = cutoff_ts - 24 * 3600
            momentum_candle = None
            for c in clist:
                if int(c.get("ts", 0)) <= momentum_ts:
                    momentum_candle = c
                else:
                    break
            if momentum_candle is not None:
                prior_price = float(momentum_candle.get("yes_ask")
                                    or momentum_candle.get("price") or ask)
                momentum = ask - prior_price
            else:
                momentum = 0.0

            rows.append({
                "ticker": ticker,
                "category": (m.get("category") or "other").lower(),
                "close_time": m.get("close_time", ""),
                "horizon_h": horizon_h,
                "ask_price": ask,
                "bucket": bucket,
                "resolved_yes": int(resolved_yes),
                "momentum_24h": round(momentum, 4),
            })

    logger.info("Dataset rows: %d (missing_candles=%d)", len(rows), missing_candles)
    if not rows:
        return pd.DataFrame(columns=["ticker", "category", "close_time", "horizon_h",
                                     "ask_price", "bucket", "resolved_yes", "momentum_24h"])
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Calibration table
# ---------------------------------------------------------------------------

def calibrate(df: pd.DataFrame, window: str = "all") -> pd.DataFrame:
    """
    Compute calibration stats per (horizon, bucket, category).
    window: 'all', 'selection', 'validation'
    """
    if window == "selection":
        df = df[df["close_time"] <= SELECTION_END].copy()
    elif window == "validation":
        df = df[df["close_time"] >= VALIDATION_START].copy()

    if df.empty:
        return pd.DataFrame()

    records = []
    for horizon in HORIZONS:
        sub_h = df[df["horizon_h"] == horizon]
        for lo, hi, label in BUCKETS:
            sub_b = sub_h[(sub_h["ask_price"] >= lo) & (sub_h["ask_price"] <= hi)]
            for cat in list(sub_b["category"].unique()) + ["ALL"]:
                if cat == "ALL":
                    sub_c = sub_b
                else:
                    sub_c = sub_b[sub_b["category"] == cat]
                n = len(sub_c)
                if n < MIN_CELL_N:
                    continue
                k = int(sub_c["resolved_yes"].sum())
                mean_ask = float(sub_c["ask_price"].mean())
                realized = k / n
                raw_edge = realized - mean_ask
                net = net_edge_per_contract(realized, mean_ask)
                ci_lo, ci_hi = wilson_ci(n, k)
                excl = ci_excludes_breakeven(ci_lo, ci_hi, mean_ask)
                records.append({
                    "window": window,
                    "horizon_h": horizon,
                    "bucket": label,
                    "category": cat,
                    "n": n,
                    "implied": round(mean_ask, 4),
                    "realized": round(realized, 4),
                    "raw_edge": round(raw_edge, 4),
                    "net_edge": round(net, 4),
                    "ci_lo": round(ci_lo, 4),
                    "ci_hi": round(ci_hi, 4),
                    "ci_excl_breakeven": excl,
                })

    return pd.DataFrame(records)


def adverse_selection_analysis(df: pd.DataFrame, window: str = "all") -> pd.DataFrame:
    """
    Within each (horizon, bucket), split by momentum sign.
    """
    if window == "selection":
        df = df[df["close_time"] <= SELECTION_END].copy()
    elif window == "validation":
        df = df[df["close_time"] >= VALIDATION_START].copy()

    records = []
    for horizon in HORIZONS:
        sub_h = df[df["horizon_h"] == horizon]
        for lo, hi, label in BUCKETS:
            sub_b = sub_h[(sub_h["ask_price"] >= lo) & (sub_h["ask_price"] <= hi)]
            for momentum_dir in ["rising", "falling"]:
                if momentum_dir == "rising":
                    sub_m = sub_b[sub_b["momentum_24h"] >= 0]
                else:
                    sub_m = sub_b[sub_b["momentum_24h"] < 0]
                n = len(sub_m)
                if n < MIN_CELL_N:
                    continue
                k = int(sub_m["resolved_yes"].sum())
                mean_ask = float(sub_m["ask_price"].mean())
                realized = k / n
                net = net_edge_per_contract(realized, mean_ask)
                records.append({
                    "window": window,
                    "horizon_h": horizon,
                    "bucket": label,
                    "momentum": momentum_dir,
                    "n": n,
                    "implied": round(mean_ask, 4),
                    "realized": round(realized, 4),
                    "net_edge": round(net, 4),
                })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def _make_chart(df_all: pd.DataFrame, df_val: pd.DataFrame) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available — skipping chart")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Kalshi Favorites — Implied vs Realized by Price Bucket", fontsize=13)

    for ax, df, title in [
        (axes[0], df_all, "All data"),
        (axes[1], df_val, "Validation window (2025-07+)"),
    ]:
        if df.empty:
            ax.set_title(title + " (no data)")
            continue
        # Best horizon row (most data)
        best_h = df.groupby("horizon_h")["n"].sum().idxmax() if not df.empty else HORIZONS[0]
        sub = df[(df["horizon_h"] == best_h) & (df["category"] == "ALL")].sort_values("implied")
        if sub.empty:
            ax.set_title(title + " (no data)")
            continue
        ax.errorbar(
            sub["implied"], sub["realized"],
            yerr=[sub["realized"] - sub["ci_lo"], sub["ci_hi"] - sub["realized"]],
            fmt="o", capsize=5, label=f"Realized (horizon={best_h}h)",
        )
        xlim = ax.get_xlim()
        ax.plot([0.75, 1.0], [0.75, 1.0], "k--", lw=0.8, label="Perfect calibration")
        ax.set_xlabel("Implied probability (ask price)")
        ax.set_ylabel("Realized YES rate")
        ax.set_title(f"{title} — {best_h}h horizon")
        ax.legend(fontsize=9)
        ax.set_xlim(0.78, 0.99)
        ax.set_ylim(0.78, 1.02)

    plt.tight_layout()
    plt.savefig(CALIBRATION_PNG, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved calibration chart to %s", CALIBRATION_PNG)


# ---------------------------------------------------------------------------
# Run calibration
# ---------------------------------------------------------------------------

def run_calibration(markets: list[dict],
                    candles: dict[str, list[dict]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Returns (df_all_calib, df_val_calib, df_adv_sel).
    Also writes calibration.csv and calibration.png.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = build_dataset(markets, candles)
    logger.info("Dataset: %d rows", len(df))

    df_all = calibrate(df, window="all")
    df_sel = calibrate(df, window="selection")
    df_val = calibrate(df, window="validation")
    df_adv = adverse_selection_analysis(df, window="all")

    # Write CSV
    combined = pd.concat([df_all, df_sel, df_val], ignore_index=True)
    combined.to_csv(CALIBRATION_CSV, index=False)
    logger.info("Wrote %s", CALIBRATION_CSV)

    _make_chart(df_all, df_val)

    return df_sel, df_val, df_adv


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    from kalshi_backtest.ingest import load_markets, load_candles
    markets = load_markets()
    candles = {m["ticker"]: rows
               for m in markets
               if (rows := load_candles(m["ticker"])) is not None}
    logger.info("Loaded %d markets, %d with candles", len(markets), len(candles))
    run_calibration(markets, candles)


if __name__ == "__main__":
    main()
