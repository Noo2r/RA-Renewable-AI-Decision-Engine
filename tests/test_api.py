"""Baseline API tests against an isolated (temp-file) SQLite DB, so these
tests never touch the developer's real backend/ra.db.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import db
    from app.seed import seed_all

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test_ra.db"))
    seed_all(force=True)

    from app.main import app
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_scenarios_list(client):
    resp = client.get("/scenarios")
    assert resp.status_code == 200
    assert set(resp.json()["scenarios"]) == {"sunny", "cloudy", "windy", "high_demand"}


def test_state_shape(client):
    resp = client.get("/state")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("scenario", "current_index", "total_points", "reading", "surplus_kw", "generation_kw"):
        assert key in body


def test_scenario_switch_resets_index(client):
    client.post("/tick", json={"steps": 5})
    advanced = client.get("/state").json()["current_index"]

    resp = client.post("/scenario", json={"scenario": "cloudy"})
    assert resp.status_code == 200
    reset_state = client.get("/state").json()
    assert reset_state["scenario"] == "cloudy"
    assert reset_state["current_index"] < advanced


def test_scenario_switch_invalid_returns_400(client):
    resp = client.post("/scenario", json={"scenario": "not_a_real_scenario"})
    assert resp.status_code == 400


def test_tick_advances_index(client):
    before = client.get("/state").json()["current_index"]
    resp = client.post("/tick", json={"steps": 2})
    assert resp.status_code == 200
    assert resp.json()["current_index"] == before + 2


def test_forecast_endpoint(client):
    resp = client.get("/forecast?hours=6")
    assert resp.status_code == 200
    body = resp.json()
    assert "forecast" in body and "history" in body and "model_quality" in body


def test_decision_endpoint(client):
    resp = client.get("/decision")
    assert resp.status_code == 200
    body = resp.json()
    assert "recommended" in body and "ranked_actions" in body
    assert body["recommended"]["action"] in {a["action"] for a in body["ranked_actions"]}


def test_core_flow_state_to_decision_to_log_to_history(client):
    """The main end-to-end flow: read state, get a decision, log it, see it in history."""
    state = client.get("/state").json()
    decision = client.get("/decision").json()
    assert decision["scenario"] == state["scenario"]

    log_resp = client.post("/decision/log")
    assert log_resp.status_code == 200
    logged = log_resp.json()
    assert logged["logged"]["action"] == decision["recommended"]["action"]

    history = client.get("/history").json()
    assert history["scenario"] == state["scenario"]
    assert any(d["id"] == logged["id"] for d in history["decisions"])


def test_repeated_logging_does_not_crash(client):
    for _ in range(3):
        resp = client.post("/decision/log")
        assert resp.status_code == 200
    history = client.get("/history?limit=10").json()
    assert len(history["decisions"]) == 3


def test_decision_log_preserves_required_fields(client):
    log_resp = client.post("/decision/log").json()
    logged = log_resp["logged"]
    required = {"action", "expected_kwh", "expected_value_egp", "co2_avoided_kg", "explanation", "score", "timestamp"}
    assert required.issubset(logged.keys())


# ---------------------------------------------------------------------------
# Part 1: multi-station API tests
# ---------------------------------------------------------------------------

def test_stations_endpoint_returns_exactly_three(client):
    resp = client.get("/stations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_station_id"] == "hybrid-01"
    assert len(body["stations"]) == 3
    ids = {s["id"] for s in body["stations"]}
    assert ids == {"solar-01", "wind-01", "hybrid-01"}
    for s in body["stations"]:
        assert "data_source" in s and s["data_source"] == "synthetic"


def test_state_without_station_id_uses_hybrid_01(client):
    resp = client.get("/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["station_id"] == "hybrid-01"
    assert body["energy_type"] == "hybrid"


@pytest.mark.parametrize("station_id", ["solar-01", "wind-01", "hybrid-01"])
def test_state_works_for_every_valid_station(client, station_id):
    resp = client.get(f"/state?station_id={station_id}")
    assert resp.status_code == 200
    assert resp.json()["station_id"] == station_id


def test_state_invalid_station_returns_404(client):
    resp = client.get("/state?station_id=not-a-real-station")
    assert resp.status_code == 404


def test_forecast_is_station_aware(client):
    solar = client.get("/forecast?station_id=solar-01&hours=3").json()
    wind = client.get("/forecast?station_id=wind-01&hours=3").json()
    assert solar["station_id"] == "solar-01"
    assert wind["station_id"] == "wind-01"
    assert solar["forecast"][0]["forecast_surplus_kw"] != wind["forecast"][0]["forecast_surplus_kw"]


def test_decision_is_station_aware(client):
    solar = client.get("/decision?station_id=solar-01").json()
    wind = client.get("/decision?station_id=wind-01").json()
    assert solar["station_id"] == "solar-01"
    assert wind["station_id"] == "wind-01"


def test_decision_log_saves_station_id(client):
    resp = client.post("/decision/log?station_id=solar-01")
    assert resp.status_code == 200
    assert resp.json()["station_id"] == "solar-01"


def test_history_filters_by_station_isolation(client):
    """A decision logged for solar-01 must not appear in wind-01's history."""
    client.post("/decision/log?station_id=solar-01")
    client.post("/decision/log?station_id=wind-01")

    solar_history = client.get("/history?station_id=solar-01").json()
    wind_history = client.get("/history?station_id=wind-01").json()

    assert all(d["station_id"] == "solar-01" for d in solar_history["decisions"])
    assert all(d["station_id"] == "wind-01" for d in wind_history["decisions"])
    assert len(solar_history["decisions"]) == 1
    assert len(wind_history["decisions"]) == 1


def test_hybrid_decision_log_preserves_all_existing_fields(client):
    resp = client.post("/decision/log?station_id=hybrid-01")
    logged = resp.json()["logged"]
    required = {"action", "expected_kwh", "expected_value_egp", "co2_avoided_kg", "explanation", "score", "timestamp"}
    assert required.issubset(logged.keys())


# ---------------------------------------------------------------------------
# Part 1: global clock / scenario shared across stations
# ---------------------------------------------------------------------------

def test_tick_advances_all_stations_to_the_same_index_and_timestamp(client):
    client.post("/tick", json={"steps": 3})
    solar = client.get("/state?station_id=solar-01").json()
    wind = client.get("/state?station_id=wind-01").json()
    hybrid = client.get("/state?station_id=hybrid-01").json()

    assert solar["current_index"] == wind["current_index"] == hybrid["current_index"]
    assert solar["reading"]["timestamp"] == wind["reading"]["timestamp"] == hybrid["reading"]["timestamp"]


def test_scenario_change_applies_to_every_station(client):
    client.post("/scenario", json={"scenario": "high_demand"})
    for station_id in ("solar-01", "wind-01", "hybrid-01"):
        body = client.get(f"/state?station_id={station_id}").json()
        assert body["scenario"] == "high_demand"


def test_resetting_same_scenario_reproduces_same_station_sequences(client):
    client.post("/scenario", json={"scenario": "cloudy"})
    client.post("/tick", json={"steps": 6})
    first_pass = {
        sid: client.get(f"/state?station_id={sid}").json()["reading"]
        for sid in ("solar-01", "wind-01", "hybrid-01")
    }

    client.post("/scenario", json={"scenario": "sunny"})  # switch away
    client.post("/scenario", json={"scenario": "cloudy"})  # switch back (resets index)
    client.post("/tick", json={"steps": 6})  # replay the same advance
    second_pass = {
        sid: client.get(f"/state?station_id={sid}").json()["reading"]
        for sid in ("solar-01", "wind-01", "hybrid-01")
    }

    for sid in first_pass:
        assert first_pass[sid]["solar_kw"] == second_pass[sid]["solar_kw"]
        assert first_pass[sid]["demand_kw"] == second_pass[sid]["demand_kw"]


# ---------------------------------------------------------------------------
# Part 1: national summary
# ---------------------------------------------------------------------------

def test_national_summary_totals_equal_sum_of_stations(client):
    resp = client.get("/national/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["station_count"] == 3

    stations = body["stations"]
    assert abs(sum(s["generation_kw"] for s in stations) - body["totals"]["generation_kw"]) < 0.05
    assert abs(sum(s["demand_kw"] for s in stations) - body["totals"]["demand_kw"]) < 0.05
    expected_net = body["totals"]["generation_kw"] - body["totals"]["demand_kw"]
    assert abs(expected_net - body["totals"]["net_balance_kw"]) < 0.05


def test_national_summary_weighted_battery_soc_is_bounded(client):
    body = client.get("/national/summary").json()
    assert 0 <= body["battery"]["weighted_soc_pct"] <= 100
    assert body["battery"]["total_capacity_kwh"] == 35.0 + 35.0 + 50.0  # solar-01 + wind-01 + hybrid-01


# ---------------------------------------------------------------------------
# Part 2: component forecast + confidence API
# ---------------------------------------------------------------------------

def test_forecast_includes_component_fields(client):
    body = client.get("/forecast?hours=6").json()
    p = body["forecast"][0]
    required = {
        "solar_kw", "solar_lower_kw", "solar_upper_kw", "solar_confidence_pct", "solar_method",
        "wind_kw", "wind_lower_kw", "wind_upper_kw", "wind_confidence_pct", "wind_method",
        "generation_kw", "generation_lower_kw", "generation_upper_kw", "generation_confidence_pct",
        "demand_kw", "demand_lower_kw", "demand_upper_kw", "demand_confidence_pct",
        "net_balance_kw", "net_balance_lower_kw", "net_balance_upper_kw", "net_balance_confidence_pct",
        "horizon_hour",
    }
    assert required.issubset(p.keys())


def test_forecast_preserves_existing_fields(client):
    body = client.get("/forecast?hours=6").json()
    p = body["forecast"][0]
    assert {"timestamp", "forecast_surplus_kw", "actual_surplus_kw"}.issubset(p.keys())
    assert set(body.keys()) >= {"interval_minutes", "history", "forecast", "model_quality", "scenario"}


@pytest.mark.parametrize("station_id", ["solar-01", "wind-01", "hybrid-01"])
def test_forecast_works_for_all_stations(client, station_id):
    resp = client.get(f"/forecast?station_id={station_id}&hours=3")
    assert resp.status_code == 200
    assert resp.json()["station_id"] == station_id


def test_forecast_defaults_to_hybrid_01(client):
    body = client.get("/forecast?hours=1").json()
    assert body["station_id"] == "hybrid-01"


def test_forecast_invalid_station_returns_404(client):
    resp = client.get("/forecast?station_id=not-a-station&hours=1")
    assert resp.status_code == 404


@pytest.mark.parametrize("hours", [0, -1, 7, 100])
def test_forecast_invalid_horizon_is_rejected(client, hours):
    resp = client.get(f"/forecast?hours={hours}")
    assert resp.status_code == 422


def test_forecast_valid_horizons_1_through_6_all_work(client):
    for hours in range(1, 7):
        resp = client.get(f"/forecast?hours={hours}")
        assert resp.status_code == 200


def test_model_quality_contains_component_metrics_and_methods(client):
    mq = client.get("/forecast?hours=6").json()["model_quality"]
    required = {
        "solar_mae_kw", "wind_mae_kw", "generation_mae_kw", "demand_mae_kw", "net_balance_mae_kw",
        "validation_method", "interval_method", "interval_nominal_coverage_pct",
    }
    assert required.issubset(mq.keys())
    assert mq["validation_method"] == "chronological_holdout"
    assert mq["interval_method"] == "empirical_residual_quantiles"
    assert mq["interval_nominal_coverage_pct"] == 80


def test_solar_only_station_forecast_has_structural_zero_wind(client):
    body = client.get("/forecast?station_id=solar-01&hours=6").json()
    for p in body["forecast"]:
        assert p["wind_method"] == "structural_zero"
        assert p["wind_kw"] == 0.0
    assert body["model_quality"]["wind_mae_kw"] is None


def test_decision_endpoint_still_works_after_component_forecast_change(client):
    resp = client.get("/decision")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended"]["action"] in {"battery_charge", "water_pumping", "sell_grid", "curtail"}
    actions = {a["action"] for a in body["ranked_actions"]}
    assert actions.issubset({"battery_charge", "water_pumping", "sell_grid", "curtail"})


# ---------------------------------------------------------------------------
# Part 3: surplus/deficit decision engine API
# ---------------------------------------------------------------------------

def test_decision_endpoint_includes_mode_priority_and_before_after(client):
    body = client.get("/decision").json()
    assert body["mode"] in ("surplus", "deficit")
    assert body["priority"] in ("critical", "high", "medium", "normal")
    for key in ("before", "after"):
        assert key in body
        assert "net_balance_kw" in body[key]
        assert "battery_soc_pct" in body[key]
    assert "remaining_deficit_kw" in body
    assert "decision_interval_minutes" in body
    assert body["decision_interval_minutes"] == 60


def test_decision_endpoint_is_station_aware_for_battery_constraints(client):
    # hybrid-01 (50 kWh) and solar-01 (35 kWh) have different battery
    # capacities/rate limits, so the decision must reflect the requested
    # station's own config, not a hardcoded default.
    hybrid = client.get("/decision?station_id=hybrid-01").json()
    solar = client.get("/decision?station_id=solar-01").json()
    assert hybrid["station_id"] == "hybrid-01"
    assert solar["station_id"] == "solar-01"


def test_high_demand_scenario_produces_deficit_mode_with_battery_discharge(client):
    """Deterministic demo scenario check (Step 20): the existing
    high_demand scenario, advanced into the evening, must reach deficit
    mode with battery_discharge/grid_import recommended for hybrid-01 --
    no new scenario is required to demonstrate the deficit path."""
    client.post("/scenario", json={"scenario": "high_demand"})
    client.post("/tick", json={"steps": 28})  # roughly +7h from 10:00 start
    body = client.get("/decision?station_id=hybrid-01").json()
    assert body["mode"] == "deficit"
    assert body["recommended"]["action"] in ("battery_discharge", "grid_import")


def test_decision_log_preserves_deficit_specific_fields(client):
    client.post("/scenario", json={"scenario": "high_demand"})
    client.post("/tick", json={"steps": 28})
    log_resp = client.post("/decision/log?station_id=hybrid-01")
    assert log_resp.status_code == 200
    logged = log_resp.json()["logged"]
    assert "mode" in logged
    assert "priority" in logged


def test_history_returns_new_part3_fields(client):
    client.post("/scenario", json={"scenario": "high_demand"})
    client.post("/tick", json={"steps": 28})
    client.post("/decision/log?station_id=hybrid-01")
    history = client.get("/history?station_id=hybrid-01").json()
    assert len(history["decisions"]) >= 1
    entry = history["decisions"][0]
    for key in ("mode", "priority", "amount_kw", "before_net_balance_kw", "after_net_balance_kw"):
        assert key in entry
