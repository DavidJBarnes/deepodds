import math
from dataclasses import dataclass

SERIES_PREFIX = "KX"

# Weight on realized vol when blending with implied vol.
# VOL_WEIGHT=0.3 means 30% realized, 70% implied — the market's vol
# estimate dominates because market Brier is 2x better than our model.
# The edge comes from vol divergence: when realized > implied, the
# market is pricing lower vol than recent history, creating a buy signal.
VOL_WEIGHT = 0.3

IMPLIED_VOL_MAX = 5.0
IMPLIED_VOL_ITERS = 80


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


@dataclass
class FairValueResult:
    model_prob: float
    market_prob: float
    edge: float
    underlying_price: float
    realized_vol: float
    implied_vol: float
    blended_vol: float
    time_to_expiry_hours: float
    strike_type: str
    floor_strike: float | None
    cap_strike: float | None


def compute_fair_probability(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    sigma: float,
    r: float = 0.0,
) -> float:
    if t_years <= 1e-10 or sigma <= 1e-10:
        if strike_type == "between":
            return 1.0 if floor_strike <= spot <= cap_strike else 0.0
        elif strike_type == "greater":
            return 1.0 if spot > floor_strike else 0.0
        else:
            return 1.0 if spot < cap_strike else 0.0

    sqrt_t = math.sqrt(t_years)
    drift = (r - sigma**2 / 2) * t_years

    def d2(k: float) -> float:
        return (math.log(spot / k) + drift) / (sigma * sqrt_t)

    def prob_below(k: float) -> float:
        return _norm_cdf(-d2(k))

    if strike_type == "between":
        return prob_below(cap_strike) - prob_below(floor_strike)
    elif strike_type == "greater":
        return _norm_cdf(d2(floor_strike))
    else:
        return prob_below(cap_strike)


def _implied_vol(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    target_prob: float,
    lo: float = 0.01,
    hi: float = IMPLIED_VOL_MAX,
) -> float | None:
    """Find sigma such that BS price equals target_prob via binary search.

    Returns None if the target is outside the price range achievable
    with vol in [lo, hi] (meaning the market price is extreme — either
    near-zero or near-certain — and not informative for vol estimation).
    """
    p_lo = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, lo)
    p_hi = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, hi)

    lo_ok = p_lo <= target_prob <= p_hi
    inv = p_hi <= target_prob <= p_lo
    if not (lo_ok or inv):
        return None

    if p_lo > p_hi:
        lo, hi = hi, lo

    for _ in range(IMPLIED_VOL_ITERS):
        mid = (lo + hi) / 2
        p = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, mid)
        if abs(p - target_prob) < 1e-8:
            return mid
        if p < target_prob:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2


def compute_edge(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    sigma: float,
    market_price: float,
) -> FairValueResult:
    def _bad(why: str) -> FairValueResult:
        return FairValueResult(
            model_prob=0.0,
            market_prob=market_price or 0.0,
            edge=-1.0,
            underlying_price=spot or 0.0,
            realized_vol=sigma or 0.0,
            implied_vol=0.0,
            blended_vol=sigma or 0.0,
            time_to_expiry_hours=(t_years or 0.0) * 365.25 * 24,
            strike_type=strike_type or "unknown",
            floor_strike=floor_strike,
            cap_strike=cap_strike,
        )

    if spot is None or sigma is None or t_years is None or market_price is None:
        return _bad("missing inputs")
    if strike_type not in ("between", "greater", "less"):
        return _bad(f"unknown strike_type={strike_type}")
    if strike_type == "between" and (floor_strike is None or cap_strike is None):
        return _bad("between missing strikes")
    if strike_type == "greater" and floor_strike is None:
        return _bad("greater missing floor")
    if strike_type == "less" and cap_strike is None:
        return _bad("less missing cap")

    # Step 1: Back-solve implied vol from the market price.
    # This tells us what vol the market is pricing in.
    implied = _implied_vol(spot, floor_strike, cap_strike, strike_type, t_years, market_price)

    # Step 2: Blend realized and implied vol.
    # When realized >> implied, the market expects lower vol than recent
    # history — options are "cheap" and we should buy.
    blended_vol = sigma
    if implied is not None and implied > 0:
        blended_vol = VOL_WEIGHT * sigma + (1 - VOL_WEIGHT) * implied

    try:
        model_prob = compute_fair_probability(
            spot, floor_strike, cap_strike, strike_type, t_years, blended_vol
        )
    except (ValueError, ZeroDivisionError, TypeError):
        return _bad("math error")

    return FairValueResult(
        model_prob=model_prob,
        market_prob=market_price,
        edge=model_prob - market_price,
        underlying_price=spot,
        realized_vol=sigma,
        implied_vol=implied or 0.0,
        blended_vol=blended_vol,
        time_to_expiry_hours=t_years * 365.25 * 24,
        strike_type=strike_type,
        floor_strike=floor_strike,
        cap_strike=cap_strike,
    )


def series_to_underlying(series_ticker: str) -> str | None:
    if not isinstance(series_ticker, str):
        return None
    if not series_ticker.startswith(SERIES_PREFIX):
        return None
    symbol = series_ticker[len(SERIES_PREFIX):]
    return symbol or None
