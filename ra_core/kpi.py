"""Aggregate KPI helpers over a sequence of logged decisions.

Note: the FastAPI/React app does not currently expose an aggregate KPI
view — only per-decision numbers (see DecisionCard / HistoryTimeline). This
module is notebook-only: it aggregates the exact same per-decision fields
`ra_core.decision_engine.evaluate` already produces (expected_kwh,
expected_value_egp, co2_avoided_kg), so nothing here is a new/independent
calculation — it's a sum over numbers the engine already outputs.
"""
from ra_core.config import INTERVAL_MINUTES

_DT_HOURS = INTERVAL_MINUTES / 60


def total_available_surplus_kwh(readings: list[dict], start_idx: int, end_idx: int) -> float:
    """Sum of positive (generation - demand) over [start_idx, end_idx], in kWh."""
    total = 0.0
    for r in readings[start_idx: end_idx + 1]:
        surplus = r["solar_kw"] + r["wind_kw"] - r["demand_kw"]
        if surplus > 0:
            total += surplus * _DT_HOURS
    return total


def summarize(decisions: list[dict], available_surplus_kwh: float) -> dict:
    """decisions: list of dicts shaped like decision_engine's action records
    (action, expected_kwh, expected_value_egp, co2_avoided_kg).
    `curtail` actions always carry expected_kwh == 0, so summing expected_kwh
    across logged decisions is exactly the surplus that was *not* curtailed.
    """
    managed_kwh = sum(d["expected_kwh"] for d in decisions)
    total_value_egp = sum(d["expected_value_egp"] for d in decisions)
    total_co2_kg = sum(d["co2_avoided_kg"] for d in decisions)
    utilization_pct = (managed_kwh / available_surplus_kwh * 100) if available_surplus_kwh > 0 else 0.0
    return {
        "decisions_logged": len(decisions),
        "renewable_utilization_pct": round(min(utilization_pct, 100.0), 1),
        "curtailment_avoided_kwh": round(managed_kwh, 1),
        "total_value_egp": round(total_value_egp, 1),
        "total_co2_avoided_kg": round(total_co2_kg, 1),
    }
