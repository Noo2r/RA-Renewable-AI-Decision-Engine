"""Seed the SQLite DB with synthetic data for every scenario."""
from app import db
from app.config import DEFAULT_SCENARIO, DEFAULT_START_INDEX, SCENARIOS
from ra_core.data_generator import generate_series


def seed_all(force: bool = False):
    db.init_db()
    with db.get_conn() as conn:
        for scenario in SCENARIOS:
            existing = db.count_readings(conn, scenario)
            if existing > 0 and not force:
                continue
            df = generate_series(scenario)
            db.clear_scenario_readings(conn, scenario)
            db.insert_readings(conn, df, scenario)

        current_scenario, _ = db.get_sim_state(conn)
        existing_state = conn.execute("SELECT 1 FROM sim_state WHERE id = 1").fetchone()
        if existing_state is None or force:
            db.set_sim_state(conn, DEFAULT_SCENARIO, DEFAULT_START_INDEX)


if __name__ == "__main__":
    seed_all(force=True)
    print("Seeded RA database with synthetic data for all scenarios.")
