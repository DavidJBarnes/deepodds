"""
BTC exchange net-flow strategy backtest.

Run in-sample first. Only pass --oos after in-sample clears ALL gate criteria.
Running --oos multiple times to tune parameters = p-hacking = the climate mistake.

Usage:
    cd backend
    uv run python -m onchain.backtest.backtest              # in-sample only (default)
    uv run python -m onchain.backtest.backtest --oos        # include OOS (one shot)
    uv run python -m onchain.backtest.backtest --plot       # save equity curve PNG
    uv run python -m onchain.backtest.backtest --short 3 --long 30   # variant sweep
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from onchain.backtest.signals import compute_signal, load_data

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"

TRAIN_START = "2021-01-01"
TRAIN_END = "2023-12-31"
OOS_START = "2024-01-01"
OOS_END = "2025-12-31"

RF_ANNUAL = 0.04  # risk-free rate used for Sharpe


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    short_window: int = 7
    long_window: int = 90
    threshold: float = 1.0
    max_hold_days: int = 14
    cost_per_leg: float = 0.0005  # 0.05% per leg → 0.10% round-trip


# ---------------------------------------------------------------------------
# Gate criteria — ALL must pass before Phase 2 is built
# ---------------------------------------------------------------------------

# (description, threshold string, test fn applied to train metric value)
TRAIN_GATE: list[tuple[str, str, object]] = [
    ("Sharpe (train)",       "> 0.60",   lambda v: v > 0.60),
    ("Max drawdown (train)", "> -45%",   lambda v: v > -0.45),
    ("IC(7d) (train)",       "> 0.04",   lambda v: v > 0.04),
    ("IC(7d) p-val (train)", "< 0.10",   lambda v: v < 0.10),
]
OOS_GATE: list[tuple[str, str, object]] = [
    ("Total return (OOS)",   "> 0%",     lambda v: v > 0.0),
]


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _apply_max_hold(raw_pos: pd.Series, max_hold: int) -> pd.Series:
    """Force position to flat after max_hold consecutive long days."""
    pos = raw_pos.copy().values.astype(float)
    hold = 0
    for i in range(len(pos)):
        if pos[i] == 1:
            hold += 1
            if hold > max_hold:
                pos[i] = 0.0
                hold = 0
        else:
            hold = 0
    return pd.Series(pos, index=raw_pos.index)


def simulate(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """
    Run the long-only simulation on a slice of df (already has 'close' and 'signal').

    Signal at close of day T → position applied to close[T] → close[T+1] return.
    This is implemented by shifting the signal forward by 1 day.

    Returns df with added columns: price_return, position, cost, strat_return, equity, bh_equity.
    """
    df = df.copy().sort_index().dropna(subset=["close", "signal"])

    df["price_return"] = df["close"].pct_change().fillna(0.0)

    # Long-only: clip signal to [0, 1], then shift by 1 (signal from yesterday → position today)
    raw_pos = df["signal"].clip(lower=0).astype(float).shift(1).fillna(0.0)
    df["position"] = _apply_max_hold(raw_pos, cfg.max_hold_days)

    # Transaction cost paid when position changes (entry or exit)
    df["cost"] = df["position"].diff().abs().fillna(0.0) * cfg.cost_per_leg

    df["strat_return"] = df["position"] * df["price_return"] - df["cost"]
    df["equity"] = (1.0 + df["strat_return"]).cumprod()
    df["bh_equity"] = (1.0 + df["price_return"]).cumprod()
    return df


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(df: pd.DataFrame, label: str = "") -> dict:
    r = df["strat_return"]
    rf_daily = (1.0 + RF_ANNUAL) ** (1.0 / 365) - 1.0
    excess = r - rf_daily
    sharpe = float(excess.mean() / excess.std() * np.sqrt(365)) if excess.std() > 0 else 0.0

    eq = df["equity"]
    drawdown = (eq - eq.cummax()) / eq.cummax()
    max_dd = float(drawdown.min())
    total_ret = float(eq.iloc[-1] - 1.0) if len(eq) else 0.0

    bh_ret = float(df["bh_equity"].iloc[-1] - 1.0) if len(df) else 0.0

    in_market = r[df["position"] > 0]
    hit_rate = float((in_market > 0).mean()) if len(in_market) > 0 else float("nan")

    # Avg hold length = total days in position / number of entries
    entries = int((df["position"].diff().fillna(0) > 0).sum())
    avg_hold = float((df["position"] > 0).sum() / entries) if entries > 0 else 0.0

    trades = entries  # entries == exits for long-only

    ic_1d, pval_1d = _ic(df["net_flow_z"], df["price_return"], 1)
    ic_7d, pval_7d = _ic(df["net_flow_z"], df["price_return"], 7)
    ic_14d, pval_14d = _ic(df["net_flow_z"], df["price_return"], 14)

    return {
        "label": label,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "total_return": total_ret,
        "bh_total_return": bh_ret,
        "hit_rate": hit_rate,
        "avg_hold_days": avg_hold,
        "trades": trades,
        "ic_1d": ic_1d,       "ic_1d_pval": pval_1d,
        "ic_7d": ic_7d,       "ic_7d_pval": pval_7d,
        "ic_14d": ic_14d,     "ic_14d_pval": pval_14d,
    }


def _ic(signal_z: pd.Series, returns: pd.Series, forward_days: int) -> tuple[float, float]:
    """
    Pearson IC between signal_z[t] and sum(return[t+1 .. t+forward_days]).
    Uses the continuous z-score (not binarized signal) for more statistical power.
    """
    # fwd_ret[t] = rolling sum of forward_days returns starting from t+1
    fwd_ret = returns.rolling(forward_days).sum().shift(-forward_days)
    valid = signal_z.notna() & fwd_ret.notna()
    if valid.sum() < 30:
        return float("nan"), float("nan")
    c, p = stats.pearsonr(signal_z[valid], fwd_ret[valid])
    return float(c), float(p)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _fmt(val, fmt: str) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "n/a"
    return fmt.format(val)


METRIC_ROWS: list[tuple[str, str, str]] = [
    ("Annualized Sharpe",     "sharpe",          "{:.2f}"),
    ("Max drawdown",          "max_drawdown",     "{:.1%}"),
    ("Total return",          "total_return",     "{:.1%}"),
    ("BTC buy-hold return",   "bh_total_return",  "{:.1%}"),
    ("Hit rate",              "hit_rate",         "{:.1%}"),
    ("Avg hold (days)",       "avg_hold_days",    "{:.1f}"),
    ("# Entries",             "trades",           "{:d}"),
    ("IC(1d) / p-val",        None,               None),   # separator
    ("IC(7d) / p-val",        None,               None),
    ("IC(14d) / p-val",       None,               None),
]


def print_report(train: dict, oos: dict | None = None) -> None:
    w = 22
    header = f"  {'Metric':<30}  {'Train 2021–2023':>{w}}"
    if oos:
        header += f"  {'OOS 2024–2025':>{w}}"
    sep = "=" * len(header)

    print(f"\n{sep}")
    print(header)
    print(sep)

    simple_rows = [
        ("Annualized Sharpe",   "sharpe",         "{:.3f}"),
        ("Max drawdown",        "max_drawdown",    "{:.1%}"),
        ("Total return",        "total_return",    "{:.1%}"),
        ("BTC buy-hold",        "bh_total_return", "{:.1%}"),
        ("Hit rate",            "hit_rate",        "{:.1%}"),
        ("Avg hold days",       "avg_hold_days",   "{:.1f}"),
        ("# Entries",           "trades",          "{:d}"),
    ]
    ic_rows = [(1, "ic_1d", "ic_1d_pval"), (7, "ic_7d", "ic_7d_pval"), (14, "ic_14d", "ic_14d_pval")]

    for label, key, fmt in simple_rows:
        tv = _fmt(train.get(key), fmt)
        line = f"  {label:<30}  {tv:>{w}}"
        if oos:
            line += f"  {_fmt(oos.get(key), fmt):>{w}}"
        print(line)

    print(f"  {'-'*30}  {'-'*w}" + (f"  {'-'*w}" if oos else ""))

    for days, ic_key, pval_key in ic_rows:
        tv = f"{_fmt(train.get(ic_key), '{:.4f}')} / {_fmt(train.get(pval_key), '{:.3f}')}"
        line = f"  {'IC(' + str(days) + 'd) / p-val':<30}  {tv:>{w}}"
        if oos:
            ov = f"{_fmt(oos.get(ic_key), '{:.4f}')} / {_fmt(oos.get(pval_key), '{:.3f}')}"
            line += f"  {ov:>{w}}"
        print(line)

    print(sep)

    print("\n  GATE CHECK  (all must pass before building live harness)\n")
    all_pass = True
    for desc, threshold, fn in TRAIN_GATE:
        key = {
            "Sharpe (train)":       "sharpe",
            "Max drawdown (train)": "max_drawdown",
            "IC(7d) (train)":       "ic_7d",
            "IC(7d) p-val (train)": "ic_7d_pval",
        }[desc]
        val = train.get(key)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            result = "??  (insufficient data)"
            all_pass = False
        elif fn(val):
            result = f"PASS   ({val:.4g} {threshold})"
        else:
            result = f"FAIL   ({val:.4g} not {threshold})"
            all_pass = False
        print(f"    {desc:<35}  {result}")

    if oos:
        for desc, threshold, fn in OOS_GATE:
            val = oos.get("total_return")
            if val is None or (isinstance(val, float) and np.isnan(val)):
                result = "??  (insufficient data)"
                all_pass = False
            elif fn(val):
                result = f"PASS   ({val:.1%} {threshold})"
            else:
                result = f"FAIL   ({val:.1%} not {threshold})"
                all_pass = False
            print(f"    {desc:<35}  {result}")

    print()
    if all_pass and oos:
        print("  >>> ALL GATES PASSED — proceed to Phase 2 (build live on-chain harness)")
    elif all_pass and not oos:
        print("  >>> In-sample gates passed. Run with --oos for the final gate (one shot).")
    else:
        print("  >>> GATE FAILED — do not build live harness. Investigate signal or try variants.")
    print()


def save_equity_plot(train_df: pd.DataFrame, oos_df: pd.DataFrame | None, path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("matplotlib not installed — skipping plot. Add it with: uv add matplotlib")
        return

    combined = pd.concat([train_df, oos_df]) if oos_df is not None else train_df
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), gridspec_kw={"height_ratios": [3, 1]}, sharex=True)

    # Equity curves
    ax1.plot(combined.index, combined["equity"], label="Net-flow strategy", color="#1976D2", linewidth=1.5)
    ax1.plot(combined.index, combined["bh_equity"], label="BTC buy-hold", color="#FF8F00", linewidth=1.2, alpha=0.7)
    if oos_df is not None:
        ax1.axvline(oos_df.index[0], color="#555", linestyle="--", linewidth=1, alpha=0.6, label="OOS start")
        ax1.axvspan(oos_df.index[0], oos_df.index[-1], alpha=0.04, color="gray")
    ax1.set_ylabel("Equity (start = 1.0)")
    ax1.set_title("BTC Exchange Net-Flow Strategy — Equity Curve")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, alpha=0.25)

    # Signal z-score with long/short threshold bands
    ax2.plot(combined.index, combined["net_flow_z"], color="#7B1FA2", linewidth=0.8, alpha=0.8, label="Net-flow z")
    ax2.axhline(1.0, color="#e53935", linestyle="--", linewidth=0.8, alpha=0.6, label="+1 (dist)")
    ax2.axhline(-1.0, color="#43a047", linestyle="--", linewidth=0.8, alpha=0.6, label="-1 (accum)")
    ax2.axhline(0, color="gray", linewidth=0.4)
    ax2.fill_between(
        combined.index,
        combined["net_flow_z"].clip(upper=0),
        0, alpha=0.18, color="#43a047",
    )
    ax2.set_ylabel("Z-score")
    ax2.set_ylim(-5, 5)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.25)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Equity curve saved → {path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="BTC exchange net-flow backtest",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--oos", action="store_true",
        help="Include OOS evaluation.\nWARNING: Only run once, after in-sample clears all gates.\nRunning repeatedly to tune = p-hacking.",
    )
    parser.add_argument("--plot", action="store_true", help="Save equity curve PNG to output/equity_curve.png")
    parser.add_argument("--short",     type=int,   default=7,    help="Short MA window days (default 7)")
    parser.add_argument("--long",      type=int,   default=90,   help="Long MA window days (default 90)")
    parser.add_argument("--threshold", type=float, default=1.0,  help="Z-score signal threshold (default 1.0)")
    parser.add_argument("--max-hold",  type=int,   default=14,   help="Max hold days before forced exit (default 14)")
    args = parser.parse_args()

    prices_csv = DATA_DIR / "btc_prices.csv"
    flows_csv = DATA_DIR / "btc_flows.csv"
    if not prices_csv.exists() or not flows_csv.exists():
        raise SystemExit(
            f"\nData files not found in {DATA_DIR}/\n"
            "Fetch first: GLASSNODE_API_KEY=<key> uv run python -m onchain.backtest.fetch_data\n"
        )

    cfg = BacktestConfig(
        short_window=args.short,
        long_window=args.long,
        threshold=args.threshold,
        max_hold_days=args.max_hold,
    )

    raw = load_data(prices_csv, flows_csv)
    df = compute_signal(raw, cfg.short_window, cfg.long_window, cfg.threshold)

    print(f"\nBacktest config: short={cfg.short_window}d long={cfg.long_window}d "
          f"threshold=±{cfg.threshold} max_hold={cfg.max_hold_days}d "
          f"cost={cfg.cost_per_leg*2*100:.2f}% rt")

    train_df = simulate(df.loc[TRAIN_START:TRAIN_END], cfg)
    train_metrics = compute_metrics(train_df, label="Train 2021–2023")

    oos_df, oos_metrics = None, None
    if args.oos:
        oos_df = simulate(df.loc[OOS_START:OOS_END], cfg)
        oos_metrics = compute_metrics(oos_df, label="OOS 2024–2025")

    print_report(train_metrics, oos_metrics)

    if args.plot:
        save_equity_plot(train_df, oos_df, OUTPUT_DIR / "equity_curve.png")


if __name__ == "__main__":
    main()
