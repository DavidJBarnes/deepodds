"""Platt scaling on top of the climate XGBoost model.

The raw climate model has known per-bucket miscalibration (e.g., predictions
in the 0.20–0.30 band see ~6% real win rate; the 0.80–0.90 band has been
0/3 on Kalshi outcomes). Retraining doesn't fix this — synthetic training
data has no awareness of these per-bucket errors.

Platt scaling fits a one-feature logistic regression mapping raw model_prob
→ calibrated_prob using real (model_prob, won) pairs from Kalshi-settled
signals. The model itself isn't retrained; the calibrator sits on top.

If fewer than MIN_FIT_N useful settled signals exist, or if all are wins /
all are losses, the calibrator is not written and predictions pass through
unchanged.

The calibrator persists to backend/app/core/climate_platt.json with the
fitted (a, b) coefficients plus metadata for diagnostics.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.signal import Signal

logger = logging.getLogger(__name__)

CALIBRATOR_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "core", "climate_platt.json"
)
MIN_FIT_N = 50
VENUE = "kalshi_climate"
SETTLED = ("settled_win", "settled_loss", "settled_breakeven")

_cached: dict | None = None


def _fetch_training_pairs(session: Session) -> list[tuple[float, int]]:
    """Pull (model_prob, won) from cleanly Kalshi-settled climate signals."""
    rows = session.execute(
        select(
            Signal.model_prob,
            Signal.status,
            Signal.exit_price,
            Signal.filled_at,
            Signal.resolved_at,
        ).where(
            Signal.venue == VENUE,
            Signal.status.in_(SETTLED),
            Signal.model_prob.isnot(None),
        )
    ).all()
    pairs: list[tuple[float, int]] = []
    for mp, st, ex, f, r in rows:
        long_held = r and f and (r - f) > timedelta(hours=2)
        real = ex in (0.0, 1.0)
        if not (real or long_held):
            continue
        won = 1 if st == "settled_win" else 0
        pairs.append((float(mp), won))
    return pairs


def _nll(params: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    a, b = params
    z = a * x + b
    p = expit(z)
    eps = 1e-12
    return -float(np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))


def _fit_logistic(pairs: list[tuple[float, int]]) -> tuple[float, float] | None:
    """Fit y ~ sigmoid(a * x + b). Returns (a, b) or None on failure."""
    x = np.array([p[0] for p in pairs], dtype=float)
    y = np.array([p[1] for p in pairs], dtype=float)
    try:
        result = minimize(
            _nll, x0=np.array([1.0, 0.0]), args=(x, y), method="BFGS"
        )
        if not result.success:
            logger.warning("Platt fit did not converge: %s", result.message)
            return None
        return float(result.x[0]), float(result.x[1])
    except Exception:
        logger.exception("Platt fit raised")
        return None


def apply_coefficients(raw_prob: float, a: float, b: float) -> float:
    raw = max(1e-6, min(1.0 - 1e-6, raw_prob))
    return float(expit(a * raw + b))


def fit_and_save(session: Session) -> dict | None:
    """Fit Platt on current settled signals and persist coefficients.

    Returns the persisted dict, or None when not enough data / fit failed.
    """
    pairs = _fetch_training_pairs(session)
    n = len(pairs)
    wins = sum(p[1] for p in pairs)
    losses = n - wins

    if n < MIN_FIT_N:
        logger.info("Platt skip: only %d settled signals (need %d)", n, MIN_FIT_N)
        return None
    if wins == 0 or losses == 0:
        logger.warning("Platt skip: wins=%d losses=%d (need both)", wins, losses)
        return None

    coeffs = _fit_logistic(pairs)
    if coeffs is None:
        return None
    a, b = coeffs

    fitted = {
        "a": a,
        "b": b,
        "n": n,
        "wins": wins,
        "fitted_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        os.makedirs(os.path.dirname(CALIBRATOR_FILE), exist_ok=True)
        tmp = CALIBRATOR_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(fitted, fh)
        os.replace(tmp, CALIBRATOR_FILE)
    except Exception:
        logger.exception("Failed to persist Platt calibrator")
        return None

    # Diagnostics: report raw vs calibrated Brier on the training pairs.
    raw_brier = float(np.mean([(p[0] - p[1]) ** 2 for p in pairs]))
    cal_brier = float(np.mean([(apply_coefficients(p[0], a, b) - p[1]) ** 2 for p in pairs]))
    logger.info(
        "Platt fit: a=%.3f b=%.3f n=%d wins=%d brier_raw=%.4f brier_cal=%.4f. "
        "Map: 0.10->%.3f 0.25->%.3f 0.50->%.3f 0.85->%.3f",
        a, b, n, wins, raw_brier, cal_brier,
        apply_coefficients(0.10, a, b),
        apply_coefficients(0.25, a, b),
        apply_coefficients(0.50, a, b),
        apply_coefficients(0.85, a, b),
    )
    if cal_brier > raw_brier:
        logger.warning(
            "Platt did NOT improve Brier (%.4f -> %.4f). Persisting anyway, "
            "but consider whether the underlying model has predictive signal at this n.",
            raw_brier, cal_brier,
        )
    fitted["brier_raw"] = raw_brier
    fitted["brier_calibrated"] = cal_brier

    global _cached
    _cached = fitted
    return fitted


def get_calibrator() -> dict | None:
    """Lazy-load + cache the persisted Platt coefficients."""
    global _cached
    if _cached is not None:
        return _cached
    if not os.path.exists(CALIBRATOR_FILE):
        return None
    try:
        with open(CALIBRATOR_FILE) as fh:
            _cached = json.load(fh)
        return _cached
    except Exception:
        logger.exception("Failed to load Platt calibrator from %s", CALIBRATOR_FILE)
        return None


def reset_cache() -> None:
    global _cached
    _cached = None


def apply_platt(raw_prob: float) -> float:
    """Apply the Platt scaler to a raw model probability. Pass-through if
    no calibrator has been fitted."""
    cal = get_calibrator()
    if cal is None:
        return raw_prob
    return apply_coefficients(raw_prob, cal["a"], cal["b"])
