"""Baseline tests for ra_core.data_generator: determinism + scenario variety."""
from ra_core.config import DEFAULT_START_INDEX, SCENARIOS, TOTAL_POINTS
from ra_core.data_generator import generate_series


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
