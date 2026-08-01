"""Baseline tests for ra_core.decision_engine: ranking, feasibility gating,
and output validity for each of the four current actions."""
from ra_core.decision_engine import evaluate

BASE = dict(timestamp="2026-07-02T10:00:00", solar_kw=20.0, wind_kw=0.0,
            demand_kw=10.0, price_egp=1.5, battery_soc=50.0)
FLAT_FORECAST = [{"forecast_surplus_kw": 10.0}] * 4
FLAT_PRICES = [1.5] * 8


def test_ranked_actions_sorted_descending_by_score():
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES)
    scores = [a["score"] for a in result["ranked_actions"]]
    assert scores == sorted(scores, reverse=True)


def test_recommended_is_top_ranked_action():
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES)
    assert result["recommended"] == result["ranked_actions"][0]


def test_action_records_have_required_fields():
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES)
    required = {"action", "expected_kwh", "expected_value_egp", "co2_avoided_kg", "score", "explanation"}
    for action in result["ranked_actions"]:
        assert required.issubset(action.keys())
        assert isinstance(action["explanation"], str) and len(action["explanation"]) > 0


def test_battery_charge_considered_when_surplus_and_headroom():
    result = evaluate({**BASE, "battery_soc": 10.0}, FLAT_FORECAST, FLAT_PRICES)
    actions = [a["action"] for a in result["ranked_actions"]]
    assert "battery_charge" in actions


def test_battery_charge_excluded_when_battery_full():
    result = evaluate({**BASE, "battery_soc": 97.0}, FLAT_FORECAST, FLAT_PRICES)
    actions = [a["action"] for a in result["ranked_actions"]]
    assert "battery_charge" not in actions


def test_water_pumping_and_sell_grid_ranked_when_surplus_exists():
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES)
    actions = {a["action"] for a in result["ranked_actions"]}
    assert "water_pumping" in actions
    assert "sell_grid" in actions


def test_high_price_favors_sell_grid_over_water_pumping():
    # water_pumping's per-kWh value is a fixed constant (WATER_PUMP_VALUE_EGP_PER_KWH);
    # once grid price exceeds it, sell_grid must rank above water_pumping.
    high_price_current = {**BASE, "battery_soc": 97.0, "solar_kw": 40.0, "price_egp": 5.0}
    result = evaluate(high_price_current, [{"forecast_surplus_kw": 30.0}] * 4, [1.0] * 8)
    assert result["recommended"]["action"] == "sell_grid"


def test_curtail_is_sole_action_on_deficit():
    deficit_current = {**BASE, "solar_kw": 2.0, "demand_kw": 15.0}
    result = evaluate(deficit_current, [{"forecast_surplus_kw": -13.0}] * 4, FLAT_PRICES)
    actions = [a["action"] for a in result["ranked_actions"]]
    assert actions == ["curtail"]
    assert result["recommended"]["expected_value_egp"] == 0.0


def test_curtail_always_present_as_fallback_when_surplus_exists():
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES)
    actions = [a["action"] for a in result["ranked_actions"]]
    assert "curtail" in actions
    assert actions[-1] == "curtail"  # lowest-value fallback, ranked last when surplus exists
