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
