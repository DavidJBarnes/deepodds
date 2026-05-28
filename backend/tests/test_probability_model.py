import pytest
import os
import xgboost as xgb
from app.services.probability_model import (
    series_to_underlying,
    predict_ml_probability,
    compute_edge,
    get_booster,
    reload_booster,
)

HOURS_TO_YEARS = 1 / (365.25 * 24)


class TestMLProbabilityModel:
    def test_series_to_underlying_valid(self):
        assert series_to_underlying("KXBTC") == "BTC"
        assert series_to_underlying("KXETH") == "ETH"
        assert series_to_underlying("KXXRP") == "XRP"

    def test_series_to_underlying_invalid(self):
        assert series_to_underlying("BTC") is None
        assert series_to_underlying("INVALID") is None
        assert series_to_underlying("") is None
        assert series_to_underlying(123) is None

    def test_get_booster(self):
        bst = get_booster()
        # Should return a Booster object (or None if missing, but we saved it locally during training!)
        assert bst is not None
        assert isinstance(bst, xgb.Booster)

    def test_reload_booster(self):
        reload_booster()
        bst = get_booster()
        assert bst is not None

    def test_predict_ml_probability_between_inside(self):
        # Spot is perfectly inside the range
        res = predict_ml_probability(
            spot=75000.0,
            floor_strike=74000.0,
            cap_strike=76000.0,
            strike_type="between",
            t_years=4 * HOURS_TO_YEARS,
            vol=0.30,
            market_price=0.25,
            symbol="BTC"
        )
        assert res.model_prob >= 0.0 and res.model_prob <= 1.0
        assert res.edge == res.model_prob - 0.25
        assert res.underlying_price == 75000.0
        assert res.realized_vol == 0.30

    def test_predict_ml_probability_between_outside(self):
        # Spot is far outside the range
        res = predict_ml_probability(
            spot=75000.0,
            floor_strike=50000.0,
            cap_strike=55000.0,
            strike_type="between",
            t_years=4 * HOURS_TO_YEARS,
            vol=0.30,
            market_price=0.05,
            symbol="BTC"
        )
        # Should predict extremely low probability
        assert res.model_prob < 0.10

    def test_predict_ml_probability_greater(self):
        res = predict_ml_probability(
            spot=75000.0,
            floor_strike=70000.0,
            cap_strike=None,
            strike_type="greater",
            t_years=4 * HOURS_TO_YEARS,
            vol=0.30,
            market_price=0.50,
            symbol="BTC"
        )
        assert res.model_prob >= 0.0 and res.model_prob <= 1.0

    def test_compute_edge_routing(self):
        # Verify compute_edge compatibility wrapper works identically
        res1 = compute_edge(
            spot=75000.0,
            floor_strike=74000.0,
            cap_strike=76000.0,
            strike_type="between",
            t_years=4 * HOURS_TO_YEARS,
            sigma=0.30,
            market_price=0.25,
            drift=0.01,
            symbol="BTC"
        )
        res2 = predict_ml_probability(
            spot=75000.0,
            floor_strike=74000.0,
            cap_strike=76000.0,
            strike_type="between",
            t_years=4 * HOURS_TO_YEARS,
            vol=0.30,
            market_price=0.25,
            drift=0.01,
            symbol="BTC"
        )
        assert res1.model_prob == res2.model_prob
        assert res1.edge == res2.edge
