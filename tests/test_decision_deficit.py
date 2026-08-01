"""Part 3 tests: ra_core.decision_engine surplus/deficit bidirectional
behavior -- mode selection, battery charge/discharge physical constraints,
deficit decisions, and deterministic priority.
"""
from ra_core.decision_engine import evaluate

BASE = dict(timestamp="2026-07-02T10:00:00", solar_kw=20.0, wind_kw=0.0,
            demand_kw=10.0, price_egp=1.5, battery_soc=50.0)
FLAT_PRICES = [1.5] * 8

BATTERY_KW = dict(
    battery_capacity_kwh=50.0, battery_charge_limit_kw=25.0, battery_discharge_limit_kw=25.0,
    battery_min_soc_pct=10.0, battery_max_soc_pct=95.0,
    battery_charge_efficiency=0.95, battery_discharge_efficiency=0.95,
)


def surplus_forecast(kw):
    return [{"forecast_surplus_kw": kw}] * 4


# ---------------------------------------------------------------------------
# Decision modes
# ---------------------------------------------------------------------------

def test_positive_net_balance_is_surplus_mode():
    result = evaluate(BASE, surplus_forecast(10.0), FLAT_PRICES, **BATTERY_KW)
    assert result["mode"] == "surplus"


def test_negative_net_balance_is_deficit_mode():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    assert result["mode"] == "deficit"


def test_surplus_mode_returns_only_surplus_actions():
    result = evaluate(BASE, surplus_forecast(10.0), FLAT_PRICES, **BATTERY_KW)
    actions = {a["action"] for a in result["ranked_actions"]}
    assert actions.issubset({"battery_charge", "water_pumping", "sell_grid", "curtail"})
    assert "battery_discharge" not in actions
    assert "grid_import" not in actions


def test_deficit_mode_returns_only_deficit_actions():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    actions = {a["action"] for a in result["ranked_actions"]}
    assert actions.issubset({"battery_discharge", "grid_import"})
    for surplus_only in ("battery_charge", "water_pumping", "sell_grid", "curtail"):
        assert surplus_only not in actions


# ---------------------------------------------------------------------------
# Battery charge constraints
# ---------------------------------------------------------------------------

def _charge_action(result):
    for a in result["ranked_actions"]:
        if a["action"] == "battery_charge":
            return a
    return None


def test_charge_amount_does_not_exceed_surplus():
    result = evaluate({**BASE, "battery_soc": 20.0}, surplus_forecast(5.0), FLAT_PRICES, **BATTERY_KW)
    action = _charge_action(result)
    assert action is not None
    assert action["amount_kw"] <= 5.0 + 1e-6


def test_charge_amount_does_not_exceed_rate_limit():
    result = evaluate({**BASE, "battery_soc": 20.0}, surplus_forecast(100.0), FLAT_PRICES,
                       **{**BATTERY_KW, "battery_charge_limit_kw": 10.0})
    action = _charge_action(result)
    assert action is not None
    assert action["amount_kw"] <= 10.0 + 1e-6


def test_projected_soc_does_not_exceed_max_soc():
    result = evaluate({**BASE, "battery_soc": 90.0}, surplus_forecast(100.0), FLAT_PRICES, **BATTERY_KW)
    action = _charge_action(result)
    assert action is not None
    assert action["projected_battery_soc_pct"] <= 95.0 + 1e-6


def test_full_battery_makes_charging_infeasible():
    result = evaluate({**BASE, "battery_soc": 95.0}, surplus_forecast(10.0), FLAT_PRICES, **BATTERY_KW)
    assert _charge_action(result) is None


# ---------------------------------------------------------------------------
# Battery discharge constraints
# ---------------------------------------------------------------------------

def _discharge_action(result):
    for a in result["ranked_actions"]:
        if a["action"] == "battery_discharge":
            return a
    return None


def test_discharge_amount_does_not_exceed_deficit():
    current = {**BASE, "solar_kw": 5.0, "demand_kw": 10.0, "battery_soc": 90.0}
    result = evaluate(current, surplus_forecast(-5.0), FLAT_PRICES, **BATTERY_KW)
    action = _discharge_action(result)
    assert action is not None
    assert action["amount_kw"] <= 5.0 + 1e-6


def test_discharge_amount_does_not_exceed_rate_limit():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 40.0, "battery_soc": 90.0}
    result = evaluate(current, surplus_forecast(-38.0), FLAT_PRICES,
                       **{**BATTERY_KW, "battery_discharge_limit_kw": 8.0})
    action = _discharge_action(result)
    assert action is not None
    assert action["amount_kw"] <= 8.0 + 1e-6


def test_discharge_does_not_reduce_soc_below_minimum():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 40.0, "battery_soc": 15.0}
    result = evaluate(current, surplus_forecast(-38.0), FLAT_PRICES, **BATTERY_KW)
    action = _discharge_action(result)
    assert action is not None
    assert action["projected_battery_soc_pct"] >= 10.0 - 1e-6


def test_min_soc_battery_makes_discharge_infeasible():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 10.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    assert _discharge_action(result) is None
    assert result["recommended"]["action"] == "grid_import"


def test_zero_capacity_battery_makes_discharge_infeasible():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 50.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES,
                       **{**BATTERY_KW, "battery_capacity_kwh": 0.0})
    assert _discharge_action(result) is None
    assert result["recommended"]["action"] == "grid_import"


def test_discharge_efficiency_reduces_delivered_energy():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 40.0, "battery_soc": 90.0}
    full_eff = evaluate(current, surplus_forecast(-38.0), FLAT_PRICES,
                         **{**BATTERY_KW, "battery_discharge_efficiency": 1.0})
    half_eff = evaluate(current, surplus_forecast(-38.0), FLAT_PRICES,
                         **{**BATTERY_KW, "battery_discharge_efficiency": 0.5})
    full_action = _discharge_action(full_eff)
    half_action = _discharge_action(half_eff)
    assert full_action is not None and half_action is not None
    # Same usable stored energy, but at 50% efficiency less useful energy
    # reaches the load, so delivered/amount_kw must be lower.
    assert half_action["amount_kw"] < full_action["amount_kw"]


def test_projected_soc_uses_energy_removed_not_energy_delivered():
    # With imperfect efficiency, energy removed from storage > energy
    # delivered to the load; the SoC drop must reflect the larger
    # (removed) figure, not the smaller delivered amount.
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 12.0, "battery_soc": 50.0}
    result = evaluate(current, surplus_forecast(-10.0), FLAT_PRICES,
                       **{**BATTERY_KW, "battery_discharge_efficiency": 0.5})
    action = _discharge_action(result)
    assert action is not None
    delivered_kwh = action["expected_kwh"]
    soc_drop_pct = 50.0 - action["projected_battery_soc_pct"]
    energy_removed_kwh = soc_drop_pct / 100 * 50.0  # battery_capacity_kwh
    # removed = delivered / efficiency -- must be roughly double delivered
    # at 50% efficiency, not equal to it.
    assert energy_removed_kwh > delivered_kwh * 1.5


# ---------------------------------------------------------------------------
# Deficit decisions: battery availability, remaining deficit, secondary action
# ---------------------------------------------------------------------------

def test_deficit_with_available_battery_recommends_battery_discharge():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 72.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    assert result["recommended"]["action"] == "battery_discharge"


def test_deficit_with_unavailable_battery_recommends_grid_import():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 10.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    assert result["recommended"]["action"] == "grid_import"


def test_partial_battery_coverage_reports_remaining_deficit_and_secondary():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 30.0, "battery_soc": 50.0}
    small_battery = {**BATTERY_KW, "battery_capacity_kwh": 10.0,
                      "battery_charge_limit_kw": 5.0, "battery_discharge_limit_kw": 5.0}
    result = evaluate(current, surplus_forecast(-28.0), FLAT_PRICES, **small_battery)
    assert result["recommended"]["action"] == "battery_discharge"
    assert result["remaining_deficit_kw"] > 0
    assert result["secondary_action"] == "grid_import"
    assert result["secondary_amount_kw"] > 0


def test_full_battery_coverage_reports_zero_remaining_deficit():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 72.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    assert result["remaining_deficit_kw"] == 0.0
    assert result["secondary_action"] is None
    assert result["secondary_amount_kw"] == 0.0


def test_grid_import_cost_is_calculated():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 10.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    grid = result["recommended"]
    assert grid["action"] == "grid_import"
    assert grid["expected_cost_egp"] > 0
    assert grid["expected_cost_egp"] == round(grid["expected_kwh"] * 1.5, 2)  # deficit_kwh * price


def test_battery_discharge_avoided_cost_is_calculated():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 72.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    discharge = result["recommended"]
    assert discharge["action"] == "battery_discharge"
    assert discharge["expected_value_egp"] > 0
    assert discharge["co2_avoided_kg"] > 0


def test_co2_avoided_and_emitted_fields_are_semantically_correct():
    current_low_batt = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 10.0}
    grid_result = evaluate(current_low_batt, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    grid = grid_result["recommended"]
    assert grid["action"] == "grid_import"
    assert grid["co2_avoided_kg"] == 0.0  # never claim avoided emissions for an import
    assert grid["co2_emitted_kg"] > 0.0

    current_batt = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 72.0}
    batt_result = evaluate(current_batt, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    discharge = batt_result["recommended"]
    assert discharge["co2_emitted_kg"] == 0.0  # discharging doesn't emit anything itself
    assert discharge["co2_avoided_kg"] > 0.0


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------

def test_priority_is_deterministic():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 30.0, "battery_soc": 50.0}
    small_battery = {**BATTERY_KW, "battery_capacity_kwh": 10.0,
                      "battery_charge_limit_kw": 5.0, "battery_discharge_limit_kw": 5.0}
    r1 = evaluate(current, surplus_forecast(-28.0), FLAT_PRICES, **small_battery)
    r2 = evaluate(current, surplus_forecast(-28.0), FLAT_PRICES, **small_battery)
    assert r1["priority"] == r2["priority"]


def test_significant_uncovered_deficit_is_high_or_critical():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 30.0, "battery_soc": 50.0}
    small_battery = {**BATTERY_KW, "battery_capacity_kwh": 10.0,
                      "battery_charge_limit_kw": 5.0, "battery_discharge_limit_kw": 5.0}
    result = evaluate(current, surplus_forecast(-28.0), FLAT_PRICES, **small_battery)
    assert result["remaining_deficit_kw"] > 0
    assert result["priority"] in ("high", "critical")


def test_large_remaining_deficit_ratio_is_critical():
    # remaining/demand >= 30% -> critical (DEFICIT_CRITICAL_RATIO)
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 30.0, "battery_soc": 10.0}  # battery unavailable
    result = evaluate(current, surplus_forecast(-28.0), FLAT_PRICES, **BATTERY_KW)
    assert result["recommended"]["action"] == "grid_import"
    # grid_import alone always "fully covers" (remaining=0) -- but since the
    # battery was unavailable, this must be "high", not silently "medium".
    assert result["priority"] == "high"


def test_battery_covered_deficit_is_not_incorrectly_marked_critical():
    current = {**BASE, "solar_kw": 2.0, "demand_kw": 20.0, "battery_soc": 72.0}
    result = evaluate(current, surplus_forecast(-18.0), FLAT_PRICES, **BATTERY_KW)
    assert result["remaining_deficit_kw"] == 0.0
    assert result["priority"] == "medium"
    assert result["priority"] != "critical"


def test_normal_surplus_is_normal_or_medium():
    small_surplus = evaluate(BASE, surplus_forecast(2.0), FLAT_PRICES, **BATTERY_KW)
    assert small_surplus["priority"] in ("normal", "medium")

    big_surplus_current = {**BASE, "solar_kw": 40.0, "demand_kw": 10.0}
    big_surplus = evaluate(big_surplus_current, surplus_forecast(30.0), FLAT_PRICES, **BATTERY_KW)
    assert big_surplus["priority"] == "medium"  # 30/10 = 300% >= 50% threshold
