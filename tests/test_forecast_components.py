"""Part 2 tests: ra_core.forecasting.forecast_components (separate solar/
wind/demand models, empirical intervals, horizon inflation, and derived
model-confidence scores).
"""
import inspect

from ra_core.config import DEFAULT_START_INDEX
from ra_core.data_generator import generate_series
from ra_core.forecasting import (
    CONFIDENCE_MAX_PCT,
    CONFIDENCE_MIN_PCT,
    forecast_components,
)


def _components(scenario="sunny", station_id="hybrid-01", idx=DEFAULT_START_INDEX):
    rows = generate_series(scenario, station_id=station_id).to_dict("records")
    return forecast_components(rows, idx, station_id=station_id)


# ---------------------------------------------------------------------------
# Component models
# ---------------------------------------------------------------------------

def test_hybrid_station_forecasts_solar_wind_and_demand():
    result = _components(station_id="hybrid-01")
    p = result["forecast"][0]
    assert p["solar_method"] == "model"
    assert p["wind_method"] == "model"
    assert p["solar_kw"] > 0
    assert p["demand_kw"] > 0


def test_solar_station_always_forecasts_zero_wind():
    result = _components(station_id="solar-01")
    for p in result["forecast"]:
        assert p["wind_method"] == "structural_zero"
        assert p["wind_kw"] == 0.0
        assert p["wind_lower_kw"] == 0.0
        assert p["wind_upper_kw"] == 0.0


def test_wind_station_always_forecasts_zero_solar():
    result = _components(station_id="wind-01")
    for p in result["forecast"]:
        assert p["solar_method"] == "structural_zero"
        assert p["solar_kw"] == 0.0
        assert p["solar_lower_kw"] == 0.0
        assert p["solar_upper_kw"] == 0.0


def test_predictions_remain_within_physical_capacity():
    from ra_core.stations import STATION_IDS, get_station
    for station_id in STATION_IDS:
        station = get_station(station_id)
        result = _components(station_id=station_id)
        for p in result["forecast"]:
            assert 0 <= p["solar_kw"] <= station.solar_capacity_kw + 1e-6
            assert 0 <= p["wind_kw"] <= station.wind_capacity_kw + 1e-6


def test_demand_remains_non_negative():
    result = _components(station_id="hybrid-01")
    for p in result["forecast"]:
        assert p["demand_kw"] >= 0
        assert p["demand_lower_kw"] >= 0


def test_generation_equals_solar_plus_wind():
    result = _components(station_id="hybrid-01")
    for p in result["forecast"]:
        assert abs(p["generation_kw"] - (p["solar_kw"] + p["wind_kw"])) < 0.01


def test_net_balance_equals_generation_minus_demand():
    result = _components(station_id="hybrid-01")
    for p in result["forecast"]:
        assert abs(p["net_balance_kw"] - (p["generation_kw"] - p["demand_kw"])) < 0.01


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_same_inputs_produce_identical_forecast():
    a = _components(station_id="hybrid-01")
    b = _components(station_id="hybrid-01")
    assert a["forecast"] == b["forecast"]
    assert a["model_quality"] == b["model_quality"]


def test_switching_station_changes_forecast():
    hybrid = _components(station_id="hybrid-01")["forecast"][0]
    solar = _components(station_id="solar-01")["forecast"][0]
    assert hybrid["solar_kw"] != solar["solar_kw"]


def test_switching_scenario_changes_forecast():
    sunny = _components(scenario="sunny", station_id="hybrid-01")["forecast"][0]
    cloudy = _components(scenario="cloudy", station_id="hybrid-01")["forecast"][0]
    assert sunny["solar_kw"] != cloudy["solar_kw"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_training_and_validation_remain_chronological():
    from ra_core import forecasting
    source = inspect.getsource(forecasting)
    assert "shuffle" not in source
    assert "sample(" not in source
    assert "train_test_split" not in source


def test_metrics_are_finite_when_model_applies():
    result = _components(station_id="hybrid-01")
    mq = result["model_quality"]
    for key in ("solar_mae_kw", "wind_mae_kw", "demand_mae_kw", "generation_mae_kw", "net_balance_mae_kw"):
        assert mq[key] is not None
        assert mq[key] >= 0


def test_structural_zero_sources_do_not_report_fake_metrics():
    result = _components(station_id="solar-01")
    assert result["model_quality"]["wind_mae_kw"] is None
    result = _components(station_id="wind-01")
    assert result["model_quality"]["solar_mae_kw"] is None


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------

def test_lower_bound_never_above_prediction():
    for station_id in ("solar-01", "wind-01", "hybrid-01"):
        result = _components(station_id=station_id)
        for p in result["forecast"]:
            assert p["solar_lower_kw"] <= p["solar_kw"]
            assert p["wind_lower_kw"] <= p["wind_kw"]
            assert p["demand_lower_kw"] <= p["demand_kw"]


def test_upper_bound_never_below_prediction():
    for station_id in ("solar-01", "wind-01", "hybrid-01"):
        result = _components(station_id=station_id)
        for p in result["forecast"]:
            assert p["solar_upper_kw"] >= p["solar_kw"]
            assert p["wind_upper_kw"] >= p["wind_kw"]
            assert p["demand_upper_kw"] >= p["demand_kw"]


def test_net_balance_interval_is_mathematically_consistent():
    result = _components(station_id="hybrid-01")
    for p in result["forecast"]:
        assert p["net_balance_lower_kw"] <= p["net_balance_kw"] <= p["net_balance_upper_kw"]


def test_t6_uncertainty_not_narrower_than_t1():
    result = _components(station_id="hybrid-01")
    forecast = result["forecast"]
    t1, t6 = forecast[3], forecast[-1]  # ~1h ahead vs. ~6h ahead (24 steps @ 15min)
    width_t1 = t1["solar_upper_kw"] - t1["solar_lower_kw"]
    width_t6 = t6["solar_upper_kw"] - t6["solar_lower_kw"]
    assert width_t6 >= width_t1 - 1e-6


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def test_confidence_values_are_deterministic():
    a = _components(station_id="hybrid-01")["forecast"]
    b = _components(station_id="hybrid-01")["forecast"]
    assert [p["solar_confidence_pct"] for p in a] == [p["solar_confidence_pct"] for p in b]


def test_confidence_values_within_documented_range():
    result = _components(station_id="hybrid-01")
    for p in result["forecast"]:
        for key in ("solar_confidence_pct", "wind_confidence_pct", "demand_confidence_pct"):
            v = p[key]
            assert v is None or (CONFIDENCE_MIN_PCT <= v <= CONFIDENCE_MAX_PCT)


def test_later_horizon_confidence_does_not_increase():
    result = _components(station_id="hybrid-01")
    confidences = [p["solar_confidence_pct"] for p in result["forecast"]]
    for earlier, later in zip(confidences, confidences[1:]):
        assert later <= earlier + 1e-6


def test_structural_zero_confidence_is_none_not_fake_value():
    result = _components(station_id="solar-01")
    for p in result["forecast"]:
        assert p["wind_confidence_pct"] is None


def test_generation_confidence_is_conservative_minimum():
    result = _components(station_id="hybrid-01")
    for p in result["forecast"]:
        assert p["generation_confidence_pct"] <= p["solar_confidence_pct"] + 1e-6
        assert p["generation_confidence_pct"] <= p["wind_confidence_pct"] + 1e-6
