"""Site + simulation constants shared by every RA front end (API, notebook).

Deliberately contains no file paths or persistence settings — those are
presentation-layer concerns (see backend/app/config.py for the API's
SQLite path).
"""

INTERVAL_MINUTES = 15
DAYS_OF_HISTORY = 4
POINTS_PER_DAY = (24 * 60) // INTERVAL_MINUTES
TOTAL_POINTS = POINTS_PER_DAY * DAYS_OF_HISTORY

# Site asset assumptions
BATTERY_CAPACITY_KWH = 50.0
BATTERY_CHARGE_EFFICIENCY = 0.95
BATTERY_DISCHARGE_EFFICIENCY = 0.95
SOLAR_CAPACITY_KW = 40.0
WIND_CAPACITY_KW = 15.0
WATER_PUMP_CAPACITY_KW = 12.0
WATER_PUMP_VALUE_EGP_PER_KWH = 2.2  # value of desalinated/pumped water per kWh consumed
GRID_CO2_FACTOR_KG_PER_KWH = 0.45  # avg Egypt grid emission factor

SCENARIOS = ["sunny", "cloudy", "windy", "high_demand"]
DEFAULT_SCENARIO = "sunny"

# Simulated clock starts at this point into the series so a surplus event
# is immediately visible on first load (mid-morning of day 2).
DEFAULT_START_INDEX = POINTS_PER_DAY + (10 * 60) // INTERVAL_MINUTES

FORECAST_HORIZON_STEPS = 24  # 24 * 15min = 6 hours
