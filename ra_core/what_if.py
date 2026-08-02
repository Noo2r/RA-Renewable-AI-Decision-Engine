"""Part 5 -- What-If simulator: hypothetical station-assumption comparison.

`simulate_what_if()` answers "what would RA recommend right now if this
station's solar/wind/demand/battery assumptions were different?" without
touching anything real: the station registry, the SQLite database, the
active scenario, or the simulated clock. It is a pure function -- called
fresh on every request, no caching, no persisted hypothetical state.

How it stays comparable and side-effect free:

  * The REAL station configuration is only ever read (`get_station()`),
    never mutated. A hypothetical copy is built with `dataclasses.replace()`
    and passed directly through `generate_series()`/`forecast_surplus()`
    (both accept a StationConfig as well as a station_id, via
    `ra_core.stations.resolve_station()`) -- it is never registered.
  * Both the baseline and the hypothetical series are *regenerated* from
    scratch via `generate_series(scenario, station)`, which is a fully
    deterministic function of (scenario, station.seed_offset, a fixed
    default start_time). The hypothetical copy keeps the same
    `seed_offset`, and only the requested capacity/demand fields differ --
    so weather (cloud cover, wind speed), timestamps, and every random
    noise draw are byte-identical between the two runs; only the
    physically capacity-driven outputs (solar_kw, wind_kw, demand_kw,
    battery_soc) differ. This is what makes the comparison represent the
    user's change and nothing else.
  * The regenerated baseline is numerically identical to what
    generate_series() already produced when the real database was seeded
    (same inputs, same deterministic function) -- so "baseline" here always
    matches what /state and /decision would show for the same
    scenario/index.
  * Both runs go through the exact same forecast_surplus()/evaluate()
    pipeline already used by /forecast and /decision -- no separate model,
    no duplicated decision math.

Forecast fields (`forecast_generation_kw`, `forecast_demand_kw`,
`forecast_net_balance_kw`, `forecast_confidence_pct`) are the SAME
near-term (next 4 forecast points = 1 hour) average the decision engine
itself uses to size actions and decide mode (see
`ra_core.decision_engine.evaluate`'s `avg_surplus_next_hour`) -- not a
single next-hour point and not the full 6-hour horizon -- so the What-If
comparison is internally consistent with why the recommended action did
or didn't change.
"""
from dataclasses import replace

from ra_core.config import TOTAL_POINTS
from ra_core.decision_engine import evaluate
from ra_core.forecasting import forecast_surplus
from ra_core.stations import StationConfig, get_station

# Step 2 input ranges (inclusive), as specified.
SOLAR_CHANGE_PCT_RANGE = (-50.0, 100.0)
WIND_CHANGE_PCT_RANGE = (-50.0, 100.0)
DEMAND_CHANGE_PCT_RANGE = (-30.0, 50.0)
BATTERY_CHANGE_PCT_RANGE = (-50.0, 100.0)

_NEAR_TERM_POINTS = 4  # first 4 forecast points (15-min interval) = 1 hour, matches decision_engine


class WhatIfValidationError(ValueError):
    """Raised for a structurally invalid or out-of-range What-If request
    (e.g. a non-zero wind change on a solar-only station, or a percentage
    outside its allowed range). The API layer maps this to HTTP 422."""


def _validate_range(name: str, value: float, bounds: tuple[float, float]) -> None:
    lo, hi = bounds
    if not (lo <= value <= hi):
        raise WhatIfValidationError(f"{name} must be between {lo:g} and {hi:g} (got {value:g}).")


def _validate_inputs(station: StationConfig, solar_pct: float, wind_pct: float,
                      demand_pct: float, battery_pct: float) -> None:
    _validate_range("solar_capacity_change_pct", solar_pct, SOLAR_CHANGE_PCT_RANGE)
    _validate_range("wind_capacity_change_pct", wind_pct, WIND_CHANGE_PCT_RANGE)
    _validate_range("demand_change_pct", demand_pct, DEMAND_CHANGE_PCT_RANGE)
    _validate_range("battery_capacity_change_pct", battery_pct, BATTERY_CHANGE_PCT_RANGE)

    if station.solar_capacity_kw <= 0 and solar_pct != 0:
        raise WhatIfValidationError(
            f"solar_capacity_change_pct cannot be changed because {station.id} has no configured solar capacity."
        )
    if station.wind_capacity_kw <= 0 and wind_pct != 0:
        raise WhatIfValidationError(
            f"wind_capacity_change_pct cannot be changed because {station.id} has no configured wind capacity."
        )


def _build_hypothetical_station(station: StationConfig, solar_pct: float, wind_pct: float,
                                 demand_pct: float, battery_pct: float) -> StationConfig:
    """Immutable copy via dataclasses.replace() -- the real registry entry
    and the original StationConfig object are never touched. Charge/
    discharge rate limits scale by the same factor as battery capacity, so
    the station's existing C-rate (limit_kw / capacity_kwh) is preserved
    exactly. Min/max SoC and both efficiencies are intentionally left
    unchanged. Every field is floored at 0.0 so no percentage combination
    within the validated ranges can produce a negative capacity/demand
    (mathematically impossible here since the ranges never reach -100%,
    but kept explicit per the spec)."""
    battery_factor = 1 + battery_pct / 100
    return replace(
        station,
        solar_capacity_kw=max(0.0, station.solar_capacity_kw * (1 + solar_pct / 100)),
        wind_capacity_kw=max(0.0, station.wind_capacity_kw * (1 + wind_pct / 100)),
        demand_scale=max(0.0, station.demand_scale * (1 + demand_pct / 100)),
        battery_capacity_kwh=max(0.0, station.battery_capacity_kwh * battery_factor),
        battery_charge_limit_kw=max(0.0, station.battery_charge_limit_kw * battery_factor),
        battery_discharge_limit_kw=max(0.0, station.battery_discharge_limit_kw * battery_factor),
    )


def _avg(values, default=0.0):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else default


def _run_pipeline(station: StationConfig, scenario: str, current_index: int) -> tuple[dict, str]:
    """Regenerates a full deterministic series for `station` (real or
    hypothetical) and runs the existing forecast_surplus()/evaluate()
    pipeline on it -- the same call shape /decision uses, just with
    freshly generated (not database-read) rows. Returns (result, timestamp)."""
    from ra_core.data_generator import generate_series  # local import avoids a cycle at module load

    df = generate_series(scenario, station_id=station)
    all_rows = df.to_dict("records")
    reading = all_rows[current_index]
    future_rows = all_rows[current_index + 1: current_index + 13]
    future_prices = [r["price_egp"] for r in future_rows]

    fc = forecast_surplus(all_rows, current_index, station_id=station)
    result = evaluate(
        reading, fc["forecast"], future_prices,
        battery_capacity_kwh=station.battery_capacity_kwh,
        battery_charge_limit_kw=station.battery_charge_limit_kw,
        battery_discharge_limit_kw=station.battery_discharge_limit_kw,
        battery_min_soc_pct=station.battery_min_soc_pct,
        battery_max_soc_pct=station.battery_max_soc_pct,
        battery_charge_efficiency=station.battery_charge_efficiency,
        battery_discharge_efficiency=station.battery_discharge_efficiency,
    )

    near_term = fc["forecast"][:_NEAR_TERM_POINTS]
    forecast_generation_kw = _avg([p["generation_kw"] for p in near_term], default=result["before"]["generation_kw"])
    forecast_demand_kw = _avg([p["demand_kw"] for p in near_term], default=result["before"]["demand_kw"])
    forecast_confidence_pct = _avg([p["net_balance_confidence_pct"] for p in near_term], default=None)

    recommended = result["recommended"]
    pipeline_result = {
        "solar_capacity_kw": round(station.solar_capacity_kw, 2),
        "wind_capacity_kw": round(station.wind_capacity_kw, 2),
        "battery_capacity_kwh": round(station.battery_capacity_kwh, 2),

        "current_generation_kw": result["before"]["generation_kw"],
        "current_demand_kw": result["before"]["demand_kw"],
        "current_net_balance_kw": result["before"]["net_balance_kw"],
        "current_battery_soc_pct": result["before"]["battery_soc_pct"],

        "forecast_generation_kw": round(forecast_generation_kw, 2),
        "forecast_demand_kw": round(forecast_demand_kw, 2),
        "forecast_net_balance_kw": round(forecast_generation_kw - forecast_demand_kw, 2),
        "forecast_confidence_pct": round(forecast_confidence_pct, 1) if forecast_confidence_pct is not None else None,

        "mode": result["mode"],
        "priority": result["priority"],
        "recommended_action": recommended["action"],
        "recommended_amount_kw": recommended["amount_kw"],

        "expected_value_egp": recommended["expected_value_egp"],
        "expected_cost_egp": recommended["expected_cost_egp"],
        "co2_avoided_kg": recommended["co2_avoided_kg"],
        "co2_emitted_kg": recommended["co2_emitted_kg"],
        "remaining_deficit_kw": result["remaining_deficit_kw"],
        "secondary_action": result["secondary_action"],
        "secondary_amount_kw": result["secondary_amount_kw"],
    }
    return pipeline_result, reading["timestamp"]


def _safe_pct_change(old: float, new: float):
    """Percentage change from old to new. Returns None (not inf/NaN) when
    old == 0, since a percentage change from a zero baseline is undefined."""
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 1)


def _compute_impact(baseline: dict, hypothetical: dict) -> dict:
    gen_delta = hypothetical["forecast_generation_kw"] - baseline["forecast_generation_kw"]
    dem_delta = hypothetical["forecast_demand_kw"] - baseline["forecast_demand_kw"]
    return {
        "generation_change_kw": round(gen_delta, 2),
        "generation_change_pct": _safe_pct_change(baseline["forecast_generation_kw"], hypothetical["forecast_generation_kw"]),

        "demand_change_kw": round(dem_delta, 2),
        "demand_change_pct": _safe_pct_change(baseline["forecast_demand_kw"], hypothetical["forecast_demand_kw"]),

        "net_balance_change_kw": round(
            hypothetical["forecast_net_balance_kw"] - baseline["forecast_net_balance_kw"], 2
        ),

        "battery_capacity_change_kwh": round(
            hypothetical["battery_capacity_kwh"] - baseline["battery_capacity_kwh"], 2
        ),

        "expected_value_change_egp": round(hypothetical["expected_value_egp"] - baseline["expected_value_egp"], 2),
        "expected_cost_change_egp": round(hypothetical["expected_cost_egp"] - baseline["expected_cost_egp"], 2),

        "co2_avoided_change_kg": round(hypothetical["co2_avoided_kg"] - baseline["co2_avoided_kg"], 2),
        "co2_emitted_change_kg": round(hypothetical["co2_emitted_kg"] - baseline["co2_emitted_kg"], 2),

        "remaining_deficit_change_kw": round(
            hypothetical["remaining_deficit_kw"] - baseline["remaining_deficit_kw"], 2
        ),

        "decision_changed": hypothetical["recommended_action"] != baseline["recommended_action"],
        "mode_changed": hypothetical["mode"] != baseline["mode"],
        "priority_changed": hypothetical["priority"] != baseline["priority"],
    }


# Mirrors the frontend's ACTION_LABELS (DecisionCard.jsx/HistoryTimeline.jsx/
# EgyptMap.jsx/WhatIfPanel.jsx) so the backend-generated explanation text
# uses the same human-readable names shown on screen. Duplicated rather than
# shared cross-language (Python has no way to import a .jsx dict) -- this is
# the one small, deliberately duplicated constant, not general decision logic.
_ACTION_LABELS = {
    "battery_charge": "Battery Charge",
    "battery_discharge": "Battery Discharge",
    "water_pumping": "Water Pumping / Desalination",
    "sell_grid": "Sell to Grid",
    "grid_import": "Grid Support",
    "curtail": "Curtailment",
}


def _label(action: str) -> str:
    return _ACTION_LABELS.get(action, action.replace("_", " ").title() if action else "—")


def _describe_requested_changes(inputs: dict) -> str:
    labels = {
        "solar_capacity_change_pct": "solar capacity",
        "wind_capacity_change_pct": "wind capacity",
        "demand_change_pct": "demand",
        "battery_capacity_change_pct": "battery capacity",
    }
    parts = [f"{label} by {inputs[key]:+.0f}%" for key, label in labels.items() if inputs[key] != 0]
    if not parts:
        return "No hypothetical changes were requested, so"
    if len(parts) == 1:
        return f"Changing {parts[0]}"
    return "Changing " + ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _build_explanation(inputs: dict, baseline: dict, hypothetical: dict, impact: dict) -> str:
    sentences = [
        f"{_describe_requested_changes(inputs)} changes the expected one-hour generation by "
        f"{impact['generation_change_kw']:+.1f} kW and demand by {impact['demand_change_kw']:+.1f} kW."
    ]

    net_delta = impact["net_balance_change_kw"]
    if net_delta > 0.05:
        sentences.append(f"Net balance improves by {net_delta:+.1f} kW.")
    elif net_delta < -0.05:
        sentences.append(f"Net balance worsens by {net_delta:+.1f} kW.")
    else:
        sentences.append("Net balance is essentially unchanged.")

    if impact["decision_changed"]:
        sentences.append(
            f"The recommended action changes from {_label(baseline['recommended_action'])} to "
            f"{_label(hypothetical['recommended_action'])}."
        )
    else:
        sentences.append(f"The recommended action remains {_label(hypothetical['recommended_action'])}.")
    if impact["mode_changed"]:
        sentences.append(f"Mode changes from {baseline['mode']} to {hypothetical['mode']}.")

    econ_delta = impact["expected_value_change_egp"] - impact["expected_cost_change_egp"]
    sentences.append(f"Expected net economic value changes by {econ_delta:+.1f} EGP.")

    co2_delta = impact["co2_avoided_change_kg"] - impact["co2_emitted_change_kg"]
    if co2_delta >= 0:
        sentences.append(f"An additional {co2_delta:.1f} kg of CO2 is avoided.")
    else:
        sentences.append(f"{abs(co2_delta):.1f} kg more CO2 is emitted.")

    return " ".join(sentences)


def simulate_what_if(
    station_id: str,
    scenario: str,
    current_index: int,
    solar_capacity_change_pct: float = 0.0,
    wind_capacity_change_pct: float = 0.0,
    demand_change_pct: float = 0.0,
    battery_capacity_change_pct: float = 0.0,
) -> dict:
    """Compares a station's real (baseline) decision against a hypothetical
    one under up to four percentage-change assumptions, at the same
    scenario/simulated-index/weather/random-seed. Side-effect free: reads
    the registry once, never writes to it, the database, or any global
    state. Raises UnknownStationError for a bad station_id and
    WhatIfValidationError for an out-of-range or structurally invalid
    change request.
    """
    station = get_station(station_id)  # raises UnknownStationError if invalid -- read-only lookup

    if not (0 <= current_index < TOTAL_POINTS):
        raise WhatIfValidationError(f"current_index must be between 0 and {TOTAL_POINTS - 1} (got {current_index}).")

    _validate_inputs(station, solar_capacity_change_pct, wind_capacity_change_pct,
                      demand_change_pct, battery_capacity_change_pct)

    hypothetical_station = _build_hypothetical_station(
        station, solar_capacity_change_pct, wind_capacity_change_pct,
        demand_change_pct, battery_capacity_change_pct,
    )

    baseline, baseline_timestamp = _run_pipeline(station, scenario, current_index)
    hypothetical, hypothetical_timestamp = _run_pipeline(hypothetical_station, scenario, current_index)
    # Both runs share the same scenario, the same fixed generate_series()
    # start_time, and the same index, so their timestamps are identical by
    # construction; asserting it here catches any future regression of
    # that guarantee immediately rather than silently reporting a wrong one.
    assert baseline_timestamp == hypothetical_timestamp, "baseline/hypothetical timestamp drift"
    impact = _compute_impact(baseline, hypothetical)

    inputs = {
        "solar_capacity_change_pct": solar_capacity_change_pct,
        "wind_capacity_change_pct": wind_capacity_change_pct,
        "demand_change_pct": demand_change_pct,
        "battery_capacity_change_pct": battery_capacity_change_pct,
    }

    return {
        "station_id": station.id,
        "scenario": scenario,
        "current_index": current_index,
        "timestamp": baseline_timestamp,
        "inputs": inputs,
        "baseline": baseline,
        "hypothetical": hypothetical,
        "impact": impact,
        "explanation": _build_explanation(inputs, baseline, hypothetical, impact),
    }
