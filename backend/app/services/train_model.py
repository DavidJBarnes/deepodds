import asyncio
import logging
import math
import os
import shutil
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import xgboost as xgb

from app.services.binance_client import _fetch_klines
from app.services.probability_model import series_to_underlying

logger = logging.getLogger(__name__)

MODEL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "xgboost_model.json")
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "models", "crypto")


def _snapshot_path() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return os.path.join(SNAPSHOT_DIR, f"v_{ts}.json")

SUPPORTED_SYMBOLS = ["BTC", "ETH", "XRP", "SOL", "DOGE", "BNB"]


async def fetch_historical_data_for_training(symbol: str, hours: int = 1000) -> list[float] | None:
    """Fetch close prices from Binance klines for training."""
    result = await _fetch_klines(symbol, hours=hours, interval="1h")
    if result is None:
        return None
    closes, _ = result
    return closes


def generate_synthetic_data(symbol: str, closes: list[float]) -> pd.DataFrame:
    """Generates synthetic Kalshi range-bound contracts on historical closes.

    Simplifies features and includes transaction spreads to combat overfitting
    and model real-world friction.
    """
    df_list = []
    n = len(closes)
    if n < 50:
        return pd.DataFrame()

    # Calculate rolling volatilities to scale synthetic ranges realistically
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
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

        for t_hours in [2, 4, 8, 12, 18, 24]:
            if i + t_hours >= n:
                continue

            future_spot = closes[i + t_hours]
            t_years = t_hours / (365.25 * 24)

            # Mix vol-scaled and fixed-percentage widths
            widths = []
            for mult in [0.2, 0.5, 0.8, 1.2]:
                w = spot * vol * math.sqrt(t_years) * mult
                if w > 0:
                    widths.append(w)
            for pct in [0.005, 0.01, 0.02, 0.03, 0.05]:
                widths.append(spot * pct)

            # Generate ranges at various offsets from spot so the model
            # sees ATM through deep OTM. sigma = 1 std dev of price move.
            sigma = spot * vol * math.sqrt(t_years)
            offsets = [-2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2]

            for width in widths:
                for offset in offsets:
                    center = spot + sigma * offset

                    floor = center - width / 2
                    cap = center + width / 2
                    if cap <= 0:
                        continue

                    won = 1 if floor <= future_spot <= cap else 0

                    dist_floor = (spot - floor) / spot
                    dist_cap = (cap - spot) / spot
                    range_width_pct = (cap - floor) / spot
                    rel_spot = (spot - floor) / (cap - floor) if cap > floor else 0.5

                    df_list.append({
                        "symbol": symbol,
                        "dist_floor": dist_floor,
                        "dist_cap": dist_cap,
                        "range_width_pct": range_width_pct,
                        "rel_spot": rel_spot,
                        "hours_to_expiry": float(t_hours),
                        "log_hours_to_expiry": math.log(float(t_hours)),
                        "vol_24h": vol,
                        "outcome": won
                    })

    return pd.DataFrame(df_list)


async def train_and_save_model() -> tuple[bool, str | None]:
    """Train + save the crypto XGBoost model.

    Returns (success, snapshot_path). On success a versioned snapshot is
    written under core/models/crypto/ and copied into the canonical model
    file. The caller persists the snapshot path on ModelTrainHistory and
    can roll back to a prior snapshot by copying it back over the
    canonical path.
    """
    logger.info("Starting SOTA Synthetic ML Model Training...")

    all_data = []

    for sym in SUPPORTED_SYMBOLS:
        closes = await fetch_historical_data_for_training(sym, hours=1500)
        if not closes:
            logger.warning("No closes fetched for %s, skipping", sym)
            continue
        df_sym = generate_synthetic_data(sym, closes)
        if not df_sym.empty:
            all_data.append(df_sym)

    if not all_data:
        logger.error("No training data generated across any symbols. Training failed.")
        return False, None

    df = pd.concat(all_data, ignore_index=True)
    logger.info("Generated %d synthetic training samples", len(df))

    # One-hot encode the asset symbol
    for sym in SUPPORTED_SYMBOLS:
        df[f"is_{sym.lower()}"] = (df["symbol"] == sym).astype(int)

    feature_cols = [
        "dist_floor", "dist_cap", "range_width_pct", "rel_spot",
        "hours_to_expiry", "log_hours_to_expiry", "vol_24h"
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

    # Train model with tighter regularization to prevent overfitting
    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 4,          # Slashed from 5 to 4 to reduce overfitting
        "eta": 0.05,             # Lower learning rate for smoother boundaries
        "subsample": 0.7,        # Subsampling rows for regularization
        "colsample_bytree": 0.7,  # Subsampling columns
        "gamma": 1.0,            # Minimum loss reduction to make a split (tighter splits)
        "seed": 42
    }

    evallist = [(dtest, "eval"), (dtrain, "train")]
    num_round = 100

    bst = xgb.train(params, dtrain, num_round, evals=evallist, verbose_eval=False)

    # Evaluate LogLoss
    preds = bst.predict(dtest)
    brier = np.mean((preds - y_test) ** 2)
    logger.info("Model training complete. Brier score on synthetic test set: %.4f", brier)

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(MODEL_FILE), exist_ok=True)
    snapshot = _snapshot_path()
    bst.save_model(snapshot)
    shutil.copyfile(snapshot, MODEL_FILE)
    logger.info("Crypto model saved to snapshot %s + canonical %s", snapshot, MODEL_FILE)
    return True, snapshot
