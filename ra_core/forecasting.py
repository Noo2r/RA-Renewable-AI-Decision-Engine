"""Short-horizon (1-6h) forecasting.

Part 2 replaces the single combined "generation" model with three
separate GradientBoostingRegressor models -- solar_kw, wind_kw, demand_kw
-- trained per station. Total generation and net balance are *derived*
(solar + wind, generation - demand), never predicted directly. Each
component forecast also carries an empirical uncertainty interval and a
model-confidence score (see module constants below for exactly how).

Design notes (kept deliberately small and explainable):

* Features are unchanged from Part 0/1: hour_sin, hour_cos, cloud_cover,
  wind_speed. No new synthetic fields (e.g. temperature) exist in the
  generator, so none are added here.
* Validation is chronological: the first 80% of history (rows stay in
  their original time order) trains a holdout model, the last 20% validates it. The
  live forecast itself is produced by a second model trained on all of
  history -- exactly the same two-model pattern the Part 0/1 pipeline
  already used for its single combined-generation model.
* Uncertainty intervals are empirical: residuals (actual - predicted) on
  the chronological holdout slice are used to take the 10th/90th
  percentile, giving an approximate 80% empirical prediction interval.
  This is NOT a formal probabilistic guarantee -- it is a small, honest
  P0 method built on held-out error, and it inherits an optimistic
  assumption from the underlying simulator: future weather (cloud cover,
  wind speed) is supplied as ground truth, not a noisy real forecast, so
  real-world uncertainty would be higher than what's shown here.
* The interval widens with horizon via a simple sqrt(hours-ahead) inflation
  factor (T+1 narrowest, T+6 widest) -- a transparent, monotonic rule, not
  a statistical model of how error actually compounds over time.
* A station's structurally zero-capacity source (e.g. wind on a solar-only
  station) is never modeled at all -- it is reported as an exact zero with
  a zero-width interval and method="structural_zero", never a trained-model
  confidence score.
* Confidence scores are derived from the *raw* (pre physical-clipping)
  interval width relative to a natural scale (station capacity for
  solar/wind, historical peak demand for demand), clamped to [50, 99].
  Using the raw width (rather than the physically-clipped display width)
  guarantees confidence is a clean, monotonically non-increasing function
  of horizon for a given target -- clipping only affects the *displayed*
  lower/upper bounds, not the confidence score itself. Confidence is a
  model-confidence score, not a probability that the prediction is
  correct.
"""
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from ra_core.config import FORECAST_HORIZON_STEPS, INTERVAL_MINUTES
from ra_core.stations import DEFAULT_STATION_ID, get_station

# --- Confidence / interval constants (all referenced from the report) ------
CONFIDENCE_MIN_PCT = 50.0
CONFIDENCE_MAX_PCT = 99.0
RESIDUAL_LOWER_QUANTILE = 0.10
RESIDUAL_UPPER_QUANTILE = 0.90
INTERVAL_NOMINAL_COVERAGE_PCT = 80  # 90th - 10th percentile ~= empirical 80% interval
VALIDATION_METHOD = "chronological_holdout"
INTERVAL_METHOD = "empirical_residual_quantiles"
MODEL_PARAMS = dict(n_estimators=60, max_depth=3, learning_rate=0.1, random_state=0)


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


def _train(df_hist: pd.DataFrame, target: np.ndarray) -> GradientBoostingRegressor:
    """Final model used for the live forecast: trained on ALL of history."""
    model = GradientBoostingRegressor(**MODEL_PARAMS)
    model.fit(_features(df_hist), target)
    return model


def _chronological_holdout(df_hist: pd.DataFrame, target: np.ndarray):
    """Train on the first 80% (row order = chronological, kept as-generated),
    predict the held-out last 20%. Returns (mae, residuals, holdout_actual,
    holdout_pred) -- an honest out-of-sample error, used both to report
    model_quality and to build empirical residual-quantile intervals.
    """
    n = len(df_hist)
    if n < 20:
        empty = np.array([])
        return float("nan"), empty, empty, empty
    split = int(n * 0.8)
    X = _features(df_hist)
    model = GradientBoostingRegressor(**MODEL_PARAMS)
    model.fit(X.iloc[:split], target[:split])
    holdout_actual = target[split:]
    holdout_pred = model.predict(X.iloc[split:])
    residuals = holdout_actual - holdout_pred
    mae = float(mean_absolute_error(holdout_actual, holdout_pred))
    return mae, residuals, holdout_actual, holdout_pred


def _residual_quantiles(residuals: np.ndarray) -> tuple[float, float]:
    if len(residuals) == 0:
        return 0.0, 0.0
    lo = float(np.quantile(residuals, RESIDUAL_LOWER_QUANTILE))
    hi = float(np.quantile(residuals, RESIDUAL_UPPER_QUANTILE))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _horizon_inflation(horizon_hour: float) -> float:
    """P0 uncertainty-growth rule: sqrt(hours-ahead). Simple, transparent,
    and strictly increasing in horizon_hour -- not a formal probability
    model of how error actually compounds over time."""
    return math.sqrt(max(horizon_hour, 1e-6))


def _confidence_from_width(width: float, scale: float) -> float:
    """Model-confidence score -- NOT the probability the prediction is
    correct. normalized_uncertainty = width / scale; confidence =
    100 * (1 - normalized_uncertainty), clamped to
    [CONFIDENCE_MIN_PCT, CONFIDENCE_MAX_PCT]."""
    if scale <= 0:
        return CONFIDENCE_MAX_PCT
    normalized = width / scale
    conf = 100.0 * (1.0 - normalized)
    return float(np.clip(conf, CONFIDENCE_MIN_PCT, CONFIDENCE_MAX_PCT))


def _clip(value: float, lo: float, hi: float | None) -> float:
    if hi is not None:
        value = min(value, hi)
    return max(value, lo)


def _forecast_one_target(df_hist: pd.DataFrame, df_future: pd.DataFrame, target_col: str,
                          capacity: float | None) -> dict:
    """Forecast one component (solar_kw / wind_kw / demand_kw).

    capacity=None means unconstrained-above (demand has no hard capacity in
    this system). capacity<=0 means a structurally zero-capacity source
    (e.g. wind on a solar-only station) -- no model is trained at all; the
    source is reported as an exact zero, method="structural_zero".
    """
    n_future = len(df_future)
    n_hist = len(df_hist)
    structural_zero = capacity is not None and capacity <= 0

    if structural_zero:
        points = [
            dict(pred=0.0, lower=0.0, upper=0.0, confidence=None, method="structural_zero")
            for _ in range(n_future)
        ]
        holdout_len = max(n_hist - int(n_hist * 0.8), 0) if n_hist >= 20 else 0
        zeros = np.zeros(holdout_len)
        return dict(points=points, mae=None, holdout_actual=zeros, holdout_pred=zeros)

    target = df_hist[target_col].values
    mae, residuals, holdout_actual, holdout_pred = _chronological_holdout(df_hist, target)
    resid_lo, resid_hi = _residual_quantiles(residuals)
    scale = capacity if capacity is not None else max(float(df_hist[target_col].max()), 1e-6)

    points = []
    if n_future > 0:
        model = _train(df_hist, target)
        raw_preds = model.predict(_features(df_future))
        for h_idx in range(n_future):
            horizon_hour = (h_idx + 1) * INTERVAL_MINUTES / 60
            inflation = _horizon_inflation(horizon_hour)
            p_raw = float(raw_preds[h_idx])

            # Confidence uses the RAW (pre-clip) width -- a function of
            # horizon + validation residual spread only, guaranteeing it
            # never increases with horizon regardless of where a specific
            # prediction happens to sit relative to the physical capacity.
            raw_width = (resid_hi - resid_lo) * inflation
            confidence = _confidence_from_width(raw_width, scale)

            lo = p_raw + resid_lo * inflation
            hi = p_raw + resid_hi * inflation
            p = _clip(p_raw, 0.0, capacity)
            lo = _clip(lo, 0.0, capacity)
            hi = _clip(hi, 0.0, capacity)
            lo = min(lo, p)  # safety net: independent clipping could invert order
            hi = max(hi, p)

            points.append(dict(
                pred=round(p, 2), lower=round(lo, 2), upper=round(hi, 2),
                confidence=round(confidence, 1), method="model",
            ))

    mae_out = None if (mae is None or math.isnan(mae)) else round(mae, 2)
    return dict(points=points, mae=mae_out, holdout_actual=holdout_actual, holdout_pred=holdout_pred)


def forecast_components(all_rows: list[dict], current_index: int, station_id: str = DEFAULT_STATION_ID,
                         history_window: int = 16) -> dict:
    """Core Part 2 forecasting function, shared by the backend and the
    notebook. all_rows: full readings list for one station+scenario,
    ordered by idx. current_index: the simulated 'now' pointer.

    Returns forward-only component forecasts (solar/wind/demand + derived
    generation/net-balance, each with an interval and a confidence score)
    plus model_quality metrics. Does not include recent history -- see
    forecast_surplus() for the history-enriched, backward-compatible view.
    """
    station = get_station(station_id)
    df_all = pd.DataFrame(all_rows)
    df_hist = df_all.iloc[: current_index + 1]

    future_end = min(current_index + FORECAST_HORIZON_STEPS, len(df_all) - 1)
    df_future = df_all.iloc[current_index + 1: future_end + 1]
    n_future = len(df_future)

    solar = _forecast_one_target(df_hist, df_future, "solar_kw", station.solar_capacity_kw)
    wind = _forecast_one_target(df_hist, df_future, "wind_kw", station.wind_capacity_kw)
    demand = _forecast_one_target(df_hist, df_future, "demand_kw", None)

    # Generation/net-balance MAE are DERIVED from the same held-out rows
    # the component models validated against -- not a separate model.
    generation_mae = None
    net_balance_mae = None
    if len(demand["holdout_actual"]) > 0:  # demand is never structural-zero
        gen_actual = solar["holdout_actual"] + wind["holdout_actual"]
        gen_pred = solar["holdout_pred"] + wind["holdout_pred"]
        generation_mae = round(float(mean_absolute_error(gen_actual, gen_pred)), 2)
        net_actual = gen_actual - demand["holdout_actual"]
        net_pred = gen_pred - demand["holdout_pred"]
        net_balance_mae = round(float(mean_absolute_error(net_actual, net_pred)), 2)

    timestamps = [row.timestamp for row in df_future.itertuples(index=False)] if n_future else []
    actual_solar = df_future["solar_kw"].values if n_future else np.array([])
    actual_wind = df_future["wind_kw"].values if n_future else np.array([])
    actual_demand = df_future["demand_kw"].values if n_future else np.array([])

    forecast_points = []
    for i in range(n_future):
        s, w, d = solar["points"][i], wind["points"][i], demand["points"][i]

        gen_pred = s["pred"] + w["pred"]
        gen_lower = s["lower"] + w["lower"]
        gen_upper = s["upper"] + w["upper"]
        gen_confidences = [c for c in (s["confidence"], w["confidence"]) if c is not None]
        gen_confidence = round(min(gen_confidences), 1) if gen_confidences else None

        net_pred = gen_pred - d["pred"]
        net_lower = gen_lower - d["upper"]  # conservative: worst-case demand vs. worst-case generation
        net_upper = gen_upper - d["lower"]  # optimistic: best-case demand vs. best-case generation
        net_confidences = [c for c in (gen_confidence, d["confidence"]) if c is not None]
        net_confidence = round(min(net_confidences), 1) if net_confidences else None

        actual_gen = float(actual_solar[i] + actual_wind[i])
        actual_net = actual_gen - float(actual_demand[i])

        forecast_points.append({
            "timestamp": timestamps[i],
            "horizon_hour": round((i + 1) * INTERVAL_MINUTES / 60, 2),

            "solar_kw": s["pred"], "solar_lower_kw": s["lower"], "solar_upper_kw": s["upper"],
            "solar_confidence_pct": s["confidence"], "solar_method": s["method"],

            "wind_kw": w["pred"], "wind_lower_kw": w["lower"], "wind_upper_kw": w["upper"],
            "wind_confidence_pct": w["confidence"], "wind_method": w["method"],

            "generation_kw": round(gen_pred, 2), "generation_lower_kw": round(gen_lower, 2),
            "generation_upper_kw": round(gen_upper, 2), "generation_confidence_pct": gen_confidence,

            "demand_kw": d["pred"], "demand_lower_kw": d["lower"], "demand_upper_kw": d["upper"],
            "demand_confidence_pct": d["confidence"],

            "net_balance_kw": round(net_pred, 2), "net_balance_lower_kw": round(net_lower, 2),
            "net_balance_upper_kw": round(net_upper, 2), "net_balance_confidence_pct": net_confidence,

            "actual_solar_kw": round(float(actual_solar[i]), 2),
            "actual_wind_kw": round(float(actual_wind[i]), 2),
            "actual_demand_kw": round(float(actual_demand[i]), 2),
            "actual_generation_kw": round(actual_gen, 2),
            "actual_net_balance_kw": round(actual_net, 2),
        })

    return {
        "interval_minutes": INTERVAL_MINUTES,
        "forecast": forecast_points,
        "model_quality": {
            "solar_mae_kw": solar["mae"],
            "wind_mae_kw": wind["mae"],
            "generation_mae_kw": generation_mae,
            "demand_mae_kw": demand["mae"],
            "net_balance_mae_kw": net_balance_mae,
            "validation_method": VALIDATION_METHOD,
            "interval_method": INTERVAL_METHOD,
            "interval_nominal_coverage_pct": INTERVAL_NOMINAL_COVERAGE_PCT,
        },
    }


def forecast_surplus(all_rows: list[dict], current_index: int, station_id: str = DEFAULT_STATION_ID,
                      history_window: int = 16) -> dict:
    """Backward-compatible entry point (Part 0/1 contract). Internally
    calls forecast_components() and derives the original
    {timestamp, forecast_surplus_kw, actual_surplus_kw} fields
    (forecast_surplus_kw == net_balance_kw) -- existing callers reading
    only those fields (the decision engine, old tests) keep working
    unchanged. All new component/interval/confidence fields are merged in
    additively on the same per-point dict.

    station_id defaults to DEFAULT_STATION_ID so existing calls that only
    ever passed (all_rows, current_index) keep behaving exactly as before,
    since those rows were always DEFAULT_STATION_ID's data in Part 0/1.
    """
    components = forecast_components(all_rows, current_index, station_id, history_window=history_window)

    df_all = pd.DataFrame(all_rows)
    hist_start = max(0, current_index - history_window + 1)
    df_recent = df_all.iloc[hist_start: current_index + 1]
    history_points = [
        {
            "timestamp": row.timestamp,
            "actual_surplus_kw": round(float(row.solar_kw + row.wind_kw - row.demand_kw), 2),
            "actual_solar_kw": round(float(row.solar_kw), 2),
            "actual_wind_kw": round(float(row.wind_kw), 2),
            "actual_demand_kw": round(float(row.demand_kw), 2),
        }
        for row in df_recent.itertuples(index=False)
    ]

    forecast_points = []
    for p in components["forecast"]:
        merged = dict(p)
        merged["forecast_surplus_kw"] = p["net_balance_kw"]
        merged["actual_surplus_kw"] = p["actual_net_balance_kw"]
        forecast_points.append(merged)

    return {
        "interval_minutes": components["interval_minutes"],
        "history": history_points,
        "forecast": forecast_points,
        "model_quality": components["model_quality"],
    }
