import math
import pytest

from app.services.probability_model import (
    FREQ_EDGE_WEIGHT,
    SPOT_RANGE_WEIGHT,
    FairValueResult,
    _historical_freq_edge,
    _implied_vol,
    _spot_in_range_edge,
    compute_edge,
    compute_fair_probability,
    series_to_underlying,
)

HOURS_TO_YEARS = 1 / (365.25 * 24)

# Use "less" type (OTM put: spot above cap, betting on a decline).
# This is monotonically increasing in vol, avoiding the GBM vol-drag
# non-monotonicity that affects OTM calls and "between" buckets.
SPOT = 2130.0
CAP = 2100.0   # slightly below spot, so S > K
STRIKE_TYPE = "less"
T_24H = 24 * HOURS_TO_YEARS

# Probability under realized_vol=0.40 for the zero-edge test
# d2 = (ln(S/K)-σ²T/2)/(σ√T) = (0.01418-0.000219)/(0.02094) = 0.6668
# P = N(-0.6668) = 0.2525
FAIR_P_AT_40 = compute_fair_probability(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40)


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


class TestImpliedVol:
    def test_recovers_known_vol(self):
        """If we price with vol X, implied_vol should recover X."""
        target = compute_fair_probability(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40)
        recovered = _implied_vol(SPOT, None, CAP, STRIKE_TYPE, T_24H, target)
        assert recovered is not None
        assert abs(recovered - 0.40) < 0.02

    def test_lower_market_price_yields_lower_implied_vol(self):
        """Cheaper OTM put → lower implied vol."""
        iv_low = _implied_vol(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.15)
        iv_high = _implied_vol(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.35)
        assert iv_low is not None
        assert iv_high is not None
        assert iv_low < iv_high

    def test_higher_strike_needs_higher_vol_for_same_price(self):
        """A deeper OTM put (cap farther below spot) needs more vol for the same price."""
        iv_close = _implied_vol(SPOT, None, 2120, STRIKE_TYPE, T_24H, 0.30)
        iv_far = _implied_vol(SPOT, None, 2050, STRIKE_TYPE, T_24H, 0.30)
        assert iv_close is not None
        assert iv_far is not None
        assert iv_far > iv_close


class TestImpliedVolBetween:
    """_implied_vol with 'between' strike type — monotonic and hump cases."""

    SPOT_IN_RANGE = 2150.0
    FLOOR = 2100.0
    CAP = 2200.0
    T = 24 * HOURS_TO_YEARS

    def test_between_spot_in_range_recovers_vol(self):
        """Spot in [floor,cap] → P decreasing from 1→0. Binary search works."""
        target = compute_fair_probability(self.SPOT_IN_RANGE, self.FLOOR, self.CAP, "between", self.T, 0.40)
        recovered = _implied_vol(self.SPOT_IN_RANGE, self.FLOOR, self.CAP, "between", self.T, target)
        assert recovered is not None
        assert abs(recovered - 0.40) < 0.02

    def test_between_spot_in_range_decreasing(self):
        """Higher market price (closer to 1) → lower implied vol for in-range spot."""
        iv_low_price = _implied_vol(self.SPOT_IN_RANGE, self.FLOOR, self.CAP, "between", self.T, 0.60)
        iv_high_price = _implied_vol(self.SPOT_IN_RANGE, self.FLOOR, self.CAP, "between", self.T, 0.40)
        assert iv_low_price is not None
        assert iv_high_price is not None
        assert iv_high_price > iv_low_price  # lower prob = higher vol for in-range

    def test_between_spot_outside_hump_recovers_vol(self):
        """Spot outside [floor,cap] → hump shape. Golden-section + bisect finds vol."""
        spot_below = 2050.0
        target = compute_fair_probability(spot_below, self.FLOOR, self.CAP, "between", self.T, 0.40)
        recovered = _implied_vol(spot_below, self.FLOOR, self.CAP, "between", self.T, target)
        assert recovered is not None, "Should find vol for hump case"
        assert abs(recovered - 0.40) < 0.03

    def test_between_spot_outside_low_prob(self):
        """Low probability for outside-range spot → low vol on rising edge."""
        spot_above = 2250.0
        iv = _implied_vol(spot_above, self.FLOOR, self.CAP, "between", self.T, 0.05)
        assert iv is not None
        assert iv < 1.0

    def test_between_spot_outside_returns_none_when_unreachable(self):
        """If target_prob > max possible P, return None."""
        spot_far = 2300.0
        iv = _implied_vol(spot_far, self.FLOOR, self.CAP, "between", self.T, 0.99)
        assert iv is None, "99% prob is unreachable for far-OTM between bucket"

    def test_between_spot_near_boundary(self):
        """Spot just outside floor — low vol should give near-zero prob, works via hump."""
        spot_just_below = 2099.0
        iv = _implied_vol(spot_just_below, self.FLOOR, self.CAP, "between", self.T, 0.10)
        assert iv is not None
        assert 0.01 < iv < 5.0


class TestVolDivergence:
    """Edge comes from realized vol diverging from implied vol."""

    def test_positive_edge_when_realized_exceeds_implied(self):
        """Cheap put (mkt_price < fair) → implied < realized → blended > implied → edge > 0."""
        market_price = 0.15  # cheaper than fair value at σ=0.40
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, market_price)
        assert result.implied_vol > 0
        assert result.implied_vol < 0.40
        assert result.blended_vol > result.implied_vol
        assert result.model_prob > result.market_prob
        assert result.edge > 0

    def test_negative_edge_when_realized_below_implied(self):
        """Expensive put → implied > realized → blended < implied → edge < 0."""
        market_price = 0.35  # more expensive than fair value
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, market_price)
        assert result.implied_vol > 0
        assert result.implied_vol > 0.40
        assert result.blended_vol < result.implied_vol
        assert result.model_prob < result.market_prob
        assert result.edge < 0

    def test_edge_near_zero_when_vols_match(self):
        """Market priced at fair value → implied ≈ realized → blended ≈ realized → edge ≈ 0."""
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, FAIR_P_AT_40)
        assert result.implied_vol > 0
        assert abs(result.implied_vol - 0.40) < 0.02
        assert abs(result.blended_vol - 0.40) < 0.02
        assert abs(result.edge) < 0.005


class TestComputeEdge:
    def test_positive_edge(self):
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, 0.15)
        assert isinstance(result, FairValueResult)
        assert result.edge > 0
        assert result.model_prob > result.market_prob

    def test_negative_edge(self):
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, 0.35)
        assert result.edge < 0

    def test_edge_equals_model_minus_market(self):
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, FAIR_P_AT_40)
        assert abs(result.edge - (result.model_prob - result.market_prob)) < 1e-10
        assert result.implied_vol > 0

    def test_result_fields_populated(self):
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, FAIR_P_AT_40)
        assert result.underlying_price == SPOT
        assert result.realized_vol == 0.40
        assert result.implied_vol > 0
        assert result.blended_vol > 0
        assert result.strike_type == "less"
        assert result.cap_strike == CAP

    def test_bad_inputs_return_zero_edge(self):
        result = compute_edge(None, None, CAP, STRIKE_TYPE, T_24H, 0.40, 0.30)
        assert result.edge == -1.0

    def test_unknown_strike_type(self):
        result = compute_edge(SPOT, None, CAP, "unknown", T_24H, 0.40, 0.30)
        assert result.edge == -1.0


class TestSeriesToUnderlying:
    def test_known_series(self):
        assert series_to_underlying("KXBTC") == "BTC"
        assert series_to_underlying("KXETH") == "ETH"

    def test_derives_new_symbols_from_convention(self):
        assert series_to_underlying("KXXRP") == "XRP"
        assert series_to_underlying("KXSOL") == "SOL"
        assert series_to_underlying("KXDOGE") == "DOGE"
        assert series_to_underlying("KXFOO") == "FOO"

    def test_non_kx_prefix_returns_none(self):
        assert series_to_underlying("PRES2028") is None
        assert series_to_underlying("INX") is None
        assert series_to_underlying("") is None

    def test_kx_alone_returns_none(self):
        assert series_to_underlying("KX") is None

    def test_non_string_returns_none(self):
        assert series_to_underlying(None) is None
        assert series_to_underlying(123) is None


class TestHistoricalFreqEdge:
    def test_all_in_range_gives_large_edge(self):
        closes = [2150.0] * 100  # all closes in range
        edge = _historical_freq_edge(closes, 2100.0, 2200.0, 0.50)
        assert edge > 0.40  # freq=1.0 - 0.50 = 0.50

    def test_none_in_range_gives_negative_edge(self):
        closes = [100.0] * 100  # all far below
        edge = _historical_freq_edge(closes, 2100.0, 2200.0, 0.50)
        assert edge < 0  # freq=0 - 0.50 = -0.50

    def test_partial_range(self):
        closes = ([2150.0] * 30) + ([100.0] * 70)
        edge = _historical_freq_edge(closes, 2100.0, 2200.0, 0.50)
        assert edge == pytest.approx(0.30 - 0.50)

    def test_empty_closes_returns_zero(self):
        edge = _historical_freq_edge([], 2100.0, 2200.0, 0.50)
        assert edge == 0.0

    def test_none_strikes_returns_zero(self):
        edge = _historical_freq_edge([2150.0], None, 2200.0, 0.50)
        assert edge == 0.0

    def test_market_price_zero_returns_zero(self):
        edge = _historical_freq_edge([2150.0], 2100.0, 2200.0, 0.0)
        assert edge == 0.0

    def test_price_at_one_returns_zero(self):
        edge = _historical_freq_edge([2150.0], 2100.0, 2200.0, 1.0)
        assert edge == 0.0


class TestSpotInRangeEdge:
    T = 24 * HOURS_TO_YEARS  # 24 hours
    FLOOR = 2100.0
    CAP = 2200.0

    def test_spot_in_range_below_50_gives_positive_edge(self):
        spot = 2150.0  # in range
        edge = _spot_in_range_edge(spot, self.FLOOR, self.CAP, "between", self.T, 0.40, 0.45)
        assert edge > 0

    def test_spot_out_of_range_gives_zero(self):
        spot = 2300.0  # above cap
        edge = _spot_in_range_edge(spot, self.FLOOR, self.CAP, "between", self.T, 0.40, 0.45)
        assert edge == 0.0

    def test_market_price_above_50_gives_zero(self):
        spot = 2150.0
        edge = _spot_in_range_edge(spot, self.FLOOR, self.CAP, "between", self.T, 0.40, 0.55)
        assert edge == 0.0

    def test_not_between_type_gives_zero(self):
        edge = _spot_in_range_edge(2150.0, self.FLOOR, None, "greater", self.T, 0.40, 0.45)
        assert edge == 0.0

    def test_near_expiry_gives_larger_edge(self):
        spot = 2150.0
        edge_24h = _spot_in_range_edge(spot, self.FLOOR, self.CAP, "between", 24 * HOURS_TO_YEARS, 0.40, 0.45)
        edge_1h = _spot_in_range_edge(spot, self.FLOOR, self.CAP, "between", 1 * HOURS_TO_YEARS, 0.40, 0.45)
        assert edge_1h > edge_24h  # closer to expiry = less time to leave range

    def test_high_vol_gives_smaller_edge(self):
        spot = 2150.0
        edge_low_vol = _spot_in_range_edge(spot, self.FLOOR, self.CAP, "between", self.T, 0.20, 0.45)
        edge_high_vol = _spot_in_range_edge(spot, self.FLOOR, self.CAP, "between", self.T, 0.80, 0.45)
        assert edge_low_vol > edge_high_vol

    def test_missing_strikes_returns_zero(self):
        edge = _spot_in_range_edge(2150.0, None, None, "between", self.T, 0.40, 0.45)
        assert edge == 0.0


class TestComputeEdgeNewFields:
    def test_result_has_frequency_edge_field(self):
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, FAIR_P_AT_40)
        assert hasattr(result, "frequency_edge")
        assert result.frequency_edge == 0.0  # vol model doesn't set this

    def test_result_has_spot_range_edge_field(self):
        result = compute_edge(SPOT, None, CAP, STRIKE_TYPE, T_24H, 0.40, FAIR_P_AT_40)
        assert hasattr(result, "spot_range_edge")
        assert result.spot_range_edge == 0.0

    def test_bad_input_result_has_zero_edge_fields(self):
        result = compute_edge(None, None, CAP, STRIKE_TYPE, T_24H, 0.40, 0.30)
        assert result.edge == -1.0
        assert result.frequency_edge == 0.0
        assert result.spot_range_edge == 0.0

    def test_edge_weights_are_reasonable(self):
        assert 0 < FREQ_EDGE_WEIGHT <= 1
        assert 0 < SPOT_RANGE_WEIGHT <= 1
