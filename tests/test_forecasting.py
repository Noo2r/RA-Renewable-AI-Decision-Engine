"""Baseline tests for ra_core.forecasting: the model is real, trained, and
its output has a sane shape."""
from ra_core.config import DEFAULT_START_INDEX, FORECAST_HORIZON_STEPS
from ra_core.data_generator import generate_series
from ra_core.forecasting import forecast_surplus


def _rows(scenario="sunny"):
    return generate_series(scenario).to_dict("records")


def test_forecast_output_shape():
    result = forecast_surplus(_rows(), DEFAULT_START_INDEX)
    assert set(result.keys()) == {"interval_minutes", "history", "forecast", "model_quality"}
    assert 0 < len(result["forecast"]) <= FORECAST_HORIZON_STEPS
    assert len(result["history"]) > 0
    for point in result["forecast"]:
        assert set(point.keys()) == {"timestamp", "forecast_surplus_kw", "actual_surplus_kw"}


def test_model_quality_is_reported_and_nonnegative():
    result = forecast_surplus(_rows(), DEFAULT_START_INDEX)
    mq = result["model_quality"]
    assert mq["generation_mae_kw"] is not None
    assert mq["demand_mae_kw"] is not None
    assert mq["generation_mae_kw"] >= 0
    assert mq["demand_mae_kw"] >= 0


def test_forecast_is_not_a_static_constant_across_scenarios():
    # If the forecast were hardcoded rather than model-driven, every scenario
    # would produce identical first-step predictions. They must differ.
    sunny_first = forecast_surplus(_rows("sunny"), DEFAULT_START_INDEX)["forecast"][0]["forecast_surplus_kw"]
    cloudy_first = forecast_surplus(_rows("cloudy"), DEFAULT_START_INDEX)["forecast"][0]["forecast_surplus_kw"]
    assert sunny_first != cloudy_first


def test_forecast_horizon_shrinks_near_end_of_series():
    rows = _rows()
    last_idx = len(rows) - 1
    result = forecast_surplus(rows, last_idx)
    assert result["forecast"] == []  # nothing left to forecast at the last timestep


def test_holdout_split_is_time_ordered_not_random():
    # No shuffling anywhere in the pipeline: rows are consumed in their
    # original chronological order, so a positional 80/20 iloc split is a
    # genuine time-based holdout (train on the early segment, validate on
    # the later segment), not a random split.
    import inspect
    from ra_core import forecasting
    source = inspect.getsource(forecasting)
    assert "shuffle" not in source
    assert "sample(" not in source
