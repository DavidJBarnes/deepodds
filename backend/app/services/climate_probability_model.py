import logging
import math
import os
from dataclasses import dataclass

import xgboost as xgb

from app.services.weather_client import SUPPORTED_CITIES

logger = logging.getLogger(__name__)

MODEL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "core", "xgboost_climate_model.json"
)

_bst = None


def get_booster():
    global _bst
    if _bst is None:
        if os.path.exists(MODEL_FILE):
            try:
                _bst = xgb.Booster()
                _bst.load_model(MODEL_FILE)
                logger.info("Climate XGBoost model loaded from %s", MODEL_FILE)
            except Exception:
                logger.exception("Failed to load climate model from %s", MODEL_FILE)
        else:
            logger.warning("Climate model not found at %s. Using fallback.", MODEL_FILE)
    return _bst


def reload_booster():
    global _bst
    _bst = None
    return get_booster()


@dataclass
class ClimateFairValueResult:
    model_prob: float          # calibrated (post-Platt) — used for edge calc + signal gating
    raw_model_prob: float      # pre-Platt — preserved for future Platt refits
    market_prob: float
    edge: float
    forecast_value: float
    forecast_sigma: float
    days_ahead: int
    strike_type: str
    floor_strike: float | None
    cap_strike: float | None


FORECAST_SKILL_FACTOR = 0.4


def _scaled_sigma(forecast_sigma: float, days_ahead: int) -> float:
    """Convert day-to-day vol into a 1-day-ahead forecast-error sigma.

    Day-to-day vol overstates true forecast uncertainty since NWP models beat
    naive persistence (forecasts capture roughly 80% of next-day variance).
    The 0.4 skill factor is a rough calibration; the trained model learns the
    actual relationship from data.
    """
    if forecast_sigma <= 0:
        return 1.0
    base = forecast_sigma * FORECAST_SKILL_FACTOR
    return base * math.sqrt(max(days_ahead, 1))


def _normal_cdf(x: float, mu: float, sigma: float) -> float:
    if sigma <= 0:
        return 1.0 if x >= mu else 0.0
    z = (x - mu) / sigma
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _fallback_prob(
    forecast_value: float,
    floor: float | None,
    cap: float | None,
    strike_type: str,
    sigma: float,
) -> float:
    """Normal-CDF model: actual ~ N(forecast_value, sigma^2)."""
    if strike_type == "between":
        if floor is None or cap is None:
            return 0.5
        return _normal_cdf(cap, forecast_value, sigma) - _normal_cdf(
            floor, forecast_value, sigma
        )
    elif strike_type == "greater":
        if floor is None:
            return 0.5
        return 1.0 - _normal_cdf(floor, forecast_value, sigma)
    elif strike_type == "less":
        if cap is None:
            return 0.5
        return _normal_cdf(cap, forecast_value, sigma)
    return 0.5


def predict_climate_probability(
    forecast_value: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    forecast_sigma: float,
    market_price: float,
    city: str = "NYC",
    days_ahead: int = 1,
) -> ClimateFairValueResult:
    """Predict P(strike condition holds) given a daily forecast and its uncertainty.

    The forecast_value is the predicted daily max/min/precipitation for the
    contract's resolution date. forecast_sigma is the stddev of the forecast
    error (we use day-to-day vol as a proxy). days_ahead scales sigma.
    """
    sigma = _scaled_sigma(forecast_sigma, days_ahead)

    bst = get_booster()
    if bst is None:
        model_prob = _fallback_prob(
            forecast_value, floor_strike, cap_strike, strike_type, sigma
        )
    else:
        # Features expressed in sigma-units around the forecast so the model
        # generalizes across cities/seasons with very different temperature
        # scales.
        big = 6.0  # sigmas — proxy for ±∞ on open-ended strikes
        z_floor = (floor_strike - forecast_value) / sigma if floor_strike is not None else -big
        z_cap = (cap_strike - forecast_value) / sigma if cap_strike is not None else big

        feat = {
            "z_floor": [z_floor],
            "z_cap": [z_cap],
            "z_width": [z_cap - z_floor],
            "forecast_sigma": [forecast_sigma],
            "days_ahead": [float(days_ahead)],
            "is_greater": [1.0 if strike_type == "greater" else 0.0],
            "is_less": [1.0 if strike_type == "less" else 0.0],
            "is_between": [1.0 if strike_type == "between" else 0.0],
        }
        city_upper = city.upper()
        for c in SUPPORTED_CITIES:
            feat[f"is_{c.lower()}"] = [1.0 if c == city_upper else 0.0]

        try:
            import pandas as pd
            df = pd.DataFrame(feat)
            dmatrix = xgb.DMatrix(df)
            model_prob = float(bst.predict(dmatrix)[0])
        except Exception:
            logger.warning("Climate ML prediction failed; using fallback")
            model_prob = _fallback_prob(
                forecast_value, floor_strike, cap_strike, strike_type, sigma
            )

    raw_model_prob = max(0.01, min(0.99, model_prob))

    # Apply Platt calibration on top of the raw model. Pass-through when no
    # calibrator has been fitted yet (n < MIN_FIT_N at the last refit).
    from app.services.climate_calibration import apply_platt
    calibrated = apply_platt(raw_model_prob)
    if calibrated != raw_model_prob:
        logger.debug("Platt: %.3f -> %.3f (%s)", raw_model_prob, calibrated, city)
    model_prob = max(0.01, min(0.99, calibrated))

    return ClimateFairValueResult(
        model_prob=model_prob,
        raw_model_prob=raw_model_prob,
        market_prob=market_price,
        edge=model_prob - market_price,
        forecast_value=forecast_value,
        forecast_sigma=sigma,
        days_ahead=days_ahead,
        strike_type=strike_type,
        floor_strike=floor_strike,
        cap_strike=cap_strike,
    )


def compute_climate_edge(
    forecast_value: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    forecast_sigma: float,
    market_price: float,
    city: str = "NYC",
    days_ahead: int = 1,
) -> ClimateFairValueResult:
    return predict_climate_probability(
        forecast_value, floor_strike, cap_strike, strike_type,
        forecast_sigma, market_price, city=city, days_ahead=days_ahead,
    )
