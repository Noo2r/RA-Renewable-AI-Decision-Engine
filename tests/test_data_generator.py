"""Baseline tests for ra_core.data_generator: determinism + scenario variety."""
from dataclasses import replace

import numpy as np

from ra_core.config import DEFAULT_START_INDEX, SCENARIOS, TOTAL_POINTS
from ra_core.data_generator import generate_series
from ra_core.stations import DEFAULT_STATION_ID, STATION_IDS, get_station


def test_same_scenario_is_reproducible():
    df1 = generate_series("sunny")
    df2 = generate_series("sunny")
    assert df1.equals(df2)


def test_series_length_matches_config():
    df = generate_series("sunny")
    assert len(df) == TOTAL_POINTS


def test_unknown_scenario_raises():
    import pytest
    with pytest.raises(ValueError):
        generate_series("nonexistent_scenario")


def test_scenarios_differ_meaningfully_at_same_index():
    idx = DEFAULT_START_INDEX
    rows = {s: generate_series(s).iloc[idx] for s in SCENARIOS}

    # cloudy must suppress solar output relative to sunny at the same index
    assert rows["cloudy"]["solar_kw"] < rows["sunny"]["solar_kw"]
    assert rows["cloudy"]["cloud_cover"] > rows["sunny"]["cloud_cover"]

    # windy must produce materially more wind power than sunny
    assert rows["windy"]["wind_kw"] > rows["sunny"]["wind_kw"]

    # high_demand must scale demand (and therefore price) up vs. sunny
    assert rows["high_demand"]["demand_kw"] > rows["sunny"]["demand_kw"]
    assert rows["high_demand"]["price_egp"] > rows["sunny"]["price_egp"]


def test_battery_soc_stays_within_bounds():
    for s in SCENARIOS:
        df = generate_series(s)
        assert (df["battery_soc"] >= 0).all()
        assert (df["battery_soc"] <= 100).all()


# ---------------------------------------------------------------------------
# Part 1: multi-station generator parameterization
# ---------------------------------------------------------------------------

def test_generate_series_without_station_id_still_works():
    """Mandatory backward-compat requirement: generate_series(scenario) with
    no station argument must keep working and use DEFAULT_STATION_ID."""
    df_implicit = generate_series("sunny")
    df_explicit = generate_series("sunny", station_id=DEFAULT_STATION_ID)
    assert df_implicit.equals(df_explicit)


def test_default_station_matches_part0_baseline_exactly():
    r = generate_series("sunny").iloc[136]
    assert abs(r.solar_kw - 30.14) < 0.01
    assert abs(r.wind_kw - 0.0) < 0.01
    assert abs(r.demand_kw - 12.33) < 0.01
    assert abs(r.price_egp - 1.514) < 0.001


def test_same_station_and_scenario_is_reproducible():
    df1 = generate_series("sunny", station_id="solar-01")
    df2 = generate_series("sunny", station_id="solar-01")
    assert df1.equals(df2)


def test_different_stations_produce_different_output():
    hybrid = generate_series("sunny", station_id="hybrid-01").iloc[136]
    solar = generate_series("sunny", station_id="solar-01").iloc[136]
    wind = generate_series("sunny", station_id="wind-01").iloc[136]
    assert hybrid.solar_kw != solar.solar_kw
    assert hybrid.demand_kw != wind.demand_kw


def test_solar_only_station_always_has_zero_wind_generation():
    df = generate_series("windy", station_id="solar-01")  # windy scenario stresses wind hardest
    assert (df["wind_kw"] == 0).all()


def test_wind_only_station_always_has_zero_solar_generation():
    df = generate_series("sunny", station_id="wind-01")  # sunny scenario stresses solar hardest
    assert (df["solar_kw"] == 0).all()


def test_generated_output_never_exceeds_configured_capacity():
    for station_id in STATION_IDS:
        station = get_station(station_id)
        for scenario in SCENARIOS:
            df = generate_series(scenario, station_id=station_id)
            assert (df["solar_kw"] <= station.solar_capacity_kw + 1e-6).all()
            assert (df["wind_kw"] <= station.wind_capacity_kw + 1e-6).all()


def test_scenario_characteristics_preserved_per_station():
    """sunny/cloudy/windy/high_demand must retain their meaning regardless
    of which station is generating -- Part 1 must not redesign scenarios."""
    for station_id in STATION_IDS:
        sunny = generate_series("sunny", station_id=station_id).iloc[136]
        high_demand = generate_series("high_demand", station_id=station_id).iloc[136]
        assert high_demand.demand_kw > sunny.demand_kw


# ---------------------------------------------------------------------------
# Part 7A: numerical safety
# ---------------------------------------------------------------------------

def test_zero_battery_capacity_does_not_crash():
    """A station with no configured battery (battery_capacity_kwh == 0) is
    unreachable via the public What-If API (its range floor is -50%), but
    ra_core.data_generator is also called directly (notebook, future
    callers) with an arbitrary StationConfig. The SoC simulation loop
    divides by battery_capacity_kwh -- previously unconditionally, which
    raised ZeroDivisionError for any zero-capacity station. Regression test
    for that fix: soc must stay a finite, in-range constant instead."""
    station = replace(get_station(DEFAULT_STATION_ID), battery_capacity_kwh=0.0)
    df = generate_series("sunny", station_id=station)
    assert np.isfinite(df["battery_soc"]).all()
    assert (df["battery_soc"] == 0).all()
