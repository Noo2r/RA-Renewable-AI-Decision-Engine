"""SQLite persistence layer. Kept as thin functions over stdlib sqlite3 so it
can be swapped for PostgreSQL/InfluxDB later without touching callers.

Multi-station note: `readings` and `decisions` are both station-aware
(station_id column). `sim_state` intentionally stays a single global row --
all stations share one active scenario and one simulated clock (Part 1).
"""
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from app.config import DB_PATH, DEFAULT_SCENARIO
from ra_core.stations import DEFAULT_STATION_ID

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
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
    UNIQUE(station_id, scenario, idx)
);

CREATE TABLE IF NOT EXISTS sim_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    scenario TEXT NOT NULL,
    current_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    scenario TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    expected_kwh REAL NOT NULL,
    expected_value_egp REAL NOT NULL,
    co2_avoided_kg REAL NOT NULL,
    explanation TEXT NOT NULL,
    score REAL NOT NULL,
    logged_at TEXT NOT NULL,
    mode TEXT,
    priority TEXT,
    amount_kw REAL,
    before_net_balance_kw REAL,
    before_battery_soc_pct REAL,
    after_net_balance_kw REAL,
    after_battery_soc_pct REAL,
    remaining_deficit_kw REAL,
    secondary_action TEXT,
    secondary_amount_kw REAL,
    expected_cost_egp REAL,
    co2_emitted_kg REAL,
    decision_interval_minutes INTEGER
);
"""

# Part 3: surplus/deficit decision-audit columns added to `decisions`.
# Plain ALTER TABLE ADD COLUMN suffices for all of these -- none of them
# participate in a UNIQUE constraint, unlike the Part 1 readings migration.
_DECISION_NEW_COLUMNS = [
    ("mode", "TEXT"),
    ("priority", "TEXT"),
    ("amount_kw", "REAL"),
    ("before_net_balance_kw", "REAL"),
    ("before_battery_soc_pct", "REAL"),
    ("after_net_balance_kw", "REAL"),
    ("after_battery_soc_pct", "REAL"),
    ("remaining_deficit_kw", "REAL"),
    ("secondary_action", "TEXT"),
    ("secondary_amount_kw", "REAL"),
    ("expected_cost_egp", "REAL"),
    ("co2_emitted_kg", "REAL"),
    ("decision_interval_minutes", "INTEGER"),
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _column_exists(conn, table: str, column: str) -> bool:
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def _backup_before_migration():
    """Best-effort file-copy backup, taken only when a real schema migration
    is about to run (not on every normal startup)."""
    import os
    if not os.path.exists(DB_PATH):
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB_PATH}.pre_stations_backup_{ts}"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def _migrate_add_station_support(conn):
    """Idempotent additive migration: adds station_id to `decisions` (simple
    ALTER TABLE) and to `readings` (requires a rebuild because the UNIQUE
    constraint changes from (scenario, idx) to (station_id, scenario, idx),
    which SQLite cannot do with ALTER TABLE alone). Pre-existing rows are
    assigned to DEFAULT_STATION_ID, since that's exactly what they were
    generated as before stations existed. Runs only if the old schema is
    detected; a no-op on a freshly created (already station-aware) database.
    """
    readings_needs_migration = not _column_exists(conn, "readings", "station_id")
    decisions_needs_migration = not _column_exists(conn, "decisions", "station_id")

    if not readings_needs_migration and not decisions_needs_migration:
        return  # already up to date

    _backup_before_migration()

    if decisions_needs_migration:
        conn.execute("ALTER TABLE decisions ADD COLUMN station_id TEXT")
        conn.execute(
            "UPDATE decisions SET station_id = ? WHERE station_id IS NULL",
            (DEFAULT_STATION_ID,),
        )

    if readings_needs_migration:
        conn.execute("ALTER TABLE readings RENAME TO readings_old")
        conn.execute("""
            CREATE TABLE readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
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
                UNIQUE(station_id, scenario, idx)
            )
        """)
        conn.execute(
            """INSERT INTO readings
               (station_id, scenario, idx, timestamp, solar_kw, wind_kw, demand_kw,
                price_egp, battery_soc, cloud_cover, wind_speed)
               SELECT ?, scenario, idx, timestamp, solar_kw, wind_kw, demand_kw,
                      price_egp, battery_soc, cloud_cover, wind_speed
               FROM readings_old""",
            (DEFAULT_STATION_ID,),
        )
        conn.execute("DROP TABLE readings_old")


def _migrate_add_decision_fields(conn):
    """Idempotent additive migration (Part 3): adds the surplus/deficit
    decision-audit columns to `decisions`. Historical (pre-Part-3) rows are
    backfilled with mode='surplus' -- the only mode that existed before
    this migration -- while the other new columns are left NULL for those
    rows, since we genuinely don't have before/after/priority data for
    decisions logged before this feature existed. A no-op on an
    already-migrated or freshly-created (already Part-3-shaped) database.
    """
    missing = [name for name, _ in _DECISION_NEW_COLUMNS if not _column_exists(conn, "decisions", name)]
    if not missing:
        return

    _backup_before_migration()

    for name, sql_type in _DECISION_NEW_COLUMNS:
        if name in missing:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {name} {sql_type}")

    if "mode" in missing:
        conn.execute("UPDATE decisions SET mode = 'surplus' WHERE mode IS NULL")


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_add_station_support(conn)
        _migrate_add_decision_fields(conn)


def clear_station_scenario_readings(conn, station_id: str, scenario: str):
    conn.execute(
        "DELETE FROM readings WHERE station_id = ? AND scenario = ?",
        (station_id, scenario),
    )


def insert_readings(conn, df, station_id: str, scenario: str):
    rows = [
        (station_id, scenario, i, r.timestamp, r.solar_kw, r.wind_kw, r.demand_kw,
         r.price_egp, r.battery_soc, r.cloud_cover, r.wind_speed)
        for i, r in enumerate(df.itertuples(index=False))
    ]
    conn.executemany(
        """INSERT INTO readings
           (station_id, scenario, idx, timestamp, solar_kw, wind_kw, demand_kw, price_egp,
            battery_soc, cloud_cover, wind_speed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def set_sim_state(conn, scenario: str, current_index: int):
    """Global for all stations -- see module docstring."""
    conn.execute("DELETE FROM sim_state")
    conn.execute(
        "INSERT INTO sim_state (id, scenario, current_index) VALUES (1, ?, ?)",
        (scenario, current_index),
    )


def get_sim_state(conn):
    """Global for all stations -- see module docstring."""
    row = conn.execute("SELECT scenario, current_index FROM sim_state WHERE id = 1").fetchone()
    if row is None:
        return DEFAULT_SCENARIO, 0
    return row["scenario"], row["current_index"]


def get_readings(conn, station_id: str, scenario: str, start_idx: int = 0, end_idx: int | None = None):
    if end_idx is None:
        rows = conn.execute(
            "SELECT * FROM readings WHERE station_id = ? AND scenario = ? AND idx >= ? ORDER BY idx",
            (station_id, scenario, start_idx),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM readings
               WHERE station_id = ? AND scenario = ? AND idx >= ? AND idx <= ?
               ORDER BY idx""",
            (station_id, scenario, start_idx, end_idx),
        ).fetchall()
    return [dict(r) for r in rows]


def get_reading_at(conn, station_id: str, scenario: str, idx: int):
    row = conn.execute(
        "SELECT * FROM readings WHERE station_id = ? AND scenario = ? AND idx = ?",
        (station_id, scenario, idx),
    ).fetchone()
    return dict(row) if row else None


def count_readings(conn, station_id: str, scenario: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM readings WHERE station_id = ? AND scenario = ?",
        (station_id, scenario),
    ).fetchone()
    return row["c"]


def insert_decision(conn, station_id: str, scenario: str, decision: dict):
    """decision may be a plain Part 0/1-shaped dict (action/expected_kwh/
    expected_value_egp/co2_avoided_kg/explanation/score/timestamp only) or
    the richer Part 3 shape additionally carrying mode/priority/before/
    after/remaining_deficit_kw/secondary_action/secondary_amount_kw/
    amount_kw/expected_cost_egp/co2_emitted_kg/decision_interval_minutes.
    All new columns are read defensively via .get() so older-shaped callers
    (and old tests) keep working -- they just log NULL/default values for
    the fields they don't have, same convention as the historical-row
    migration backfill.
    """
    before = decision.get("before") or {}
    after = decision.get("after") or {}
    conn.execute(
        """INSERT INTO decisions
           (station_id, scenario, timestamp, action, expected_kwh, expected_value_egp,
            co2_avoided_kg, explanation, score, logged_at,
            mode, priority, amount_kw, before_net_balance_kw, before_battery_soc_pct,
            after_net_balance_kw, after_battery_soc_pct, remaining_deficit_kw,
            secondary_action, secondary_amount_kw, expected_cost_egp, co2_emitted_kg,
            decision_interval_minutes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            station_id,
            scenario,
            decision["timestamp"],
            decision["action"],
            decision["expected_kwh"],
            decision["expected_value_egp"],
            decision["co2_avoided_kg"],
            decision["explanation"],
            decision["score"],
            decision.get("mode", "surplus"),
            decision.get("priority", "normal"),
            decision.get("amount_kw"),
            before.get("net_balance_kw"),
            before.get("battery_soc_pct"),
            after.get("net_balance_kw"),
            after.get("battery_soc_pct"),
            decision.get("remaining_deficit_kw", 0.0),
            decision.get("secondary_action"),
            decision.get("secondary_amount_kw", 0.0),
            decision.get("expected_cost_egp", 0.0),
            decision.get("co2_emitted_kg", 0.0),
            decision.get("decision_interval_minutes", 60),
        ),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def get_history(conn, station_id: str, scenario: str, limit: int = 50):
    rows = conn.execute(
        "SELECT * FROM decisions WHERE station_id = ? AND scenario = ? ORDER BY id DESC LIMIT ?",
        (station_id, scenario, limit),
    ).fetchall()
    return [dict(r) for r in rows]
