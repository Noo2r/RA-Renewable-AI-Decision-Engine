from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import db
from app.config import DEFAULT_START_INDEX, SCENARIOS
from app.seed import seed_all
from ra_core.decision_engine import evaluate
from ra_core.forecasting import forecast_surplus

app = FastAPI(title="RA - Renewable AI Decision Engine", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    seed_all(force=False)


@app.get("/health")
def health():
    return {"status": "ok"}


def _current_state(conn):
    scenario, idx = db.get_sim_state(conn)
    reading = db.get_reading_at(conn, scenario, idx)
    total = db.count_readings(conn, scenario)
    return scenario, idx, reading, total


def _surplus(reading: dict) -> float:
    return reading["solar_kw"] + reading["wind_kw"] - reading["demand_kw"]


@app.get("/scenarios")
def list_scenarios():
    return {"scenarios": SCENARIOS}


class ScenarioRequest(BaseModel):
    scenario: str


@app.post("/scenario")
def set_scenario(req: ScenarioRequest):
    if req.scenario not in SCENARIOS:
        raise HTTPException(400, f"Unknown scenario '{req.scenario}'. Options: {SCENARIOS}")
    with db.get_conn() as conn:
        db.set_sim_state(conn, req.scenario, DEFAULT_START_INDEX)
        scenario, idx, reading, total = _current_state(conn)
    return {"scenario": scenario, "current_index": idx, "total_points": total}


class TickRequest(BaseModel):
    steps: int = 1


@app.post("/tick")
def tick(req: TickRequest):
    with db.get_conn() as conn:
        scenario, idx = db.get_sim_state(conn)
        total = db.count_readings(conn, scenario)
        max_idx = total - 1
        new_idx = min(idx + max(1, req.steps), max_idx)
        db.set_sim_state(conn, scenario, new_idx)
        reading = db.get_reading_at(conn, scenario, new_idx)
    return {"scenario": scenario, "current_index": new_idx, "total_points": total, "reading": reading}


@app.get("/state")
def get_state():
    with db.get_conn() as conn:
        scenario, idx, reading, total = _current_state(conn)
    if reading is None:
        raise HTTPException(404, "No data for current scenario")
    surplus_kw = _surplus(reading)
    return {
        "scenario": scenario,
        "current_index": idx,
        "total_points": total,
        "at_end": idx >= total - 1,
        "reading": reading,
        "surplus_kw": round(surplus_kw, 2),
        "generation_kw": round(reading["solar_kw"] + reading["wind_kw"], 2),
    }


@app.get("/forecast")
def get_forecast(hours: float = 6.0):
    with db.get_conn() as conn:
        scenario, idx = db.get_sim_state(conn)
        all_rows = db.get_readings(conn, scenario, start_idx=0)
    result = forecast_surplus(all_rows, idx)
    max_steps = max(1, int(hours * 60 / result["interval_minutes"]))
    result["forecast"] = result["forecast"][:max_steps]
    result["scenario"] = scenario
    return result


@app.get("/decision")
def get_decision():
    with db.get_conn() as conn:
        scenario, idx, reading, total = _current_state(conn)
        if reading is None:
            raise HTTPException(404, "No data for current scenario")
        all_rows = db.get_readings(conn, scenario, start_idx=0)
        future_rows = db.get_readings(conn, scenario, start_idx=idx + 1, end_idx=idx + 12)
    fc = forecast_surplus(all_rows, idx)
    future_prices = [r["price_egp"] for r in future_rows]
    result = evaluate(reading, fc["forecast"], future_prices)
    result["scenario"] = scenario
    return result


@app.post("/decision/log")
def log_decision():
    with db.get_conn() as conn:
        scenario, idx, reading, total = _current_state(conn)
        if reading is None:
            raise HTTPException(404, "No data for current scenario")
        all_rows = db.get_readings(conn, scenario, start_idx=0)
        future_rows = db.get_readings(conn, scenario, start_idx=idx + 1, end_idx=idx + 12)
        fc = forecast_surplus(all_rows, idx)
        future_prices = [r["price_egp"] for r in future_rows]
        result = evaluate(reading, fc["forecast"], future_prices)
        recommended = {**result["recommended"], "timestamp": result["timestamp"]}
        record_id = db.insert_decision(conn, scenario, recommended)
    return {"id": record_id, "scenario": scenario, "logged": recommended}


@app.get("/history")
def get_history(limit: int = 50):
    with db.get_conn() as conn:
        scenario, _ = db.get_sim_state(conn)
        rows = db.get_history(conn, scenario, limit=limit)
    return {"scenario": scenario, "decisions": rows}
