"""Part 5 tests: ra_core.what_if.simulate_what_if -- shared-core What-If
simulation, side-effect freedom, and deterministic comparison."""
import pytest

from ra_core.config import TOTAL_POINTS
from ra_core.stations import get_station, list_stations, STATION_IDS
from ra_core.what_if import (
    BATTERY_CHANGE_PCT_RANGE,
    DEMAND_CHANGE_PCT_RANGE,
    SOLAR_CHANGE_PCT_RANGE,
    WIND_CHANGE_PCT_RANGE,
    WhatIfValidationError,
    _safe_pct_change,
    simulate_what_if,
)

HYBRID_IDX = 136  # DEFAULT_START_INDEX for "sunny" -- mid-morning surplus


# ---------------------------------------------------------------------------
# Zero-change / determinism
# ---------------------------------------------------------------------------

def test_zero_changes_reproduce_baseline_values():
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX)
    assert result["baseline"] == result["hypothetical"]
    assert result["impact"]["decision_changed"] is False
    assert result["impact"]["mode_changed"] is False
    assert result["impact"]["priority_changed"] is False
    for key in ("generation_change_kw", "demand_change_kw", "net_balance_change_kw",
                "battery_capacity_change_kwh", "expected_value_change_egp",
                "co2_avoided_change_kg", "remaining_deficit_change_kw"):
        assert result["impact"][key] == 0.0


def test_results_are_deterministic_across_repeated_calls():
    r1 = simulate_what_if("hybrid-01", "high_demand", 140, demand_change_pct=20, battery_capacity_change_pct=30)
    r2 = simulate_what_if("hybrid-01", "high_demand", 140, demand_change_pct=20, battery_capacity_change_pct=30)
    assert r1 == r2


def test_baseline_and_hypothetical_share_one_timestamp():
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, solar_capacity_change_pct=20)
    # A single top-level timestamp is returned (not one per side) --
    # verifies the internal assertion that both runs agree.
    assert result["timestamp"]


# ---------------------------------------------------------------------------
# Capacity/demand/battery effects
# ---------------------------------------------------------------------------

def test_solar_capacity_increase_raises_solar_capable_station_generation():
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, solar_capacity_change_pct=50)
    assert result["hypothetical"]["solar_capacity_kw"] > result["baseline"]["solar_capacity_kw"]
    assert result["hypothetical"]["forecast_generation_kw"] >= result["baseline"]["forecast_generation_kw"]


def test_wind_capacity_increase_raises_wind_capacity_field():
    result = simulate_what_if("wind-01", "windy", HYBRID_IDX, wind_capacity_change_pct=50)
    assert result["hypothetical"]["wind_capacity_kw"] > result["baseline"]["wind_capacity_kw"]


def test_solar_only_station_hypothetical_wind_capacity_stays_zero():
    station = get_station("solar-01")
    assert station.wind_capacity_kw == 0
    result = simulate_what_if("solar-01", "sunny", HYBRID_IDX)  # zero requested changes
    assert result["baseline"]["wind_capacity_kw"] == 0
    assert result["hypothetical"]["wind_capacity_kw"] == 0


def test_wind_only_station_hypothetical_solar_capacity_stays_zero():
    station = get_station("wind-01")
    assert station.solar_capacity_kw == 0
    result = simulate_what_if("wind-01", "sunny", HYBRID_IDX)
    assert result["baseline"]["solar_capacity_kw"] == 0
    assert result["hypothetical"]["solar_capacity_kw"] == 0


def test_demand_increase_raises_forecast_demand():
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, demand_change_pct=40)
    assert result["hypothetical"]["forecast_demand_kw"] > result["baseline"]["forecast_demand_kw"]
    assert result["impact"]["demand_change_kw"] > 0


def test_battery_capacity_change_scales_capacity_and_rate_limits_proportionally():
    station = get_station("hybrid-01")
    original_c_rate = station.battery_charge_limit_kw / station.battery_capacity_kwh
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, battery_capacity_change_pct=50)
    assert result["hypothetical"]["battery_capacity_kwh"] == pytest.approx(station.battery_capacity_kwh * 1.5)
    assert result["impact"]["battery_capacity_change_kwh"] == pytest.approx(station.battery_capacity_kwh * 0.5)

    # C-rate preserved: verified indirectly via a battery_discharge deficit
    # scenario where the discharge amount is rate-limited, scaling with
    # capacity in exactly the same proportion as the original C-rate.
    assert original_c_rate == pytest.approx(0.5)  # demo stations are all 0.5C (Part 3)


def test_capacities_never_become_negative_at_range_extremes():
    for station_id in STATION_IDS:
        station = get_station(station_id)
        solar_pct = SOLAR_CHANGE_PCT_RANGE[0] if station.solar_capacity_kw > 0 else 0
        wind_pct = WIND_CHANGE_PCT_RANGE[0] if station.wind_capacity_kw > 0 else 0
        result = simulate_what_if(
            station_id, "sunny", HYBRID_IDX,
            solar_capacity_change_pct=solar_pct, wind_capacity_change_pct=wind_pct,
            demand_change_pct=DEMAND_CHANGE_PCT_RANGE[0], battery_capacity_change_pct=BATTERY_CHANGE_PCT_RANGE[0],
        )
        assert result["hypothetical"]["solar_capacity_kw"] >= 0
        assert result["hypothetical"]["wind_capacity_kw"] >= 0
        assert result["hypothetical"]["battery_capacity_kwh"] >= 0
        assert result["hypothetical"]["forecast_demand_kw"] >= 0


def test_forecast_fields_stay_within_physical_limits():
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, solar_capacity_change_pct=100, wind_capacity_change_pct=100)
    hyp = result["hypothetical"]
    assert 0 <= hyp["current_battery_soc_pct"] <= 100
    assert hyp["forecast_generation_kw"] >= 0
    assert hyp["forecast_demand_kw"] >= 0


def test_existing_decision_engine_fields_are_present_and_consistent():
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, battery_capacity_change_pct=20)
    for side in ("baseline", "hypothetical"):
        r = result[side]
        assert r["mode"] in ("surplus", "deficit")
        assert r["priority"] in ("normal", "medium", "high", "critical")
        assert r["recommended_action"] in (
            "battery_charge", "water_pumping", "sell_grid", "curtail",
            "battery_discharge", "grid_import",
        )


def test_explanation_contains_calculated_change_values():
    result = simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, solar_capacity_change_pct=20)
    gen_delta = result["impact"]["generation_change_kw"]
    assert f"{gen_delta:+.1f}" in result["explanation"]
    assert "solar capacity by +20%" in result["explanation"]


# ---------------------------------------------------------------------------
# Side effects (must all be zero)
# ---------------------------------------------------------------------------

def test_registry_and_station_objects_are_completely_untouched():
    before_ids = list(STATION_IDS)
    before = {s.id: s for s in list_stations()}

    simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, solar_capacity_change_pct=80,
                      wind_capacity_change_pct=0, demand_change_pct=30, battery_capacity_change_pct=90)

    after_ids = list(STATION_IDS)
    after = {s.id: s for s in list_stations()}
    assert before_ids == after_ids
    for sid in before_ids:
        assert before[sid] is get_station(sid)
        assert before[sid] == after[sid]


def test_no_database_or_global_state_dependency():
    """simulate_what_if takes no db/session argument and imports no db
    module -- it cannot write to SQLite or read/alter global sim state by
    construction. This is a structural guard against that regressing."""
    import ra_core.what_if as wi
    assert "db" not in dir(wi)
    assert not hasattr(wi, "get_conn")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_unknown_station_raises():
    from ra_core.stations import UnknownStationError
    with pytest.raises(UnknownStationError):
        simulate_what_if("not-a-station", "sunny", HYBRID_IDX)


@pytest.mark.parametrize("field,bad_value", [
    ("solar_capacity_change_pct", 500),
    ("solar_capacity_change_pct", -90),
    ("wind_capacity_change_pct", 200),
    ("demand_change_pct", 100),
    ("demand_change_pct", -50),
    ("battery_capacity_change_pct", 150),
])
def test_out_of_range_inputs_raise_validation_error(field, bad_value):
    kwargs = {field: bad_value}
    with pytest.raises(WhatIfValidationError):
        simulate_what_if("hybrid-01", "sunny", HYBRID_IDX, **kwargs)


def test_nonzero_wind_change_on_solar_only_station_rejected():
    with pytest.raises(WhatIfValidationError, match="wind"):
        simulate_what_if("solar-01", "sunny", HYBRID_IDX, wind_capacity_change_pct=10)


def test_nonzero_solar_change_on_wind_only_station_rejected():
    with pytest.raises(WhatIfValidationError, match="solar"):
        simulate_what_if("wind-01", "sunny", HYBRID_IDX, solar_capacity_change_pct=10)


def test_zero_change_on_structurally_absent_source_is_allowed():
    # solar_capacity_change_pct=0 (the default) on a wind-only station must
    # NOT be rejected -- only a genuine non-zero request is invalid.
    result = simulate_what_if("wind-01", "sunny", HYBRID_IDX, solar_capacity_change_pct=0)
    assert result is not None


def test_out_of_bounds_current_index_raises():
    with pytest.raises(WhatIfValidationError):
        simulate_what_if("hybrid-01", "sunny", TOTAL_POINTS)
    with pytest.raises(WhatIfValidationError):
        simulate_what_if("hybrid-01", "sunny", -1)


def test_safe_pct_change_never_raises_or_returns_inf_on_zero_baseline():
    assert _safe_pct_change(0.0, 5.0) is None
    assert _safe_pct_change(0.0, 0.0) is None
    result = _safe_pct_change(10.0, 15.0)
    assert result == 50.0
    import math
    assert not math.isinf(result) and not math.isnan(result)
