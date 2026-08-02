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


def test_deficit_mode_ranks_only_battery_discharge_and_grid_import():
    # Part 3: deficit no longer falls back to "curtail" -- it gets its own
    # two actions. BASE's battery_soc=50.0 is well above the default min
    # SoC (10.0), so battery_discharge is feasible and, with the default
    # (unconstrained) battery/rate defaults, fully covers this 13 kW deficit.
    deficit_current = {**BASE, "solar_kw": 2.0, "demand_kw": 15.0}
    result = evaluate(deficit_current, [{"forecast_surplus_kw": -13.0}] * 4, FLAT_PRICES)
    actions = [a["action"] for a in result["ranked_actions"]]
    assert set(actions) == {"battery_discharge", "grid_import"}
    assert result["mode"] == "deficit"
    assert result["recommended"]["action"] == "battery_discharge"
    assert result["remaining_deficit_kw"] == 0.0
    assert result["secondary_action"] is None
    # curtail must not appear at all in deficit mode
    assert "curtail" not in actions


def test_curtail_always_present_as_fallback_when_surplus_exists():
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES)
    actions = [a["action"] for a in result["ranked_actions"]]
    assert "curtail" in actions
    assert actions[-1] == "curtail"  # lowest-value fallback, ranked last when surplus exists


def test_evaluate_without_battery_capacity_arg_still_works():
    """Backward compat: battery_capacity_kwh is optional and defaults to the
    original single-station constant."""
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES)
    assert result["recommended"]["action"] in {"battery_charge", "water_pumping", "sell_grid", "curtail"}


def test_zero_battery_capacity_excludes_charge_in_surplus_mode():
    """Mirrors test_decision_deficit.test_zero_capacity_battery_makes_discharge_infeasible
    but for the surplus/battery_charge side -- previously only the deficit
    side had direct coverage of battery_capacity_kwh == 0."""
    result = evaluate(BASE, FLAT_FORECAST, FLAT_PRICES, battery_capacity_kwh=0.0)
    actions = [a["action"] for a in result["ranked_actions"]]
    assert "battery_charge" not in actions
    assert result["recommended"]["action"] in {"water_pumping", "sell_grid", "curtail"}


def test_zero_demand_does_not_raise_or_produce_nan():
    """demand_kw == 0.0 exercises the max(demand_kw, 1e-6) guard in
    _priority() -- must not raise ZeroDivisionError or return NaN."""
    result = evaluate({**BASE, "demand_kw": 0.0}, FLAT_FORECAST, FLAT_PRICES)
    assert result["priority"] in {"normal", "medium", "high", "critical"}
    assert result["recommended"]["score"] == result["recommended"]["score"]  # not NaN


def test_zero_generation_full_deficit_recommends_grid_import():
    """solar_kw == wind_kw == 0.0: no generation at all, mode must be
    deficit and grid_import must be feasible (battery may or may not be)."""
    current = {**BASE, "solar_kw": 0.0, "wind_kw": 0.0, "demand_kw": 10.0, "battery_soc": 5.0}
    result = evaluate(current, [{"forecast_surplus_kw": -10.0}] * 4, FLAT_PRICES)
    assert result["mode"] == "deficit"
    actions = [a["action"] for a in result["ranked_actions"]]
    assert "grid_import" in actions
    assert result["remaining_deficit_kw"] == 0.0


def test_empty_forecast_points_falls_back_to_instantaneous_surplus():
    """forecast_points=[] happens at dataset end (no future rows left).
    near_term must fall back to [] and avg_surplus_next_hour to the
    instantaneous surplus_kw, not raise IndexError/KeyError."""
    result = evaluate(BASE, [], FLAT_PRICES)
    assert result["avg_surplus_next_hour_kw"] == result["surplus_kw"]
    assert result["recommended"]["action"] in {"battery_charge", "water_pumping", "sell_grid", "curtail"}


def test_smaller_battery_capacity_reduces_charge_headroom():
    # A much smaller battery should cap expected_kwh for battery_charge lower
    # than the default (50 kWh) battery would, given identical inputs.
    low_soc_current = {**BASE, "battery_soc": 80.0}
    big_battery = evaluate(low_soc_current, FLAT_FORECAST, FLAT_PRICES, battery_capacity_kwh=50.0)
    small_battery = evaluate(low_soc_current, FLAT_FORECAST, FLAT_PRICES, battery_capacity_kwh=5.0)

    def charge_kwh(result):
        for a in result["ranked_actions"]:
            if a["action"] == "battery_charge":
                return a["expected_kwh"]
        return None

    small_kwh = charge_kwh(small_battery)
    big_kwh = charge_kwh(big_battery)
    assert small_kwh is not None and big_kwh is not None
    assert small_kwh < big_kwh
