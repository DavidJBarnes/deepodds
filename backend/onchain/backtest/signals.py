"""
Signal computation for the BTC exchange net-flow strategy.
All functions are pure (pandas in, pandas out — no I/O, no side effects).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_data(prices_csv: str | Path, flows_csv: str | Path) -> pd.DataFrame:
    """
    Load and inner-join price + flow CSVs into a single DataFrame indexed by date.

    Returns columns: close, exchange_inflow_usd, exchange_outflow_usd
    """
    prices = pd.read_csv(prices_csv, parse_dates=["date"], index_col="date")
    flows = pd.read_csv(flows_csv, parse_dates=["date"], index_col="date")
    df = prices.join(flows, how="inner").sort_index()
    df.index = pd.DatetimeIndex(df.index).normalize()  # ensure midnight, no tz
    return df


def compute_signal(
    df: pd.DataFrame,
    short_window: int = 7,
    long_window: int = 90,
    threshold: float = 1.0,
) -> pd.DataFrame:
    """
    Add net_flow_usd, net_flow_z, and signal columns to df.

    net_flow_z is the z-score of the short MA vs long MA of net exchange flow.
    Positive z → more coins flowing INTO exchanges (distribution pressure → bearish).
    Negative z → more coins flowing OUT OF exchanges (accumulation → bullish).

    signal values:
      1  = long (net_flow_z < -threshold)
     -1  = short (net_flow_z > +threshold) — not used in long-only paper harness
      0  = flat
    """
    df = df.copy()
    df["net_flow_usd"] = df["exchange_inflow_usd"] - df["exchange_outflow_usd"]

    short_ma = df["net_flow_usd"].rolling(short_window, min_periods=short_window).mean()
    long_ma = df["net_flow_usd"].rolling(long_window, min_periods=long_window).mean()
    long_std = df["net_flow_usd"].rolling(long_window, min_periods=long_window).std()

    # Clip std to avoid exploding z-scores when series is nearly constant.
    df["net_flow_z"] = (short_ma - long_ma) / long_std.clip(lower=long_std[long_std > 0].quantile(0.05))
    df["signal"] = 0
    df.loc[df["net_flow_z"] < -threshold, "signal"] = 1
    df.loc[df["net_flow_z"] > threshold, "signal"] = -1
    return df
