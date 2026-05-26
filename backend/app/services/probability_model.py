import math
from dataclasses import dataclass

SERIES_TO_SYMBOL = {"KXBTC": "BTC", "KXETH": "ETH"}


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
    model_prob = compute_fair_probability(
        spot, floor_strike, cap_strike, strike_type, t_years, sigma
    )
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
    return SERIES_TO_SYMBOL.get(series_ticker)
