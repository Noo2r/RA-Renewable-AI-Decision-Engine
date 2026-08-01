"""Seed the SQLite DB with synthetic data for every (station, scenario) pair."""
from app import db
from app.config import DEFAULT_SCENARIO, DEFAULT_START_INDEX, SCENARIOS
from ra_core.data_generator import generate_series
from ra_core.stations import DEFAULT_STATION_ID, STATION_IDS


def seed_all(force: bool = False):
    db.init_db()
    with db.get_conn() as conn:
        for station_id in STATION_IDS:
            for scenario in SCENARIOS:
                existing = db.count_readings(conn, station_id, scenario)
                if existing > 0 and not force:
                    continue
                df = generate_series(scenario, station_id=station_id)
                db.clear_station_scenario_readings(conn, station_id, scenario)
                db.insert_readings(conn, df, station_id, scenario)

        existing_state = conn.execute("SELECT 1 FROM sim_state WHERE id = 1").fetchone()
        if existing_state is None or force:
            db.set_sim_state(conn, DEFAULT_SCENARIO, DEFAULT_START_INDEX)


if __name__ == "__main__":
    seed_all(force=True)
    print(f"Seeded RA database with synthetic data for {len(STATION_IDS)} stations x all scenarios "
          f"(default station: {DEFAULT_STATION_ID}).")
