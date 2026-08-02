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


# ---------------------------------------------------------------------------
# Part 4: /stations/overview (Egypt map dashboard)
# ---------------------------------------------------------------------------

_OVERVIEW_REQUIRED_FIELDS = {
    "station_id", "name", "energy_type", "latitude", "longitude",
    "scenario", "current_index", "timestamp",
    "generation_kw", "demand_kw", "net_balance_kw", "battery_soc_pct",
    "mode", "priority", "recommended_action", "status", "status_label",
}

_HEALTH_LIKE_FIELDS = {
    "health_score", "health", "anomaly", "anomaly_score", "anomaly_probability",
    "maintenance", "maintenance_due", "failure_probability", "failure_risk",
}


def test_overview_returns_exactly_three_stations(client):
    body = client.get("/stations/overview").json()
    assert len(body["stations"]) == 3
    ids = {s["station_id"] for s in body["stations"]}
    assert ids == {"solar-01", "wind-01", "hybrid-01"}


def test_overview_returns_all_required_map_fields(client):
    body = client.get("/stations/overview").json()
    for s in body["stations"]:
        assert _OVERVIEW_REQUIRED_FIELDS.issubset(s.keys())


def test_overview_does_not_contain_health_anomaly_or_maintenance_fields(client):
    body = client.get("/stations/overview").json()
    for s in body["stations"]:
        assert not (_HEALTH_LIKE_FIELDS & set(s.keys()))


def test_overview_uses_each_stations_configured_lat_lon(client):
    from ra_core.stations import list_stations

    body = client.get("/stations/overview").json()
    by_id = {s["station_id"]: s for s in body["stations"]}
    for station in list_stations():
        assert by_id[station.id]["latitude"] == station.latitude
        assert by_id[station.id]["longitude"] == station.longitude


def test_overview_shares_one_timestamp_across_stations(client):
    body = client.get("/stations/overview").json()
    timestamps = {s["timestamp"] for s in body["stations"]}
    assert len(timestamps) == 1
    assert body["timestamp"] in timestamps


def test_overview_matches_state_values_per_station(client):
    for station_id in ("solar-01", "wind-01", "hybrid-01"):
        state = client.get(f"/state?station_id={station_id}").json()
        overview = client.get("/stations/overview").json()
        entry = next(s for s in overview["stations"] if s["station_id"] == station_id)
        assert entry["generation_kw"] == state["generation_kw"]
        assert entry["demand_kw"] == state["reading"]["demand_kw"]
        assert entry["battery_soc_pct"] == round(state["reading"]["battery_soc"], 1)


def test_overview_matches_decision_mode_priority_and_action(client):
    for station_id in ("solar-01", "wind-01", "hybrid-01"):
        decision = client.get(f"/decision?station_id={station_id}").json()
        overview = client.get("/stations/overview").json()
        entry = next(s for s in overview["stations"] if s["station_id"] == station_id)
        assert entry["mode"] == decision["mode"]
        assert entry["priority"] == decision["priority"]
        assert entry["recommended_action"] == decision["recommended"]["action"]


def test_overview_updates_after_global_tick(client):
    before = client.get("/stations/overview").json()
    client.post("/tick", json={"steps": 4})
    after = client.get("/stations/overview").json()
    assert after["current_index"] == before["current_index"] + 4
    assert after["timestamp"] != before["timestamp"]


def test_overview_updates_after_scenario_change(client):
    # Every scenario resets to the same DEFAULT_START_INDEX/timestamp, so
    # index/timestamp alone don't prove a refresh -- the `scenario` field
    # and the underlying per-station generation numbers (which depend on
    # the scenario's own weather parameters) are the real signal.
    client.post("/scenario", json={"scenario": "high_demand"})
    hd = client.get("/stations/overview").json()
    assert hd["scenario"] == "high_demand"

    client.post("/scenario", json={"scenario": "windy"})
    windy = client.get("/stations/overview").json()
    assert windy["scenario"] == "windy"
    assert all(s["scenario"] == "windy" for s in windy["stations"])

    hd_generation = {s["station_id"]: s["generation_kw"] for s in hd["stations"]}
    windy_generation = {s["station_id"]: s["generation_kw"] for s in windy["stations"]}
    assert hd_generation != windy_generation


def test_overview_is_deterministic_for_a_fixed_scenario_index(client):
    client.post("/scenario", json={"scenario": "sunny"})
    first = client.get("/stations/overview").json()
    second = client.get("/stations/overview").json()
    assert first == second


def test_overview_priority_and_status_are_consistent(client):
    from ra_core.decision_engine import status_from_priority

    body = client.get("/stations/overview").json()
    for s in body["stations"]:
        assert s["status"] == status_from_priority(s["priority"])


# ---------------------------------------------------------------------------
# Part 4: existing behavior regression (must be unaffected by the map work)
# ---------------------------------------------------------------------------

def test_stations_endpoint_unchanged_by_part4(client):
    body = client.get("/stations").json()
    assert body["default_station_id"] == "hybrid-01"
    assert len(body["stations"]) == 3


def test_national_summary_still_aggregation_only(client):
    body = client.get("/national/summary").json()
    assert set(body.keys()) == {"scenario", "current_index", "timestamp", "station_count", "totals", "battery", "stations"}
    assert "status" not in body and "priority" not in body


def test_decision_endpoint_unaffected_by_overview_endpoint(client):
    body = client.get("/decision?station_id=wind-01").json()
    assert "mode" in body and "priority" in body and "recommended" in body


def test_invalid_station_still_404_for_existing_endpoints(client):
    assert client.get("/state?station_id=nope").status_code == 404
    assert client.get("/decision?station_id=nope").status_code == 404
    assert client.get("/forecast?station_id=nope").status_code == 404


def test_forecast_intervals_and_confidence_unchanged(client):
    body = client.get("/forecast?hours=6").json()
    assert body["model_quality"]["validation_method"] == "chronological_holdout"
    assert body["model_quality"]["interval_method"] == "empirical_residual_quantiles"


def test_history_isolation_unaffected_by_part4(client):
    client.post("/decision/log?station_id=solar-01")
    client.post("/decision/log?station_id=wind-01")
    solar_history = client.get("/history?station_id=solar-01").json()
    wind_history = client.get("/history?station_id=wind-01").json()
    assert all(d["station_id"] == "solar-01" for d in solar_history["decisions"])
    assert all(d["station_id"] == "wind-01" for d in wind_history["decisions"])


# ---------------------------------------------------------------------------
# Part 5: POST /simulate (What-If simulator)
# ---------------------------------------------------------------------------

def test_simulate_returns_baseline_hypothetical_impact_and_explanation(client):
    resp = client.post("/simulate", json={
        "station_id": "hybrid-01", "solar_capacity_change_pct": 20, "battery_capacity_change_pct": 50,
    })
    assert resp.status_code == 200
    body = resp.json()
    for key in ("station_id", "scenario", "current_index", "timestamp", "inputs",
                "baseline", "hypothetical", "impact", "explanation"):
        assert key in body
    assert body["station_id"] == "hybrid-01"
    assert isinstance(body["explanation"], str) and len(body["explanation"]) > 0


def test_simulate_defaults_to_current_global_scenario_and_index(client):
    client.post("/scenario", json={"scenario": "high_demand"})
    client.post("/tick", json={"steps": 8})
    state = client.get("/state").json()

    resp = client.post("/simulate", json={"station_id": "hybrid-01"})
    body = resp.json()
    assert body["scenario"] == "high_demand"
    assert body["current_index"] == state["current_index"]


def test_simulate_invalid_station_returns_404(client):
    resp = client.post("/simulate", json={"station_id": "not-a-station"})
    assert resp.status_code == 404


def test_simulate_out_of_range_percent_returns_422(client):
    resp = client.post("/simulate", json={"station_id": "hybrid-01", "solar_capacity_change_pct": 500})
    assert resp.status_code == 422
    assert "solar_capacity_change_pct" in resp.json()["detail"]


def test_simulate_nonzero_wind_on_solar_only_station_returns_422(client):
    resp = client.post("/simulate", json={"station_id": "solar-01", "wind_capacity_change_pct": 10})
    assert resp.status_code == 422
    assert "wind" in resp.json()["detail"].lower()


def test_simulate_nonzero_solar_on_wind_only_station_returns_422(client):
    resp = client.post("/simulate", json={"station_id": "wind-01", "solar_capacity_change_pct": 10})
    assert resp.status_code == 422
    assert "solar" in resp.json()["detail"].lower()


def test_simulate_zero_baseline_percent_returns_null_not_error(client):
    # solar-01 has no wind, so its forecast_generation baseline is entirely
    # solar; at night (or with 0 baseline demand components) percentage
    # deltas would be undefined -- this must never surface as a 500 or a
    # NaN/inf, only a clean 200 with null where appropriate.
    resp = client.post("/simulate", json={"station_id": "wind-01", "wind_capacity_change_pct": 20})
    assert resp.status_code == 200
    body = resp.json()
    import json as _json
    assert "Infinity" not in resp.text and "NaN" not in resp.text
    _json.loads(resp.text)  # would raise if genuinely non-finite floats leaked through


def test_simulate_is_deterministic(client):
    body_a = client.post("/simulate", json={"station_id": "hybrid-01", "demand_change_pct": 20}).json()
    body_b = client.post("/simulate", json={"station_id": "hybrid-01", "demand_change_pct": 20}).json()
    assert body_a == body_b


def test_simulate_has_no_side_effects_on_state_history_or_overview(client):
    before_state = client.get("/state?station_id=hybrid-01").json()
    before_history = client.get("/history?station_id=hybrid-01").json()
    before_overview = client.get("/stations/overview").json()
    before_national = client.get("/national/summary").json()

    for _ in range(3):
        client.post("/simulate", json={
            "station_id": "hybrid-01", "solar_capacity_change_pct": 80,
            "demand_change_pct": 30, "battery_capacity_change_pct": 90,
        })

    after_state = client.get("/state?station_id=hybrid-01").json()
    after_history = client.get("/history?station_id=hybrid-01").json()
    after_overview = client.get("/stations/overview").json()
    after_national = client.get("/national/summary").json()

    assert before_state == after_state
    assert len(before_history["decisions"]) == len(after_history["decisions"])
    assert before_overview == after_overview
    assert before_national == after_national


def test_simulate_does_not_change_stations_endpoint(client):
    before = client.get("/stations").json()
    client.post("/simulate", json={"station_id": "hybrid-01", "battery_capacity_change_pct": 90})
    after = client.get("/stations").json()
    assert before == after


# ---------------------------------------------------------------------------
# Part 5: regression (existing behavior must be unaffected)
# ---------------------------------------------------------------------------

def test_forecast_and_decision_unchanged_by_part5(client):
    fc = client.get("/forecast?hours=6").json()
    assert fc["model_quality"]["validation_method"] == "chronological_holdout"
    decision = client.get("/decision").json()
    assert "mode" in decision and "priority" in decision


def test_map_overview_endpoint_unaffected_by_part5(client):
    body = client.get("/stations/overview").json()
    assert len(body["stations"]) == 3
    for s in body["stations"]:
        assert "status" in s and "status_label" in s


def test_national_summary_still_aggregation_only_after_part5(client):
    body = client.get("/national/summary").json()
    assert set(body.keys()) == {"scenario", "current_index", "timestamp", "station_count", "totals", "battery", "stations"}


# ---------------------------------------------------------------------------
# Part 6: POST /assistant/query (grounded RA Assistant)
# ---------------------------------------------------------------------------

def test_assistant_valid_question_returns_intent_answer_facts_and_grounding(client):
    resp = client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "What is happening now?"})
    assert resp.status_code == 200
    body = resp.json()
    for key in ("intent", "station_id", "answer", "facts", "generated_from", "grounding"):
        assert key in body
    assert body["intent"] == "explain_current_status"
    assert body["station_id"] == "hybrid-01"
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["facts"], list)
    for key in ("scenario", "current_index", "timestamp", "station_id", "what_if_included", "mode"):
        assert key in body["grounding"]
    assert body["grounding"]["mode"] == "offline_deterministic"


def test_assistant_default_station_is_hybrid_01(client):
    resp = client.post("/assistant/query", json={"question": "What is happening now?"})
    assert resp.status_code == 200
    assert resp.json()["station_id"] == "hybrid-01"


def test_assistant_invalid_station_returns_404(client):
    resp = client.post("/assistant/query", json={"station_id": "not-a-station", "question": "What is happening now?"})
    assert resp.status_code == 404


def test_assistant_empty_question_returns_422(client):
    resp = client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "   "})
    assert resp.status_code == 422


def test_assistant_long_question_returns_422(client):
    resp = client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "a" * 600})
    assert resp.status_code == 422


def test_assistant_invalid_what_if_inputs_return_422(client):
    resp = client.post("/assistant/query", json={
        "station_id": "solar-01",
        "question": "What changed in the simulation?",
        "what_if_inputs": {"wind_capacity_change_pct": 10},
    })
    assert resp.status_code == 422


def test_assistant_out_of_scope_request_returns_safe_scoped_guidance(client):
    resp = client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "What is the weather in Cairo?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "out_of_scope"
    assert "RA station status" in body["answer"]


def test_assistant_equipment_control_request_is_refused_safely(client):
    resp = client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "Discharge the battery now."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "out_of_scope"
    assert "does not send control commands to real equipment" in body["answer"]


def test_assistant_api_is_deterministic(client):
    body_a = client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "Why was this decision selected?"}).json()
    body_b = client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "Why was this decision selected?"}).json()
    assert body_a == body_b


def test_assistant_creates_no_history_row(client):
    before = client.get("/history?station_id=hybrid-01").json()
    client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "What is happening now?"})
    client.post("/assistant/query", json={"station_id": "hybrid-01", "question": "Why was this decision selected?"})
    after = client.get("/history?station_id=hybrid-01").json()
    assert len(before["decisions"]) == len(after["decisions"])


def test_assistant_does_not_change_state_scenario_index_overview_or_national_summary(client):
    before_state = client.get("/state?station_id=hybrid-01").json()
    before_overview = client.get("/stations/overview").json()
    before_national = client.get("/national/summary").json()

    for question in ["What is happening now?", "Which station needs attention?", "Why was this decision selected?"]:
        client.post("/assistant/query", json={"station_id": "hybrid-01", "question": question})

    after_state = client.get("/state?station_id=hybrid-01").json()
    after_overview = client.get("/stations/overview").json()
    after_national = client.get("/national/summary").json()

    assert before_state == after_state
    assert before_overview == after_overview
    assert before_national == after_national


def test_assistant_what_if_intent_regenerates_server_side(client):
    resp = client.post("/assistant/query", json={
        "station_id": "hybrid-01",
        "question": "What changed in the simulation?",
        "what_if_inputs": {"solar_capacity_change_pct": 20, "battery_capacity_change_pct": 50},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "explain_what_if"
    assert body["grounding"]["what_if_included"] is True

    sim = client.post("/simulate", json={
        "station_id": "hybrid-01", "solar_capacity_change_pct": 20, "battery_capacity_change_pct": 50,
    }).json()
    assert sim["explanation"] == body["answer"]


def test_assistant_what_if_intent_without_inputs_asks_to_run_simulation(client):
    resp = client.post("/assistant/query", json={
        "station_id": "hybrid-01", "question": "What changed in the simulation?",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["grounding"]["what_if_included"] is False
    assert "Run a What-If simulation first" in body["answer"]


# ---------------------------------------------------------------------------
# Part 6: regression (existing behavior must be unaffected)
# ---------------------------------------------------------------------------

def test_forecast_unchanged_by_part6(client):
    body = client.get("/forecast?hours=6").json()
    assert body["model_quality"]["validation_method"] == "chronological_holdout"


def test_decision_unchanged_by_part6(client):
    body = client.get("/decision").json()
    assert "mode" in body and "priority" in body and "recommended" in body


def test_simulate_endpoint_unchanged_by_part6(client):
    resp = client.post("/simulate", json={"station_id": "hybrid-01", "solar_capacity_change_pct": 10})
    assert resp.status_code == 200
    body = resp.json()
    for key in ("baseline", "hypothetical", "impact", "explanation"):
        assert key in body


def test_map_overview_unchanged_by_part6(client):
    body = client.get("/stations/overview").json()
    assert len(body["stations"]) == 3


def test_history_remains_station_isolated_after_part6(client):
    client.post("/decision/log?station_id=solar-01")
    client.post("/assistant/query", json={"station_id": "wind-01", "question": "What is happening now?"})
    client.post("/decision/log?station_id=wind-01")
    solar_history = client.get("/history?station_id=solar-01").json()
    wind_history = client.get("/history?station_id=wind-01").json()
    assert all(d["station_id"] == "solar-01" for d in solar_history["decisions"])
    assert all(d["station_id"] == "wind-01" for d in wind_history["decisions"])
