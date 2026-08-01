"""Backend-only settings (DB path) + a re-export of the shared site/simulation
constants from ra_core.config, so existing `from app.config import X` call
sites throughout the backend keep working unchanged.
"""
import os

from ra_core.config import (  # noqa: F401
    BATTERY_CAPACITY_KWH,
    BATTERY_CHARGE_EFFICIENCY,
    BATTERY_DISCHARGE_EFFICIENCY,
    DAYS_OF_HISTORY,
    DEFAULT_SCENARIO,
    DEFAULT_START_INDEX,
    FORECAST_HORIZON_STEPS,
    GRID_CO2_FACTOR_KG_PER_KWH,
    INTERVAL_MINUTES,
    POINTS_PER_DAY,
    SCENARIOS,
    SOLAR_CAPACITY_KW,
    TOTAL_POINTS,
    WATER_PUMP_CAPACITY_KW,
    WATER_PUMP_VALUE_EGP_PER_KWH,
    WIND_CAPACITY_KW,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "ra.db")
