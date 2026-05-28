import logging
import math
import os
from dataclasses import dataclass
import xgboost as xgb
import numpy as np

logger = logging.getLogger(__name__)

SERIES_PREFIX = "KX"
SUPPORTED_SYMBOLS = ["BTC", "ETH", "XRP", "SOL", "DOGE", "BNB"]
MODEL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "xgboost_model.json")

_bst = None


def get_booster():
    """Lazily loads the saved XGBoost model booster into memory."""
    global _bst
    if _bst is None:
        if os.path.exists(MODEL_FILE):
            try:
                _bst = xgb.Booster()
                _bst.load_model(MODEL_FILE)
                logger.info("XGBoost model loaded successfully from %s", MODEL_FILE)
            except Exception:
                logger.exception("Failed to load XGBoost model from %s", MODEL_FILE)
        else:
            logger.warning("XGBoost model file not found at %s. Running fallback predictions.", MODEL_FILE)
    return _bst


def reload_booster():
    """Forces reloading of the XGBoost booster from disk (useful after retraining)."""
    global _bst
    _bst = None
    return get_booster()


@dataclass
class FairValueResult:
    model_prob: float
    market_prob: float
    edge: float
    frequency_edge: float
    spot_range_edge: float
    underlying_price: float
    realized_vol: float
    realized_drift: float
    implied_vol: float
    blended_vol: float
    time_to_expiry_hours: float
    strike_type: str
    floor_strike: float | None
    cap_strike: float | None


def series_to_underlying(series_ticker: str) -> str | None:
    if not isinstance(series_ticker, str):
        return None
    if not series_ticker.startswith(SERIES_PREFIX):
        return None
    symbol = series_ticker[len(SERIES_PREFIX):]
    return symbol or None


def predict_ml_probability(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    vol: float,
    market_price: float,
    drift: float = 0.0,
    symbol: str = "BTC",
) -> FairValueResult:
    """Predicts range/binary option probability using the trained SOTA XGBoost model.

    If the model is not loaded, gracefully falls back to a symmetric normal-CDF approximation.
    """
    def _fallback_prob() -> float:
        # Fallback approximation using a standard normal CDF
        if t_years <= 1e-10 or vol <= 1e-10:
            if strike_type == "between":
                return 1.0 if floor_strike <= spot <= cap_strike else 0.0
            elif strike_type == "greater":
                return 1.0 if spot > floor_strike else 0.0
            else:
                return 1.0 if spot < cap_strike else 0.0

        # Simple CDF symmetric random walk
        sqrt_t = math.sqrt(t_years)
        def cdf(k: float) -> float:
            val = (math.log(spot / k) + (drift - vol**2 / 2) * t_years) / (vol * sqrt_t)
            return 0.5 * (1 + math.erf(val / math.sqrt(2)))

        if strike_type == "between":
            return cdf(cap_strike) - cdf(floor_strike)
        elif strike_type == "greater":
            return 1.0 - cdf(floor_strike)
        else:
            return cdf(cap_strike)

    # Clean strike bounds for input compatibility
    f_strike = floor_strike if floor_strike is not None else spot * 0.5
    c_strike = cap_strike if cap_strike is not None else spot * 1.5

    hours_to_expiry = t_years * 365.25 * 24
    if hours_to_expiry <= 0:
        hours_to_expiry = 0.01

    bst = get_booster()
    if bst is None:
        model_prob = _fallback_prob()
    else:
        # 1. Feature Engineering Real-time Vector (Simplified, Robust, No Overfitting)
        dist_floor = (spot - f_strike) / spot
        dist_cap = (c_strike - spot) / spot
        range_width_pct = (c_strike - f_strike) / spot
        rel_spot = (spot - f_strike) / (c_strike - f_strike) if c_strike > f_strike else 0.5

        # Feature mapping
        feat_dict = {
            "dist_floor": [dist_floor],
            "dist_cap": [dist_cap],
            "range_width_pct": [range_width_pct],
            "rel_spot": [rel_spot],
            "hours_to_expiry": [hours_to_expiry],
            "log_hours_to_expiry": [math.log(hours_to_expiry)],
            "vol_24h": [vol],
        }

        # One-hot encoding the target asset
        sym_upper = symbol.upper()
        for s in SUPPORTED_SYMBOLS:
            feat_dict[f"is_{s.lower()}"] = [1 if s == sym_upper else 0]

        # Convert to matrix and predict
        try:
            import pandas as pd
            df = pd.DataFrame(feat_dict)
            dmatrix = xgb.DMatrix(df)
            preds = bst.predict(dmatrix)
            model_prob = float(preds[0])

            # Geometric guardrail to prevent ML extrapolation errors on extreme out-of-bounds inputs
            if strike_type == "between":
                std_dev = spot * vol * math.sqrt(t_years)
                if std_dev > 0:
                    if spot > c_strike + 3 * std_dev or spot < f_strike - 3 * std_dev:
                        model_prob = min(model_prob, 0.01)
        except Exception:
            logger.warning("ML prediction failed; falling back to CDF approximation")
            model_prob = _fallback_prob()

    # Model probability safety boundaries
    model_prob = max(0.0, min(1.0, model_prob))

    return FairValueResult(
        model_prob=model_prob,
        market_prob=market_price,
        edge=model_prob - market_price,
        frequency_edge=0.0,
        spot_range_edge=0.0,
        underlying_price=spot,
        realized_vol=vol,
        realized_drift=drift,
        implied_vol=0.0,
        blended_vol=vol,
        time_to_expiry_hours=hours_to_expiry,
        strike_type=strike_type,
        floor_strike=floor_strike,
        cap_strike=cap_strike,
    )


def compute_edge(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    sigma: float,
    market_price: float,
    drift: float = 0.0,
    symbol: str = "BTC",
) -> FairValueResult:
    """Compatibility wrapper that routes directly to our SOTA XGBoost predictor."""
    return predict_ml_probability(
        spot, floor_strike, cap_strike, strike_type, t_years, sigma, market_price,
        drift=drift, symbol=symbol
    )
