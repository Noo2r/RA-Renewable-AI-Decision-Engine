"""Aggregate KPI helpers over a sequence of logged decisions.

Note: the FastAPI/React app does not currently expose an aggregate KPI
view — only per-decision numbers (see DecisionCard / HistoryTimeline). This
module is notebook-only: it aggregates the exact same per-decision fields
`ra_core.decision_engine.evaluate` already produces (expected_kwh,
expected_value_egp, co2_avoided_kg, and, since Part 3, mode/action/
expected_cost_egp/co2_emitted_kg), so nothing here is a new/independent
calculation — it's a sum over numbers the engine already outputs.

Part 3 note: renewable_utilization_pct/curtailment_avoided_kwh are
deliberately restricted to *surplus-mode* decisions only (via
`d.get("mode", "surplus") == "surplus"`, defaulting old pre-Part-3 records
that have no "mode" field to "surplus" -- the only mode that existed then).
This preserves their original meaning exactly ("how much of the available
surplus got used instead of curtailed") rather than being diluted by
deficit-side energy flows, which are a different concept entirely and are
reported separately below.
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
    (action, expected_kwh, expected_value_egp, co2_avoided_kg, and
    optionally mode/expected_cost_egp/co2_emitted_kg since Part 3).
    `curtail` actions always carry expected_kwh == 0, so summing expected_kwh
    across *surplus-mode* logged decisions is exactly the surplus that was
    not curtailed.
    """
    surplus_decisions = [d for d in decisions if d.get("mode", "surplus") == "surplus"]
    managed_kwh = sum(d["expected_kwh"] for d in surplus_decisions)
    total_value_egp = sum(d["expected_value_egp"] for d in decisions)
    total_co2_kg = sum(d["co2_avoided_kg"] for d in decisions)
    utilization_pct = (managed_kwh / available_surplus_kwh * 100) if available_surplus_kwh > 0 else 0.0

    grid_import_kwh = sum(d["expected_kwh"] for d in decisions if d.get("action") == "grid_import")
    grid_import_cost_egp = sum(d.get("expected_cost_egp", 0.0) for d in decisions if d.get("action") == "grid_import")
    battery_discharge_kwh = sum(d["expected_kwh"] for d in decisions if d.get("action") == "battery_discharge")
    co2_emitted_kg = sum(d.get("co2_emitted_kg", 0.0) for d in decisions)

    return {
        "decisions_logged": len(decisions),
        "renewable_utilization_pct": round(min(utilization_pct, 100.0), 1),
        "curtailment_avoided_kwh": round(managed_kwh, 1),
        "total_value_egp": round(total_value_egp, 1),
        "total_co2_avoided_kg": round(total_co2_kg, 1),
        "grid_import_kwh": round(grid_import_kwh, 1),
        "grid_import_cost_egp": round(grid_import_cost_egp, 1),
        "battery_discharge_kwh": round(battery_discharge_kwh, 1),
        "co2_emitted_kg": round(co2_emitted_kg, 1),
    }
