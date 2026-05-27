import math
from dataclasses import dataclass

SERIES_PREFIX = "KX"

# Weight on realized vol when blending with implied vol.
# VOL_WEIGHT=0.3 means 30% realized, 70% implied — the market's vol
# estimate dominates because market Brier is 2x better than our model.
# The edge comes from vol divergence: when realized > implied, the
# market is pricing lower vol than recent history, creating a buy signal.
VOL_WEIGHT = 0.3

# Approach A: Weight on historical-frequency edge vs vol-based edge.
# 0.5 means 50% empirical frequency, 50% Black-Scholes vol model.
# Historical frequency is the highest-value signal — it directly
# measures past bucket-landing rates without any model assumptions.
FREQ_EDGE_WEIGHT = 0.5

# Approach B: Weight on spot-in-range edge vs vol-based edge.
# 0.3 means 30% in-range boost, 70% vol model. This supplements
# the vol model when spot is already inside the winner's range and
# the market is underpricing the "no move needed" advantage.
SPOT_RANGE_WEIGHT = 0.3

IMPLIED_VOL_MAX = 5.0
IMPLIED_VOL_ITERS = 80


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


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


def _bisect(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    target_prob: float,
    lo: float,
    hi: float,
    increasing: bool,
) -> float:
    """Binary search for vol in [lo, hi] that gives target probability.

    The `increasing` flag selects the comparison direction:
      True  → P increases with σ (standard: if p < target, go up)
      False → P decreases with σ (inverted: if p > target, go up)
    """
    for _ in range(IMPLIED_VOL_ITERS):
        mid = (lo + hi) / 2
        p = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, mid)
        if abs(p - target_prob) < 1e-8:
            return mid
        if increasing:
            if p < target_prob:
                lo = mid
            else:
                hi = mid
        else:
            if p > target_prob:
                lo = mid
            else:
                hi = mid
    return (lo + hi) / 2


def _golden_section_max(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    a: float,
    b: float,
    tol: float = 1e-6,
) -> float:
    """Find sigma in [a,b] that maximises P(sigma) for a unimodal function.

    Uses golden-section search.  Converges in O(log((b-a)/tol)) iterations.
    """
    phi = (math.sqrt(5) - 1) / 2
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    while abs(b - a) > tol:
        fc = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, c)
        fd = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, d)
        if fc < fd:
            a = c
        else:
            b = d
        c = b - phi * (b - a)
        d = a + phi * (b - a)
    return (a + b) / 2


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
    """Find sigma such that BS price equals target_prob.

    Returns None if the target is outside the price range achievable
    with vol in [lo, hi] (meaning the market price is extreme — either
    near-zero or near-certain — and not informative for vol estimation).

    Handles all three strike types:
    - "greater" / "less": P is monotonic in σ → standard binary search.
    - "between" spot IN [floor, cap]: P decreases monotonically from 1→0.
    - "between" spot OUTSIDE [floor, cap]: P is hump-shaped (0 → max → 0).
      Uses golden-section to find σ_max, then binary search on [lo, σ_max]
      for the low-vol (conservative) solution.
    """
    p_lo = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, lo)
    p_hi = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, hi)

    # "greater" and "less" are always monotonic — simple range check
    if strike_type != "between":
        if not (min(p_lo, p_hi) <= target_prob <= max(p_lo, p_hi)):
            return None
        return _bisect(spot, floor_strike, cap_strike, strike_type, t_years, target_prob, lo, hi, p_lo < p_hi)

    # "between" — may be monotonic or hump-shaped
    lo_ok = p_lo <= target_prob <= p_hi
    inv = p_hi <= target_prob <= p_lo
    if lo_ok or inv:
        # Monotonic on this interval — binary search with direction flag.
        # Do NOT swap lo/hi: _bisect uses the increasing flag to handle the
        # comparison direction; swapping would invert the search incorrectly.
        return _bisect(spot, floor_strike, cap_strike, strike_type, t_years, target_prob, lo, hi, p_lo < p_hi)

    # Target is outside the monotonic bracket — check for a hump
    if target_prob > max(p_lo, p_hi):
        sigma_max = _golden_section_max(spot, floor_strike, cap_strike, strike_type, t_years, lo, hi)
        p_max = compute_fair_probability(spot, floor_strike, cap_strike, strike_type, t_years, sigma_max)
        if target_prob > p_max:
            return None
        # Low-vol solution on the rising edge [lo, sigma_max]
        return _bisect(spot, floor_strike, cap_strike, strike_type, t_years, target_prob, lo, sigma_max, increasing=True)

    # target_prob < min(p_lo, p_hi) — should never happen for "between" (min ≈ 0)
    return None


def compute_edge(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    sigma: float,
    market_price: float,
    drift: float = 0.0,
) -> FairValueResult:
    def _bad(why: str) -> FairValueResult:
        return FairValueResult(
            model_prob=0.0,
            market_prob=market_price or 0.0,
            edge=-1.0,
            frequency_edge=0.0,
            spot_range_edge=0.0,
            underlying_price=spot or 0.0,
            realized_vol=sigma or 0.0,
            realized_drift=drift or 0.0,
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
            spot, floor_strike, cap_strike, strike_type, t_years, blended_vol, r=drift
        )
    except (ValueError, ZeroDivisionError, TypeError):
        return _bad("math error")

    return FairValueResult(
        model_prob=model_prob,
        market_prob=market_price,
        edge=model_prob - market_price,
        frequency_edge=0.0,
        spot_range_edge=0.0,
        underlying_price=spot,
        realized_vol=sigma,
        realized_drift=drift,
        implied_vol=implied or 0.0,
        blended_vol=blended_vol,
        time_to_expiry_hours=t_years * 365.25 * 24,
        strike_type=strike_type,
        floor_strike=floor_strike,
        cap_strike=cap_strike,
    )


def _spot_in_range_edge(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    sigma: float,
    market_price: float,
) -> float:
    """Edge from spot already being inside the winner's range.

    When spot is in [floor, cap] for a "between" bucket, the only way to
    lose is for spot to LEAVE the range — a one-sided risk.  The BS model
    prices the probability of entering AND leaving the range symmetrically,
    but for spot-already-there events, the "entering" path is already won:
    no price move is needed.  The market often over-discounts this — a
    contract trading at $0.45 with spot in range and 1 hour left should
    be worth much more because the required move to lose ($50+ on BTC)
    needs high vol or lots of time.

    The boost formula:
        boost = (0.50 - market_price) * exp(-sigma * t_days)
    converges to (0.50-market_price) for immediate expiry and to 0 for
    far-out events or high-vol regimes.
    """
    if strike_type != "between":
        return 0.0
    if floor_strike is None or cap_strike is None:
        return 0.0
    if not (floor_strike <= spot <= cap_strike):
        return 0.0
    if market_price >= 0.50:
        return 0.0

    t_days = t_years * 365.25
    decay = math.exp(-sigma * t_days)
    boost = max(0.0, (0.50 - market_price) * decay)
    return boost


def _historical_freq_edge(
    daily_closes: list[float],
    floor_strike: float | None,
    cap_strike: float | None,
    market_price: float,
) -> float:
    """Empirical edge from historical bucket-landing frequency.

    Counts what fraction of past daily closes fell inside [floor, cap]
    and compares that to the market-implied probability.  Bypasses
    Black-Scholes entirely — pure empirical calibration.

    Returns the gap: historical_freq - market_price.
    """
    if not daily_closes or floor_strike is None or cap_strike is None:
        return 0.0
    if market_price <= 0 or market_price >= 1:
        return 0.0

    in_range = sum(1 for c in daily_closes if floor_strike <= c <= cap_strike)
    freq = in_range / len(daily_closes) if daily_closes else 0.0
    return freq - market_price


def series_to_underlying(series_ticker: str) -> str | None:
    if not isinstance(series_ticker, str):
        return None
    if not series_ticker.startswith(SERIES_PREFIX):
        return None
    symbol = series_ticker[len(SERIES_PREFIX):]
    return symbol or None
