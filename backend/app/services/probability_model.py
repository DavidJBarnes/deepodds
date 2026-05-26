import math
from dataclasses import dataclass

# Kalshi crypto series follow the convention KX{SYMBOL} (KXBTC, KXETH, KXXRP,
# KXSOL, ...). We derive the underlying instead of hardcoding a whitelist so
# any series the user puts in their config works without a code change.
SERIES_PREFIX = "KX"


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


@dataclass
class FairValueResult:
    model_prob: float
    market_prob: float
    edge: float
    underlying_price: float
    annualized_vol: float
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


def compute_edge(
    spot: float,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
    t_years: float,
    sigma: float,
    market_price: float,
) -> FairValueResult:
    # Defensive: any None/invalid input produces a zero-edge result rather
    # than a crash. The scanner's per-market try/except is the outer safety
    # net; this is the inner one so noisy log entries don't pile up.
    def _bad(why: str) -> FairValueResult:
        return FairValueResult(
            model_prob=0.0,
            market_prob=market_price or 0.0,
            edge=-1.0,  # forces edge < min_edge so no signal fires
            underlying_price=spot or 0.0,
            annualized_vol=sigma or 0.0,
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

    try:
        model_prob = compute_fair_probability(
            spot, floor_strike, cap_strike, strike_type, t_years, sigma
        )
    except (ValueError, ZeroDivisionError, TypeError):
        return _bad("math error")

    return FairValueResult(
        model_prob=model_prob,
        market_prob=market_price,
        edge=model_prob - market_price,
        underlying_price=spot,
        annualized_vol=sigma,
        time_to_expiry_hours=t_years * 365.25 * 24,
        strike_type=strike_type,
        floor_strike=floor_strike,
        cap_strike=cap_strike,
    )


def series_to_underlying(series_ticker: str) -> str | None:
    """Derive the underlying crypto symbol from a Kalshi series ticker.

    Kalshi crypto series follow the convention `KX{SYMBOL}` (e.g. KXBTC → BTC,
    KXETH → ETH, KXXRP → XRP). Returns None for non-conforming tickers.
    """
    if not isinstance(series_ticker, str):
        return None
    if not series_ticker.startswith(SERIES_PREFIX):
        return None
    symbol = series_ticker[len(SERIES_PREFIX):]
    return symbol or None
