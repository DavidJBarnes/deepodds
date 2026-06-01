"""Train an XGBoost model for Kalshi climate (daily max/min/precip) contracts.

Inference uses Open-Meteo's daily forecast as the spot estimate for the
contract's resolution date. Without a historical forecast archive, we use
day d-1's actual daily extreme as a proxy for "what the forecast for day d
looked like" — this overstates forecast error (real forecasts beat naive
persistence) but the resulting model is conservative and matches the
fallback's assumption surface.
"""

import logging
import math
import os
import random
import shutil
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import xgboost as xgb

from app.services.weather_client import (
    KIND_DAILY_MAX,
    KIND_DAILY_MIN,
    SUPPORTED_CITIES,
    get_daily_extreme_history,
)

logger = logging.getLogger(__name__)

MODEL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "core", "xgboost_climate_model.json"
)
SNAPSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "core", "models", "climate"
)


def _snapshot_path() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return os.path.join(SNAPSHOT_DIR, f"v_{ts}.json")

# Match the feature ordering used by the probability model at inference time.
FEATURE_COLS = [
    "z_floor",
    "z_cap",
    "z_width",
    "forecast_sigma",
    "days_ahead",
    "is_greater",
    "is_less",
    "is_between",
] + [f"is_{c.lower()}" for c in SUPPORTED_CITIES]

_BIG_Z = 6.0  # ±∞ proxy for open-ended strikes


def _rolling_sigma(values: list[float], window: int = 60) -> list[float]:
    """Per-day rolling stddev of day-to-day changes."""
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    sigmas = [3.0]  # day 0 has no prior diff
    for i in range(len(diffs)):
        w = diffs[max(0, i - window + 1): i + 1]
        if len(w) < 5:
            sigmas.append(3.0)
            continue
        mean = sum(w) / len(w)
        var = sum((d - mean) ** 2 for d in w) / (len(w) - 1)
        sigmas.append(math.sqrt(var) if var > 0 else 3.0)
    return sigmas


def generate_synthetic_data(city: str, kind: str, values: list[float]) -> pd.DataFrame:
    """Generate synthetic Kalshi daily-extreme contracts from historical data.

    For each day d:
    - "predicted" = day d-1's actual extreme (naive persistence proxy for forecast)
    - "actual" = day d's actual extreme
    - Generate strike levels at ±N×sigma offsets and check whether actual
      satisfies greater/less/between conditions.
    """
    rng = random.Random(42 + sum(ord(c) for c in city))
    if len(values) < 60:
        return pd.DataFrame()

    sigmas = _rolling_sigma(values, window=60)
    rows = []

    for i in range(1, len(values)):
        predicted = values[i - 1]
        actual = values[i]
        sigma = max(sigmas[i], 0.5)

        # Strike offsets in units of sigma, half-widths for between markets
        z_offsets = [-2.5, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.5]
        half_widths = [0.25, 0.5, 1.0]
        # days_ahead: most Kalshi climate contracts trade 1-3 days out
        for d_ahead in [1, 2, 3]:
            scaled_sigma = sigma * math.sqrt(d_ahead)
            for offset in z_offsets:
                strike = predicted + scaled_sigma * offset

                # Greater
                rows.append({
                    "city": city,
                    "z_floor": (strike - predicted) / scaled_sigma,
                    "z_cap": _BIG_Z,
                    "z_width": _BIG_Z - (strike - predicted) / scaled_sigma,
                    "forecast_sigma": sigma,
                    "days_ahead": float(d_ahead),
                    "is_greater": 1.0, "is_less": 0.0, "is_between": 0.0,
                    "outcome": 1 if actual > strike else 0,
                })
                # Less
                rows.append({
                    "city": city,
                    "z_floor": -_BIG_Z,
                    "z_cap": (strike - predicted) / scaled_sigma,
                    "z_width": (strike - predicted) / scaled_sigma - (-_BIG_Z),
                    "forecast_sigma": sigma,
                    "days_ahead": float(d_ahead),
                    "is_greater": 0.0, "is_less": 1.0, "is_between": 0.0,
                    "outcome": 1 if actual < strike else 0,
                })
                # Between (only for offsets near forecast)
                if -1.5 <= offset <= 1.5:
                    half_w = rng.choice(half_widths) * scaled_sigma
                    floor = strike - half_w
                    cap = strike + half_w
                    rows.append({
                        "city": city,
                        "z_floor": (floor - predicted) / scaled_sigma,
                        "z_cap": (cap - predicted) / scaled_sigma,
                        "z_width": (cap - floor) / scaled_sigma,
                        "forecast_sigma": sigma,
                        "days_ahead": float(d_ahead),
                        "is_greater": 0.0, "is_less": 0.0, "is_between": 1.0,
                        "outcome": 1 if floor <= actual <= cap else 0,
                    })

    return pd.DataFrame(rows)


async def train_and_save_climate_model() -> tuple[bool, str | None]:
    """Train + save the climate XGBoost model.

    Returns (success, snapshot_path). See train_model.train_and_save_model
    for the snapshot semantics.
    """
    logger.info("Starting climate ML training...")

    all_data = []
    for city in SUPPORTED_CITIES:
        for kind in (KIND_DAILY_MAX, KIND_DAILY_MIN):
            values = await get_daily_extreme_history(city, kind, days=365 * 2)
            if not values:
                logger.warning("No history for %s/%s — skipping", city, kind)
                continue
            df_city = generate_synthetic_data(city, kind, values)
            if not df_city.empty:
                all_data.append(df_city)

    if not all_data:
        logger.error("No climate training data generated. Training failed.")
        return False, None

    df = pd.concat(all_data, ignore_index=True)
    logger.info("Generated %d synthetic climate samples", len(df))

    for city in SUPPORTED_CITIES:
        df[f"is_{city.lower()}"] = (df["city"] == city).astype(int)

    X = df[FEATURE_COLS]
    y = df["outcome"]

    rng = np.random.default_rng(42)
    shuffled = rng.permutation(len(df))
    split = int(len(df) * 0.8)
    train_idx, test_idx = shuffled[:split], shuffled[split:]
    X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
    X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtest = xgb.DMatrix(X_test, label=y_test)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 5,
        "eta": 0.05,
        "subsample": 0.7,
        "colsample_bytree": 0.7,
        "gamma": 1.0,
        "min_child_weight": 10,
        "seed": 42,
    }

    bst = xgb.train(
        params, dtrain, num_boost_round=300,
        evals=[(dtest, "eval"), (dtrain, "train")],
        early_stopping_rounds=20, verbose_eval=False,
    )

    preds = bst.predict(dtest)
    brier = float(np.mean((preds - y_test) ** 2))
    logloss = float(-np.mean(y_test * np.log(np.clip(preds, 1e-6, 1)) + (1 - y_test) * np.log(np.clip(1 - preds, 1e-6, 1))))
    logger.info("Climate training done. n=%d brier=%.4f logloss=%.4f", len(df), brier, logloss)

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(MODEL_FILE), exist_ok=True)
    snapshot = _snapshot_path()
    bst.save_model(snapshot)
    shutil.copyfile(snapshot, MODEL_FILE)
    logger.info("Climate model saved to snapshot %s + canonical %s", snapshot, MODEL_FILE)
    return True, snapshot
