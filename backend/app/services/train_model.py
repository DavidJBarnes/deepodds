import asyncio
import logging
import math
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import xgboost as xgb

from app.services.binance_client import _fetch_klines
from app.services.probability_model import series_to_underlying

logger = logging.getLogger(__name__)

MODEL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "xgboost_model.json")

SUPPORTED_SYMBOLS = ["BTC", "ETH", "XRP", "SOL", "DOGE", "BNB"]


async def fetch_historical_data_for_training(symbol: str, hours: int = 1000) -> list[float] | None:
    """Fetch close prices from Binance klines for training."""
    # We fetch hourly and 5m bars to get a dense dataset.
    # 5m klines limit is 1000 bars. To get longer history, we fetch daily/hourly,
    # but for synthetic range generation, 1000 bars of 1h or 15m is a great dataset.
    # Let's get 1000 bars of 15m (which is 250 hours / 10 days).
    # To get 1 year of data, we would need to fetch multiple times or use public archived data,
    # but we can get an extremely robust dataset of the last 1000 15m bars (10 days) of high-frequency
    # data to train a highly reactive regime-aware micro-booster, or fetch 1h bars.
    # Let's use 1h bars to get 1000 hours (~41 days) of hourly data for a wider regime window.
    result = await _fetch_klines(symbol, hours=hours, interval="1h")
    if result is None:
        return None
    closes, _ = result
    return closes


def generate_synthetic_data(symbol: str, closes: list[float]) -> pd.DataFrame:
    """Generates synthetic Kalshi range-bound contracts on historical closes.

    For each timestamp, simulates various times to expiry and strike ranges,
    determining if the future price lands in-range (Y=1) or out-of-range (Y=0).
    """
    df_list = []
    n = len(closes)
    if n < 50:
        return pd.DataFrame()

    # Calculate rolling volatilities to scale synthetic ranges realistically
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    # Rolling standard deviation over 24h (24 bars)
    vol_24h = []
    for i in range(n):
        if i < 24:
            vol_24h.append(0.5)  # default
        else:
            window = log_returns[i - 24:i]
            mean_r = sum(window) / len(window)
            var = sum((r - mean_r) ** 2 for r in window) / (len(window) - 1)
            vol_24h.append(math.sqrt(var) * math.sqrt(365.25 * 24))

    for i in range(24, n - 24):
        spot = closes[i]
        vol = vol_24h[i]

        # For each historical spot price, generate multiple synthetic contracts
        for t_hours in [2, 4, 8, 12, 18, 24]:
            if i + t_hours >= n:
                continue

            future_spot = closes[i + t_hours]
            t_years = t_hours / (365.25 * 24)

            # Generate multiple strike widths (scaled by volatility)
            for width_multiplier in [0.2, 0.5, 0.8, 1.2]:
                width = spot * vol * math.sqrt(t_years) * width_multiplier
                if width <= 0:
                    continue

                # Center the range around spot, optionally with a random drift shift
                drift_shift = spot * np.random.normal(0, vol * math.sqrt(t_years) * 0.3)
                center = spot + drift_shift

                floor = center - width / 2
                cap = center + width / 2

                # Label: Y=1 if future price ended inside the range
                won = 1 if floor <= future_spot <= cap else 0

                # Compute features at time i
                dist_floor = (spot - floor) / spot
                dist_cap = (cap - spot) / spot
                range_width_pct = (cap - floor) / spot
                rel_spot = (spot - floor) / (cap - floor) if cap > floor else 0.5

                # Multi-scale realized volatility
                window_4h = log_returns[max(0, i - 4):i]
                vol_4h = math.sqrt(sum(r**2 for r in window_4h) / len(window_4h)) * math.sqrt(365.25 * 24) if window_4h else vol

                # Multi-scale drift (momentum)
                drift_1h = log_returns[i - 1] * 365.25 * 24 if i > 0 else 0.0
                drift_4h = sum(log_returns[max(0, i - 4):i]) / min(4, i) * 365.25 * 24 if i > 4 else 0.0
                drift_24h = sum(log_returns[max(0, i - 24):i]) / min(24, i) * 365.25 * 24 if i > 24 else 0.0

                df_list.append({
                    "symbol": symbol,
                    "dist_floor": dist_floor,
                    "dist_cap": dist_cap,
                    "range_width_pct": range_width_pct,
                    "rel_spot": rel_spot,
                    "hours_to_expiry": float(t_hours),
                    "log_hours_to_expiry": math.log(float(t_hours)),
                    "vol_4h": vol_4h,
                    "vol_24h": vol,
                    "vol_ratio": vol_4h / vol if vol > 0 else 1.0,
                    "drift_1h": drift_1h,
                    "drift_4h": drift_4h,
                    "drift_24h": drift_24h,
                    "outcome": won
                })

    return pd.DataFrame(df_list)


def train_and_save_model() -> bool:
    """Fetches Binance klines, generates synthetic data, trains XGBoost and saves to JSON."""
    logger.info("Starting SOTA Synthetic ML Model Training...")

    all_data = []
    loop = asyncio.get_event_loop()

    for sym in SUPPORTED_SYMBOLS:
        closes = loop.run_until_complete(fetch_historical_data_for_training(sym, hours=1500))
        if not closes:
            logger.warning("No closes fetched for %s, skipping", sym)
            continue
        df_sym = generate_synthetic_data(sym, closes)
        if not df_sym.empty:
            all_data.append(df_sym)

    if not all_data:
        logger.error("No training data generated across any symbols. Training failed.")
        return False

    df = pd.concat(all_data, ignore_index=True)
    logger.info("Generated %d synthetic training samples", len(df))

    # One-hot encode the asset symbol
    for sym in SUPPORTED_SYMBOLS:
        df[f"is_{sym.lower()}"] = (df["symbol"] == sym).astype(int)

    feature_cols = [
        "dist_floor", "dist_cap", "range_width_pct", "rel_spot",
        "hours_to_expiry", "log_hours_to_expiry", "vol_4h", "vol_24h", "vol_ratio",
        "drift_1h", "drift_4h", "drift_24h"
    ] + [f"is_{sym.lower()}" for sym in SUPPORTED_SYMBOLS]

    X = df[feature_cols]
    y = df["outcome"]

    # Shuffle and split
    shuffled_idx = np.random.permutation(len(df))
    split_point = int(len(df) * 0.8)
    train_idx, test_idx = shuffled_idx[:split_point], shuffled_idx[split_point:]

    X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
    X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

    # Convert to DMatrix
    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtest = xgb.DMatrix(X_test, label=y_test)

    # Train model
    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 5,
        "eta": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "seed": 42
    }

    evallist = [(dtest, "eval"), (dtrain, "train")]
    num_round = 80

    bst = xgb.train(params, dtrain, num_round, evals=evallist, verbose_eval=False)

    # Evaluate LogLoss
    preds = bst.predict(dtest)
    brier = np.mean((preds - y_test) ** 2)
    logger.info("Model training complete. Brier score on synthetic test set: %.4f", brier)

    # Create directories if they do not exist
    os.makedirs(os.path.dirname(MODEL_FILE), exist_ok=True)
    bst.save_model(MODEL_FILE)
    logger.info("Model saved successfully to %s", MODEL_FILE)
    return True
