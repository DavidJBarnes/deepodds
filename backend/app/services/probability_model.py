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


def compute_edge(model_prob: float, yes_ask: float | None, no_ask: float | None) -> float | None:
    """Edge in cents against the ask price (what you'd actually pay).
    Positive = YES is cheap (buy YES).
    Negative = NO is cheap (buy NO), magnitude is the NO edge."""
    fair_yes = model_prob * 100
    fair_no = 100 - fair_yes
    yes_edge = (fair_yes - yes_ask) if yes_ask and yes_ask > 0 else None
    no_edge = (fair_no - no_ask) if no_ask and no_ask > 0 else None
    if yes_edge is not None and no_edge is not None:
        return yes_edge if yes_edge >= no_edge else -no_edge
    if yes_edge is not None:
        return yes_edge
    if no_edge is not None:
        return -no_edge
    return None
