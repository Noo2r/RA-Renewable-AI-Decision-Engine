"""Tests for the Part 1 station-aware SQLite schema migration.

Builds a throwaway pre-Part-1 schema (no station_id columns) in a temp
file, then verifies app.db.init_db() migrates it safely: existing rows are
assigned to DEFAULT_STATION_ID, no data is lost, and it's idempotent.
Never touches the developer's real backend/ra.db.
"""
import sqlite3

from ra_core.stations import DEFAULT_STATION_ID

OLD_SCHEMA = """
CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario TEXT NOT NULL,
    idx INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    solar_kw REAL NOT NULL,
    wind_kw REAL NOT NULL,
    demand_kw REAL NOT NULL,
    price_egp REAL NOT NULL,
    battery_soc REAL NOT NULL,
    cloud_cover REAL NOT NULL,
    wind_speed REAL NOT NULL,
    UNIQUE(scenario, idx)
);
CREATE TABLE sim_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    scenario TEXT NOT NULL,
    current_index INTEGER NOT NULL
);
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    expected_kwh REAL NOT NULL,
    expected_value_egp REAL NOT NULL,
    co2_avoided_kg REAL NOT NULL,
    explanation TEXT NOT NULL,
    score REAL NOT NULL,
    logged_at TEXT NOT NULL
);
"""


def _make_old_schema_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO readings (scenario, idx, timestamp, solar_kw, wind_kw, demand_kw, "
        "price_egp, battery_soc, cloud_cover, wind_speed) VALUES "
        "('sunny', 136, '2026-07-02T10:00:00', 30.14, 0.0, 12.33, 1.514, 35.45, 0.108, 1.62)"
    )
    conn.execute(
        "INSERT INTO decisions (scenario, timestamp, action, expected_kwh, expected_value_egp, "
        "co2_avoided_kg, explanation, score, logged_at) VALUES "
        "('sunny', '2026-07-02T10:00:00', 'battery_charge', 23.45, 37.57, 10.55, 'test', 40.74, "
        "datetime('now'))"
    )
    conn.commit()
    conn.close()


def test_clean_database_initialization_works(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "fresh.db"))
    db.init_db()  # no pre-existing file at all

    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(readings)").fetchall()]
        assert "station_id" in cols
        cols = [r[1] for r in conn.execute("PRAGMA table_info(decisions)").fetchall()]
        assert "station_id" in cols


def test_existing_rows_migrate_to_default_station(tmp_path, monkeypatch):
    from app import db

    db_path = tmp_path / "old.db"
    _make_old_schema_db(db_path)
    monkeypatch.setattr(db, "DB_PATH", str(db_path))

    db.init_db()  # triggers migration

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    reading = conn.execute("SELECT * FROM readings WHERE scenario='sunny' AND idx=136").fetchone()
    assert reading["station_id"] == DEFAULT_STATION_ID
    assert reading["solar_kw"] == 30.14  # data preserved, not regenerated/lost

    decision = conn.execute("SELECT * FROM decisions WHERE action='battery_charge'").fetchone()
    assert decision["station_id"] == DEFAULT_STATION_ID
    assert decision["expected_value_egp"] == 37.57
    conn.close()


def test_migration_is_idempotent(tmp_path, monkeypatch):
    from app import db

    db_path = tmp_path / "old.db"
    _make_old_schema_db(db_path)
    monkeypatch.setattr(db, "DB_PATH", str(db_path))

    db.init_db()
    db.init_db()  # second call must not error or duplicate/lose rows

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1
    conn.close()


def test_station_histories_remain_isolated_at_db_layer(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "fresh.db"))
    db.init_db()

    decision = dict(timestamp="2026-07-02T10:00:00", action="sell_grid", expected_kwh=1.0,
                     expected_value_egp=2.0, co2_avoided_kg=0.1, explanation="x", score=2.03)
    with db.get_conn() as conn:
        db.insert_decision(conn, "solar-01", "sunny", decision)
        db.insert_decision(conn, "wind-01", "sunny", decision)

        solar_history = db.get_history(conn, "solar-01", "sunny")
        wind_history = db.get_history(conn, "wind-01", "sunny")

    assert len(solar_history) == 1
    assert len(wind_history) == 1
    assert solar_history[0]["station_id"] == "solar-01"
    assert wind_history[0]["station_id"] == "wind-01"
