"""Lightweight short-horizon (1-6h) surplus forecasting.

Uses a small GradientBoostingRegressor per target (generation, demand) with
time-of-day + weather features. Weather (cloud cover / wind speed) is treated
as a known near-term forecast input, which is realistic for a 1-6h horizon.
Models are cheap to train (<1s on a few hundred rows) so we retrain on
demand and cache the result per (scenario, index) to keep repeated polling
fast without adding staleness.
"""
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from ra_core.config import FORECAST_HORIZON_STEPS, INTERVAL_MINUTES


def _features(df: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp"])
    hour = ts.dt.hour + ts.dt.minute / 60
    feats = pd.DataFrame({
        "hour_sin": np.sin(hour / 24 * 2 * np.pi),
        "hour_cos": np.cos(hour / 24 * 2 * np.pi),
        "cloud_cover": df["cloud_cover"].values,
        "wind_speed": df["wind_speed"].values,
    })
    return feats


def _train(df_hist: pd.DataFrame, target: np.ndarray):
    model = GradientBoostingRegressor(n_estimators=60, max_depth=3, learning_rate=0.1, random_state=0)
    X = _features(df_hist)
    model.fit(X, target)
    return model


def _holdout_mae(df_hist: pd.DataFrame, target: np.ndarray) -> float:
    n = len(df_hist)
    if n < 20:
        return float("nan")
    split = int(n * 0.8)
    X = _features(df_hist)
    model = GradientBoostingRegressor(n_estimators=60, max_depth=3, learning_rate=0.1, random_state=0)
    model.fit(X.iloc[:split], target[:split])
    preds = model.predict(X.iloc[split:])
    return float(mean_absolute_error(target[split:], preds))


def forecast_surplus(all_rows: list[dict], current_index: int, history_window: int = 16) -> dict:
    """all_rows: full readings list for the scenario, ordered by idx.
    current_index: the simulated 'now' pointer into all_rows.
    Returns recent history + forward forecast, using ground-truth future
    weather as the forecast input (as a real short-term weather forecast would).
    """
    df_all = pd.DataFrame(all_rows)
    df_hist = df_all.iloc[: current_index + 1]

    generation = (df_hist["solar_kw"] + df_hist["wind_kw"]).values
    demand = df_hist["demand_kw"].values

    gen_model = _train(df_hist, generation)
    demand_model = _train(df_hist, demand)
    gen_mae = _holdout_mae(df_hist, generation)
    demand_mae = _holdout_mae(df_hist, demand)

    future_end = min(current_index + FORECAST_HORIZON_STEPS, len(df_all) - 1)
    df_future = df_all.iloc[current_index + 1: future_end + 1]

    forecast_points = []
    if len(df_future) > 0:
        X_future = _features(df_future)
        gen_pred = gen_model.predict(X_future)
        demand_pred = demand_model.predict(X_future)
        surplus_pred = gen_pred - demand_pred
        actual_surplus = (df_future["solar_kw"] + df_future["wind_kw"] - df_future["demand_kw"]).values
        for i, row in enumerate(df_future.itertuples(index=False)):
            forecast_points.append({
                "timestamp": row.timestamp,
                "forecast_surplus_kw": round(float(surplus_pred[i]), 2),
                "actual_surplus_kw": round(float(actual_surplus[i]), 2),
            })

    hist_start = max(0, current_index - history_window + 1)
    df_recent = df_all.iloc[hist_start: current_index + 1]
    history_points = [
        {
            "timestamp": row.timestamp,
            "actual_surplus_kw": round(float(row.solar_kw + row.wind_kw - row.demand_kw), 2),
        }
        for row in df_recent.itertuples(index=False)
    ]

    return {
        "interval_minutes": INTERVAL_MINUTES,
        "history": history_points,
        "forecast": forecast_points,
        "model_quality": {
            "generation_mae_kw": None if math.isnan(gen_mae) else round(gen_mae, 2),
            "demand_mae_kw": None if math.isnan(demand_mae) else round(demand_mae, 2),
        },
    }
