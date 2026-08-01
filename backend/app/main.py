from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import db
from app.config import DEFAULT_START_INDEX, SCENARIOS
from app.seed import seed_all
from ra_core.decision_engine import evaluate, status_from_priority, STATUS_LABELS
from ra_core.forecasting import forecast_surplus
from ra_core.stations import DEFAULT_STATION_ID, StationConfig, UnknownStationError, get_station, list_stations

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


def _resolve_station(station_id: str) -> StationConfig:
    try:
        return get_station(station_id)
    except UnknownStationError as e:
        raise HTTPException(404, str(e)) from e


def _current_state(conn, station_id: str):
    scenario, idx = db.get_sim_state(conn)
    reading = db.get_reading_at(conn, station_id, scenario, idx)
    total = db.count_readings(conn, station_id, scenario)
    return scenario, idx, reading, total


def _surplus(reading: dict) -> float:
    return reading["solar_kw"] + reading["wind_kw"] - reading["demand_kw"]


def _station_fields(station: StationConfig) -> dict:
    """Additive station info merged into existing endpoint responses."""
    return {
        "station_id": station.id,
        "station_name": station.name,
        "energy_type": station.energy_type,
    }


def _evaluate_for_station(station: StationConfig, reading: dict, forecast_points: list[dict],
                           future_prices: list[float]) -> dict:
    """evaluate() call site shared by /decision and /decision/log -- passes
    the requested station's full battery configuration (capacity, rate
    limits, min/max SoC, efficiencies) so surplus AND deficit math is
    correct for that specific station, not just the default's."""
    return evaluate(
        reading, forecast_points, future_prices,
        battery_capacity_kwh=station.battery_capacity_kwh,
        battery_charge_limit_kw=station.battery_charge_limit_kw,
        battery_discharge_limit_kw=station.battery_discharge_limit_kw,
        battery_min_soc_pct=station.battery_min_soc_pct,
        battery_max_soc_pct=station.battery_max_soc_pct,
        battery_charge_efficiency=station.battery_charge_efficiency,
        battery_discharge_efficiency=station.battery_discharge_efficiency,
    )


def _log_record(result: dict) -> dict:
    """Flattens the top-level decision metadata (mode, priority, before/
    after, remaining deficit, secondary action, decision interval) onto the
    recommended action dict, for both the /decision/log response and what
    gets persisted to SQLite. Nested before/after dicts are kept nested
    here (the DB layer flattens them into scalar columns itself)."""
    return {
        **result["recommended"],
        "timestamp": result["timestamp"],
        "mode": result["mode"],
        "priority": result["priority"],
        "decision_interval_minutes": result["decision_interval_minutes"],
        "before": result["before"],
        "after": result["after"],
        "remaining_deficit_kw": result["remaining_deficit_kw"],
        "secondary_action": result["secondary_action"],
        "secondary_amount_kw": result["secondary_amount_kw"],
    }


@app.get("/scenarios")
def list_scenarios():
    return {"scenarios": SCENARIOS}


@app.get("/stations")
def get_stations():
    return {
        "default_station_id": DEFAULT_STATION_ID,
        "stations": [s.public_dict() for s in list_stations()],
    }


@app.get("/stations/overview")
def stations_overview():
    """One current operational snapshot per registered station, for the
    Egypt map dashboard (Part 4). Reuses the exact same shared-clock +
    forecast_surplus() + evaluate() call path already used by /state and
    /decision (via _evaluate_for_station) -- this endpoint performs no
    independent calculation of its own. `status`/`status_label` are a
    deterministic relabeling of the decision engine's own `priority`
    (see ra_core.decision_engine.status_from_priority): this is an
    operational "how urgently does this station's current recommendation
    need attention" indicator, NOT equipment health, failure probability,
    anomaly status, or maintenance status.

    All stations share one global scenario and simulated clock (Part 1),
    so every entry here is evaluated at the same scenario/index and
    therefore carries the same timestamp.
    """
    stations = list_stations()
    overview = []
    with db.get_conn() as conn:
        scenario, idx = db.get_sim_state(conn)
        for station in stations:
            reading = db.get_reading_at(conn, station.id, scenario, idx)
            if reading is None:
                raise HTTPException(404, f"No data for station '{station.id}' at current scenario/index")
            all_rows = db.get_readings(conn, station.id, scenario, start_idx=0)
            future_rows = db.get_readings(conn, station.id, scenario, start_idx=idx + 1, end_idx=idx + 12)
            fc = forecast_surplus(all_rows, idx, station_id=station.id)
            future_prices = [r["price_egp"] for r in future_rows]
            result = _evaluate_for_station(station, reading, fc["forecast"], future_prices)
            status = status_from_priority(result["priority"])
            overview.append({
                "station_id": station.id,
                "name": station.name,
                "energy_type": station.energy_type,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "scenario": scenario,
                "current_index": idx,
                "timestamp": reading["timestamp"],
                "generation_kw": round(reading["solar_kw"] + reading["wind_kw"], 2),
                "demand_kw": round(reading["demand_kw"], 2),
                "net_balance_kw": result["net_balance_kw"],
                "battery_soc_pct": round(reading["battery_soc"], 1),
                "mode": result["mode"],
                "priority": result["priority"],
                "recommended_action": result["recommended"]["action"],
                "status": status,
                "status_label": STATUS_LABELS.get(status, "Unknown"),
            })
    return {
        "scenario": scenario,
        "current_index": idx,
        "timestamp": overview[0]["timestamp"] if overview else None,
        "stations": overview,
    }


class ScenarioRequest(BaseModel):
    scenario: str


@app.post("/scenario")
def set_scenario(req: ScenarioRequest):
    """Global for all stations: switches the shared scenario and resets the
    shared simulated clock. Unchanged from Part 0 -- stations don't have
    their own scenario/clock (see ra_core/stations.py + Part 1 report)."""
    if req.scenario not in SCENARIOS:
        raise HTTPException(400, f"Unknown scenario '{req.scenario}'. Options: {SCENARIOS}")
    with db.get_conn() as conn:
        db.set_sim_state(conn, req.scenario, DEFAULT_START_INDEX)
        scenario, idx = db.get_sim_state(conn)
        total = db.count_readings(conn, DEFAULT_STATION_ID, scenario)
    return {"scenario": scenario, "current_index": idx, "total_points": total}


class TickRequest(BaseModel):
    steps: int = 1


@app.post("/tick")
def tick(req: TickRequest):
    """Global for all stations: advances the one shared simulated clock."""
    with db.get_conn() as conn:
        scenario, idx = db.get_sim_state(conn)
        total = db.count_readings(conn, DEFAULT_STATION_ID, scenario)
        max_idx = total - 1
        new_idx = min(idx + max(1, req.steps), max_idx)
        db.set_sim_state(conn, scenario, new_idx)
        reading = db.get_reading_at(conn, DEFAULT_STATION_ID, scenario, new_idx)
    return {"scenario": scenario, "current_index": new_idx, "total_points": total, "reading": reading}


@app.get("/state")
def get_state(station_id: str = DEFAULT_STATION_ID):
    station = _resolve_station(station_id)
    with db.get_conn() as conn:
        scenario, idx, reading, total = _current_state(conn, station.id)
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
        **_station_fields(station),
    }


@app.get("/forecast")
def get_forecast(station_id: str = DEFAULT_STATION_ID, hours: float = Query(default=6.0, ge=1, le=6)):
    """Station-aware component forecast (solar/wind/demand, each with an
    empirical uncertainty interval + model-confidence score), plus the
    original forecast_surplus_kw/actual_surplus_kw fields the decision
    engine and older clients rely on. hours is limited to the project's
    supported 1-6 hour horizon (enforced by FastAPI's Query validation)."""
    station = _resolve_station(station_id)
    with db.get_conn() as conn:
        scenario, idx = db.get_sim_state(conn)
        all_rows = db.get_readings(conn, station.id, scenario, start_idx=0)
    result = forecast_surplus(all_rows, idx, station_id=station.id)
    max_steps = max(1, int(hours * 60 / result["interval_minutes"]))
    result["forecast"] = result["forecast"][:max_steps]
    result["scenario"] = scenario
    result.update(_station_fields(station))
    return result


@app.get("/decision")
def get_decision(station_id: str = DEFAULT_STATION_ID):
    station = _resolve_station(station_id)
    with db.get_conn() as conn:
        scenario, idx, reading, total = _current_state(conn, station.id)
        if reading is None:
            raise HTTPException(404, "No data for current scenario")
        all_rows = db.get_readings(conn, station.id, scenario, start_idx=0)
        future_rows = db.get_readings(conn, station.id, scenario, start_idx=idx + 1, end_idx=idx + 12)
    fc = forecast_surplus(all_rows, idx, station_id=station.id)
    future_prices = [r["price_egp"] for r in future_rows]
    result = _evaluate_for_station(station, reading, fc["forecast"], future_prices)
    result["scenario"] = scenario
    result.update(_station_fields(station))
    return result


@app.post("/decision/log")
def log_decision(station_id: str = DEFAULT_STATION_ID):
    station = _resolve_station(station_id)
    with db.get_conn() as conn:
        scenario, idx, reading, total = _current_state(conn, station.id)
        if reading is None:
            raise HTTPException(404, "No data for current scenario")
        all_rows = db.get_readings(conn, station.id, scenario, start_idx=0)
        future_rows = db.get_readings(conn, station.id, scenario, start_idx=idx + 1, end_idx=idx + 12)
        fc = forecast_surplus(all_rows, idx, station_id=station.id)
        future_prices = [r["price_egp"] for r in future_rows]
        result = _evaluate_for_station(station, reading, fc["forecast"], future_prices)
        recommended = _log_record(result)
        record_id = db.insert_decision(conn, station.id, scenario, recommended)
    return {"id": record_id, "scenario": scenario, "logged": recommended, **_station_fields(station)}


@app.get("/history")
def get_history(station_id: str = DEFAULT_STATION_ID, limit: int = 50):
    station = _resolve_station(station_id)
    with db.get_conn() as conn:
        scenario, _ = db.get_sim_state(conn)
        rows = db.get_history(conn, station.id, scenario, limit=limit)
    return {"scenario": scenario, "decisions": rows, **_station_fields(station)}


@app.get("/national/summary")
def national_summary():
    """Aggregation only across the 3 registered stations at the current
    shared scenario/clock. Does not create a national decision, transfer
    energy between stations, or perform any optimization."""
    stations = list_stations()
    with db.get_conn() as conn:
        scenario, idx = db.get_sim_state(conn)
        per_station = []
        for station in stations:
            reading = db.get_reading_at(conn, station.id, scenario, idx)
            if reading is None:
                raise HTTPException(404, f"No data for station '{station.id}' at current scenario/index")
            per_station.append((station, reading))

    total_solar = sum(r["solar_kw"] for _, r in per_station)
    total_wind = sum(r["wind_kw"] for _, r in per_station)
    total_generation = total_solar + total_wind
    total_demand = sum(r["demand_kw"] for _, r in per_station)
    total_battery_capacity = sum(s.battery_capacity_kwh for s, _ in per_station)
    weighted_soc = (
        sum(r["battery_soc"] * s.battery_capacity_kwh for s, r in per_station) / total_battery_capacity
        if total_battery_capacity > 0
        else 0.0
    )

    return {
        "scenario": scenario,
        "current_index": idx,
        "timestamp": per_station[0][1]["timestamp"] if per_station else None,
        "station_count": len(per_station),
        "totals": {
            "solar_kw": round(total_solar, 2),
            "wind_kw": round(total_wind, 2),
            "generation_kw": round(total_generation, 2),
            "demand_kw": round(total_demand, 2),
            "net_balance_kw": round(total_generation - total_demand, 2),
        },
        "battery": {
            "total_capacity_kwh": round(total_battery_capacity, 2),
            "weighted_soc_pct": round(weighted_soc, 1),
        },
        "stations": [
            {
                "station_id": s.id,
                "generation_kw": round(r["solar_kw"] + r["wind_kw"], 2),
                "demand_kw": round(r["demand_kw"], 2),
                "net_balance_kw": round(r["solar_kw"] + r["wind_kw"] - r["demand_kw"], 2),
                "battery_soc": round(r["battery_soc"], 1),
            }
            for s, r in per_station
        ],
    }
