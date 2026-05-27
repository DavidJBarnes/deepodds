import math
import pytest

from app.services.probability_model import (
    FairValueResult,
    compute_edge,
    compute_fair_probability,
    series_to_underlying,
)

HOURS_TO_YEARS = 1 / (365.25 * 24)


class TestComputeFairProbability:
    def test_atm_between_bucket(self):
        prob = compute_fair_probability(
            spot=2130, floor_strike=2120, cap_strike=2139.99,
            strike_type="between", t_years=1 * HOURS_TO_YEARS, sigma=0.40,
        )
        assert 0.30 < prob < 0.90

    def test_far_otm_between_bucket(self):
        prob = compute_fair_probability(
            spot=2130, floor_strike=1400, cap_strike=1419.99,
            strike_type="between", t_years=1 * HOURS_TO_YEARS, sigma=0.40,
        )
        assert prob < 0.001

    def test_greater_strike(self):
        prob = compute_fair_probability(
            spot=2130, floor_strike=2000, cap_strike=None,
            strike_type="greater", t_years=4 * HOURS_TO_YEARS, sigma=0.40,
        )
        assert 0.50 < prob < 1.0

    def test_less_strike(self):
        prob = compute_fair_probability(
            spot=2130, floor_strike=None, cap_strike=2000,
            strike_type="less", t_years=4 * HOURS_TO_YEARS, sigma=0.40,
        )
        assert 0.0 < prob < 0.50

    def test_greater_plus_less_sums_near_one(self):
        K = 2130
        kwargs = dict(t_years=4 * HOURS_TO_YEARS, sigma=0.40)
        p_above = compute_fair_probability(spot=2130, floor_strike=K, cap_strike=None, strike_type="greater", **kwargs)
        p_below = compute_fair_probability(spot=2130, floor_strike=None, cap_strike=K, strike_type="less", **kwargs)
        assert abs(p_above + p_below - 1.0) < 0.001

    def test_all_buckets_sum_near_one(self):
        spot = 2133.62
        sigma = 0.387
        T = 1 * HOURS_TO_YEARS
        total = 0.0
        for lo in range(1380, 2840, 20):
            hi = lo + 19.99
            total += compute_fair_probability(spot, lo, hi, "between", T, sigma)
        total += compute_fair_probability(spot, None, 1380, "less", T, sigma)
        total += compute_fair_probability(spot, 2839.99, None, "greater", T, sigma)
        assert abs(total - 1.0) < 0.01

    def test_near_expiry_converges_to_binary(self):
        prob_in = compute_fair_probability(
            spot=2130, floor_strike=2120, cap_strike=2139.99,
            strike_type="between", t_years=1e-12, sigma=0.40,
        )
        assert prob_in == 1.0

        prob_out = compute_fair_probability(
            spot=2200, floor_strike=2120, cap_strike=2139.99,
            strike_type="between", t_years=1e-12, sigma=0.40,
        )
        assert prob_out == 0.0

    def test_higher_vol_spreads_probability(self):
        kwargs = dict(
            spot=2130, floor_strike=1800, cap_strike=1819.99,
            strike_type="between", t_years=24 * HOURS_TO_YEARS,
        )
        prob_low_vol = compute_fair_probability(**kwargs, sigma=0.20)
        prob_high_vol = compute_fair_probability(**kwargs, sigma=0.80)
        assert prob_high_vol > prob_low_vol


class TestComputeEdge:
    def test_positive_edge(self):
        result = compute_edge(
            spot=2130, floor_strike=2120, cap_strike=2139.99,
            strike_type="between", t_years=1 * HOURS_TO_YEARS,
            sigma=0.40, market_price=0.30,
        )
        assert isinstance(result, FairValueResult)
        assert result.edge > 0
        assert result.model_prob > result.market_prob

    def test_negative_edge(self):
        result = compute_edge(
            spot=2130, floor_strike=2120, cap_strike=2139.99,
            strike_type="between", t_years=1 * HOURS_TO_YEARS,
            sigma=0.40, market_price=0.95,
        )
        assert result.edge < 0

    def test_edge_equals_model_minus_market(self):
        result = compute_edge(
            spot=2130, floor_strike=2120, cap_strike=2139.99,
            strike_type="between", t_years=1 * HOURS_TO_YEARS,
            sigma=0.40, market_price=0.50,
        )
        # Edge is now blended: edge = (1-MARKET_WEIGHT) * (model_prob - market_prob)
        # With MARKET_WEIGHT=0.5, edge = 0.5 * (model_prob - market_prob)
        expected = 0.5 * (result.model_prob - result.market_prob)
        assert abs(result.edge - expected) < 1e-10

    def test_result_fields_populated(self):
        result = compute_edge(
            spot=2130, floor_strike=2120, cap_strike=2139.99,
            strike_type="between", t_years=4 * HOURS_TO_YEARS,
            sigma=0.40, market_price=0.30,
        )
        assert result.underlying_price == 2130
        assert result.annualized_vol == 0.40
        assert abs(result.time_to_expiry_hours - 4.0) < 0.01
        assert result.strike_type == "between"
        assert result.floor_strike == 2120
        assert result.cap_strike == 2139.99


class TestSeriesToUnderlying:
    def test_known_series(self):
        assert series_to_underlying("KXBTC") == "BTC"
        assert series_to_underlying("KXETH") == "ETH"

    def test_derives_new_symbols_from_convention(self):
        # Any KX-prefixed series should derive its underlying — no code change
        # needed to support new tickers Kalshi adds.
        assert series_to_underlying("KXXRP") == "XRP"
        assert series_to_underlying("KXSOL") == "SOL"
        assert series_to_underlying("KXDOGE") == "DOGE"
        assert series_to_underlying("KXFOO") == "FOO"

    def test_non_kx_prefix_returns_none(self):
        # Only the KX-crypto convention is supported. Non-crypto series (e.g.
        # presidential election series) should not be treated as crypto.
        assert series_to_underlying("PRES2028") is None
        assert series_to_underlying("INX") is None
        assert series_to_underlying("") is None

    def test_kx_alone_returns_none(self):
        # "KX" with nothing after it should not produce an empty-string symbol.
        assert series_to_underlying("KX") is None

    def test_non_string_returns_none(self):
        assert series_to_underlying(None) is None
        assert series_to_underlying(123) is None
