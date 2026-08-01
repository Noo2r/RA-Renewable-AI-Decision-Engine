"""Baseline tests for the Part 1 station registry (ra_core.stations)."""
import pytest

from ra_core.stations import (
    DEFAULT_STATION_ID,
    STATION_IDS,
    UnknownStationError,
    get_station,
    list_stations,
)


def test_exactly_three_stations_registered():
    assert len(STATION_IDS) == 3
    assert len(list_stations()) == 3


def test_station_ids_are_unique():
    assert len(set(STATION_IDS)) == len(STATION_IDS)


def test_hybrid_01_is_default():
    assert DEFAULT_STATION_ID == "hybrid-01"
    assert "hybrid-01" in STATION_IDS


def test_energy_types_are_correct():
    types = {s.id: s.energy_type for s in list_stations()}
    assert types["solar-01"] == "solar"
    assert types["wind-01"] == "wind"
    assert types["hybrid-01"] == "hybrid"


def test_solar_only_station_has_zero_wind_capacity():
    station = get_station("solar-01")
    assert station.solar_capacity_kw > 0
    assert station.wind_capacity_kw == 0


def test_wind_only_station_has_zero_solar_capacity():
    station = get_station("wind-01")
    assert station.wind_capacity_kw > 0
    assert station.solar_capacity_kw == 0


def test_hybrid_station_has_both_capacities():
    station = get_station("hybrid-01")
    assert station.solar_capacity_kw > 0
    assert station.wind_capacity_kw > 0


def test_unknown_station_lookup_fails_clearly():
    with pytest.raises(UnknownStationError) as exc_info:
        get_station("does-not-exist")
    assert "does-not-exist" in str(exc_info.value)


def test_seed_offsets_are_stable_explicit_integers_not_hash():
    # Regression guard: seed offsets must be fixed ints, not derived from
    # Python's hash() (which is randomized per-process for strings).
    for station in list_stations():
        assert isinstance(station.seed_offset, int)

    # hybrid-01 must be offset 0 so the default station reproduces the
    # exact Part 0 baseline (see ra_core/data_generator.py).
    assert get_station("hybrid-01").seed_offset == 0


# ---------------------------------------------------------------------------
# Part 3: battery operating constraints
# ---------------------------------------------------------------------------

def test_every_station_has_valid_battery_constraints():
    for station in list_stations():
        assert 0 <= station.battery_min_soc_pct < station.battery_max_soc_pct <= 100
        assert 0 < station.battery_charge_efficiency <= 1
        assert 0 < station.battery_discharge_efficiency <= 1
        assert station.battery_charge_limit_kw >= 0
        assert station.battery_discharge_limit_kw >= 0


def test_battery_rate_limits_scale_with_capacity():
    for station in list_stations():
        assert station.battery_charge_limit_kw == station.battery_capacity_kwh * 0.5
        assert station.battery_discharge_limit_kw == station.battery_capacity_kwh * 0.5


def test_invalid_battery_soc_bounds_are_rejected():
    from dataclasses import replace

    station = get_station("hybrid-01")
    with pytest.raises(AssertionError):
        replace(station, battery_min_soc_pct=95.0, battery_max_soc_pct=10.0)


def test_invalid_battery_efficiency_is_rejected():
    from dataclasses import replace

    station = get_station("hybrid-01")
    with pytest.raises(AssertionError):
        replace(station, battery_charge_efficiency=0.0)
    with pytest.raises(AssertionError):
        replace(station, battery_discharge_efficiency=1.5)


def test_public_dict_includes_battery_fields():
    station = get_station("hybrid-01")
    d = station.public_dict()
    required = {
        "battery_charge_limit_kw", "battery_discharge_limit_kw",
        "battery_min_soc_pct", "battery_max_soc_pct",
        "battery_charge_efficiency", "battery_discharge_efficiency",
    }
    assert required.issubset(d.keys())
