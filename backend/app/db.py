"""SQLite persistence layer. Kept as thin functions over stdlib sqlite3 so it
can be swapped for PostgreSQL/InfluxDB later without touching callers.
"""
import sqlite3
from contextlib import contextmanager

from app.config import DB_PATH, DEFAULT_SCENARIO

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
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

CREATE TABLE IF NOT EXISTS sim_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    scenario TEXT NOT NULL,
    current_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
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


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def clear_scenario_readings(conn, scenario: str):
    conn.execute("DELETE FROM readings WHERE scenario = ?", (scenario,))


def insert_readings(conn, df, scenario: str):
    rows = [
        (scenario, i, r.timestamp, r.solar_kw, r.wind_kw, r.demand_kw,
         r.price_egp, r.battery_soc, r.cloud_cover, r.wind_speed)
        for i, r in enumerate(df.itertuples(index=False))
    ]
    conn.executemany(
        """INSERT INTO readings
           (scenario, idx, timestamp, solar_kw, wind_kw, demand_kw, price_egp,
            battery_soc, cloud_cover, wind_speed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def set_sim_state(conn, scenario: str, current_index: int):
    conn.execute("DELETE FROM sim_state")
    conn.execute(
        "INSERT INTO sim_state (id, scenario, current_index) VALUES (1, ?, ?)",
        (scenario, current_index),
    )


def get_sim_state(conn):
    row = conn.execute("SELECT scenario, current_index FROM sim_state WHERE id = 1").fetchone()
    if row is None:
        return DEFAULT_SCENARIO, 0
    return row["scenario"], row["current_index"]


def get_readings(conn, scenario: str, start_idx: int = 0, end_idx: int | None = None):
    if end_idx is None:
        rows = conn.execute(
            "SELECT * FROM readings WHERE scenario = ? AND idx >= ? ORDER BY idx",
            (scenario, start_idx),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM readings WHERE scenario = ? AND idx >= ? AND idx <= ? ORDER BY idx",
            (scenario, start_idx, end_idx),
        ).fetchall()
    return [dict(r) for r in rows]


def get_reading_at(conn, scenario: str, idx: int):
    row = conn.execute(
        "SELECT * FROM readings WHERE scenario = ? AND idx = ?", (scenario, idx)
    ).fetchone()
    return dict(row) if row else None


def count_readings(conn, scenario: str) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM readings WHERE scenario = ?", (scenario,)).fetchone()
    return row["c"]


def insert_decision(conn, scenario: str, decision: dict):
    conn.execute(
        """INSERT INTO decisions
           (scenario, timestamp, action, expected_kwh, expected_value_egp,
            co2_avoided_kg, explanation, score, logged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            scenario,
            decision["timestamp"],
            decision["action"],
            decision["expected_kwh"],
            decision["expected_value_egp"],
            decision["co2_avoided_kg"],
            decision["explanation"],
            decision["score"],
        ),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def get_history(conn, scenario: str, limit: int = 50):
    rows = conn.execute(
        "SELECT * FROM decisions WHERE scenario = ? ORDER BY id DESC LIMIT ?",
        (scenario, limit),
    ).fetchall()
    return [dict(r) for r in rows]
