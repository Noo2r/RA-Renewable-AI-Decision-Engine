"""Deterministic synthetic time-series generator for the RA MVP.

Each scenario produces a full multi-day dataset (solar/wind generation,
site demand, grid price, weather, and a physically-plausible battery
state-of-charge trace) using smooth diurnal curves + seeded noise so the
same scenario always reproduces the same data (good for demos).

Multi-station note: generation is parameterized by a StationConfig (solar/
wind capacity, demand scale, battery capacity, seed offset). The default
station (DEFAULT_STATION_ID = "hybrid-01") is configured with the same
capacities/demand scale/seed offset as the original single-station MVP, so
generate_series(scenario) with no station argument is byte-identical to
the Part 0 baseline.
"""
import hashlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ra_core.config import (
    BATTERY_CHARGE_EFFICIENCY,
    BATTERY_DISCHARGE_EFFICIENCY,
    INTERVAL_MINUTES,
    TOTAL_POINTS,
)
from ra_core.stations import DEFAULT_STATION_ID, StationConfig, get_station

SCENARIO_PARAMS = {
    "sunny": dict(cloud_base=0.12, cloud_amp=0.08, wind_base=4.5, wind_amp=2.5,
                  demand_scale=1.0, price_volatility=1.0),
    "cloudy": dict(cloud_base=0.55, cloud_amp=0.30, wind_base=5.5, wind_amp=3.0,
                   demand_scale=1.0, price_volatility=1.0),
    "windy": dict(cloud_base=0.20, cloud_amp=0.15, wind_base=11.0, wind_amp=3.5,
                  demand_scale=1.0, price_volatility=1.0),
    "high_demand": dict(cloud_base=0.15, cloud_amp=0.10, wind_base=5.0, wind_amp=2.5,
                         demand_scale=1.45, price_volatility=1.4),
}


def _seed_for(scenario: str, seed_offset: int) -> int:
    # hashlib (unlike Python's built-in hash()) is stable across processes,
    # which is required for determinism across restarts/notebook/tests.
    base = int(hashlib.sha256(scenario.encode()).hexdigest(), 16)
    return (base + seed_offset) % (2 ** 32)


def generate_series(
    scenario: str,
    station_id: str = DEFAULT_STATION_ID,
    start_time: datetime | None = None,
) -> pd.DataFrame:
    if scenario not in SCENARIO_PARAMS:
        raise ValueError(f"Unknown scenario: {scenario}")
    station: StationConfig = get_station(station_id)
    params = SCENARIO_PARAMS[scenario]
    rng = np.random.default_rng(_seed_for(scenario, station.seed_offset))

    start_time = start_time or datetime(2026, 7, 1, 0, 0, 0)
    timestamps = [start_time + timedelta(minutes=INTERVAL_MINUTES * i) for i in range(TOTAL_POINTS)]
    hour_of_day = np.array([t.hour + t.minute / 60 for t in timestamps])

    # --- Weather -----------------------------------------------------
    cloud_cover = np.clip(
        params["cloud_base"] + params["cloud_amp"] * np.sin(hour_of_day / 24 * 2 * np.pi * 3 + 1.0)
        + rng.normal(0, 0.06, TOTAL_POINTS),
        0, 0.95,
    )
    wind_speed = np.clip(
        params["wind_base"] + params["wind_amp"] * np.sin(hour_of_day / 24 * 2 * np.pi + 2.5)
        + rng.normal(0, 1.2, TOTAL_POINTS),
        0, None,
    )

    # --- Generation ----------------------------------------------------
    # Solar bell curve centered at noon, zero at night, suppressed by cloud cover.
    # Station solar_capacity_kw == 0 (wind-only stations) forces solar_kw to 0
    # via the clip upper bound, regardless of noise.
    daylight = np.clip(np.sin((hour_of_day - 6) / 12 * np.pi), 0, None)
    solar_kw = station.solar_capacity_kw * (daylight ** 1.3) * (1 - 0.85 * cloud_cover)
    solar_kw = np.clip(solar_kw + rng.normal(0, 0.4, TOTAL_POINTS), 0, station.solar_capacity_kw)

    # Wind power ~ cube of wind speed, capped at rated capacity. Station
    # wind_capacity_kw == 0 (solar-only stations) forces wind_kw to 0 via the
    # clip upper bound, regardless of wind speed or noise.
    wind_power_raw = 0.015 * wind_speed ** 3
    wind_kw = np.clip(wind_power_raw, 0, station.wind_capacity_kw)
    wind_kw = np.clip(wind_kw + rng.normal(0, 0.3, TOTAL_POINTS), 0, station.wind_capacity_kw)

    # --- Demand: morning + evening double peak -------------------------
    # Station demand_scale (site size) composes multiplicatively with the
    # scenario's demand_scale (shared weather/grid condition across stations).
    morning_peak = 9 * np.exp(-((hour_of_day - 8.5) ** 2) / (2 * 1.8 ** 2))
    evening_peak = 14 * np.exp(-((hour_of_day - 19.5) ** 2) / (2 * 2.2 ** 2))
    base_load = 6
    demand_kw = (base_load + morning_peak + evening_peak) * params["demand_scale"] * station.demand_scale
    demand_kw = np.clip(demand_kw + rng.normal(0, 0.5, TOTAL_POINTS), 2, None)

    # --- Grid price: time-of-use with evening peak pricing -------------
    tou_multiplier = 1 + 0.5 * np.exp(-((hour_of_day - 19.5) ** 2) / (2 * 2.5 ** 2))
    night_discount = 1 - 0.35 * np.exp(-((hour_of_day - 3) ** 2) / (2 * 2.5 ** 2))
    price_egp = 1.6 * tou_multiplier * night_discount * params["price_volatility"]
    price_egp = np.clip(price_egp + rng.normal(0, 0.05, TOTAL_POINTS), 0.5, None)

    # --- Battery state of charge: simulate physically plausible trace --
    battery_capacity_kwh = station.battery_capacity_kwh
    soc = np.zeros(TOTAL_POINTS)
    current_soc = 50.0
    dt_h = INTERVAL_MINUTES / 60
    surplus_kw = solar_kw + wind_kw - demand_kw
    for i in range(TOTAL_POINTS):
        s = surplus_kw[i]
        if s > 0:
            headroom_kwh = battery_capacity_kwh * (1 - current_soc / 100)
            charge_kwh = min(s * dt_h * BATTERY_CHARGE_EFFICIENCY, headroom_kwh)
            current_soc += (charge_kwh / battery_capacity_kwh) * 100
        else:
            available_kwh = battery_capacity_kwh * (current_soc / 100)
            discharge_kwh = min(-s * dt_h / BATTERY_DISCHARGE_EFFICIENCY, available_kwh)
            current_soc -= (discharge_kwh / battery_capacity_kwh) * 100
        current_soc = float(np.clip(current_soc, 2, 98))
        soc[i] = current_soc

    df = pd.DataFrame({
        "timestamp": [t.isoformat() for t in timestamps],
        "scenario": scenario,
        "station_id": station.id,
        "solar_kw": np.round(solar_kw, 2),
        "wind_kw": np.round(wind_kw, 2),
        "demand_kw": np.round(demand_kw, 2),
        "price_egp": np.round(price_egp, 3),
        "battery_soc": np.round(soc, 2),
        "cloud_cover": np.round(cloud_cover, 3),
        "wind_speed": np.round(wind_speed, 2),
    })
    return df
