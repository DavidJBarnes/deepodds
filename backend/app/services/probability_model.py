import math
from datetime import datetime, timezone

from scipy.stats import norm


def time_to_expiry(expiry: datetime) -> float:
    now = datetime.now(timezone.utc)
    seconds = max((expiry - now).total_seconds(), 1.0)
    return seconds / (365.25 * 86400)


def prob_above(spot: float, strike: float, sigma: float, t_years: float, r: float = 0.0) -> float:
    """P(S_T > strike) using Black-Scholes N(d2). Returns probability 0-1."""
    if t_years <= 0:
        return 1.0 if spot > strike else 0.0
    if sigma <= 0:
        return 1.0 if spot > strike else 0.0

    d2 = (math.log(spot / strike) + (r - 0.5 * sigma**2) * t_years) / (sigma * math.sqrt(t_years))
    return float(norm.cdf(d2))


def prob_below(spot: float, strike: float, sigma: float, t_years: float, r: float = 0.0) -> float:
    return 1.0 - prob_above(spot, strike, sigma, t_years, r)


def prob_between(spot: float, k_low: float, k_high: float, sigma: float, t_years: float, r: float = 0.0) -> float:
    """P(K_low < S_T < K_high)."""
    return prob_above(spot, k_low, sigma, t_years, r) - prob_above(spot, k_high, sigma, t_years, r)


def compute_edge(model_prob: float, market_price_cents: float | None) -> float | None:
    """Edge in cents: how much the market is mispriced.
    Positive = market is cheap (buy opportunity).
    Negative = market is expensive."""
    if market_price_cents is None:
        return None
    fair_cents = model_prob * 100
    return fair_cents - market_price_cents
