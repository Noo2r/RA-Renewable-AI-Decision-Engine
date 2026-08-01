"""RA's core decision engine.

Given the current site state and a short-horizon forecast, scores each
candidate action for the current surplus (or deficit) by expected economic
value + environmental value, then produces a plain-language explanation of
the top recommendation. This is deliberately a transparent, template-driven
scoring model (not a black box) so every number in the explanation traces
back to a feature the judge/user can see on the dashboard.

Part 3 -- surplus AND deficit:

  mode = "surplus" if the near-term forecast net balance (generation -
  demand) is >= 0, else "deficit". Surplus mode ranks the original four
  actions (battery_charge, water_pumping, sell_grid, curtail) exactly as
  before. Deficit mode ranks exactly two actions (battery_discharge,
  grid_import). One deliberate Part 3 change: mode is decided from the
  near-term forecast average, not the instantaneous reading -- see
  evaluate()'s docstring for why.

  Decision interval: unchanged from Part 0 -- PLANNING_HOURS = 1.0 (one
  hour), exposed explicitly as decision_interval_minutes = 60. This is NOT
  the simulator's 15-minute reading interval (ra_core.config.INTERVAL_MINUTES);
  it is the dispatch engine's own, separate planning horizon, and was
  already the existing time basis before Part 3 -- preserved unchanged, per
  Part 3 Step 1.

  This is a recommendation/decision-support system: it never mutates
  station state or issues real control commands. "before"/"after" describe
  the *projected* effect of following the recommendation, nothing more.
"""
from ra_core.config import (
    BATTERY_CAPACITY_KWH,
    BATTERY_CHARGE_EFFICIENCY,
    BATTERY_DISCHARGE_EFFICIENCY,
    GRID_CO2_FACTOR_KG_PER_KWH,
    WATER_PUMP_CAPACITY_KW,
    WATER_PUMP_VALUE_EGP_PER_KWH,
)

CO2_SHADOW_PRICE_EGP_PER_KG = 0.3  # environmental value folded into ranking score
PLANNING_HOURS = 1.0  # dispatch actions are evaluated over the next hour (unchanged since Part 0)
DECISION_INTERVAL_MINUTES = int(PLANNING_HOURS * 60)  # = 60; exposed explicitly (Part 3 Step 8)

MIN_ACTION_KWH = 0.05  # ignore actions smaller than this (float noise, not a real recommendation)

# Backward-compatible defaults for callers that don't pass station battery
# fields (e.g. old tests, or any future caller with no StationConfig on
# hand). battery_max_soc_pct=95.0 matches the previous hardcoded threshold
# exactly, so surplus-mode behavior for existing callers is unchanged.
DEFAULT_BATTERY_MIN_SOC_PCT = 10.0
DEFAULT_BATTERY_MAX_SOC_PCT = 95.0

# Priority thresholds (Part 3 Step 10) -- deterministic, rule-based, no ML.
DEFICIT_CRITICAL_RATIO = 0.30   # remaining deficit >= 30% of demand -> critical
SURPLUS_SIGNIFICANT_RATIO = 0.50  # surplus >= 50% of demand -> "medium" (needs decisive allocation)


def _avg(values, default=0.0):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else default


def _action(name, kwh, value_egp, co2_kg, explanation, *, amount_kw=None,
            expected_cost_egp=0.0, co2_emitted_kg=0.0, reason="",
            projected_battery_soc_pct=None) -> dict:
    """Shared action-record builder. Every action -- surplus or deficit --
    gets the same flat shape: the original (Part 0) fields plus a few
    additive Part 3 fields (amount_kw, expected_cost_egp, co2_emitted_kg,
    reason, projected_battery_soc_pct), so a consumer never has to
    special-case which mode produced the record. expected_cost_egp/
    co2_emitted_kg default to 0.0 for actions that don't cost money or emit
    anything (mirrors expected_value_egp/co2_avoided_kg defaulting to 0.0
    for curtail today). projected_battery_soc_pct is the SoC *this specific
    action* would leave the battery at -- None means "unchanged" (the
    action doesn't touch the battery), resolved against the current SoC by
    the caller building the top-level "after" block.
    """
    score = value_egp + co2_kg * CO2_SHADOW_PRICE_EGP_PER_KG - expected_cost_egp
    if amount_kw is None:
        amount_kw = kwh / PLANNING_HOURS if PLANNING_HOURS else 0.0
    return {
        "action": name,
        "expected_kwh": round(kwh, 2),
        "amount_kw": round(amount_kw, 2),
        "expected_value_egp": round(value_egp, 2),
        "co2_avoided_kg": round(co2_kg, 2),
        "expected_cost_egp": round(expected_cost_egp, 2),
        "co2_emitted_kg": round(co2_emitted_kg, 2),
        "score": round(score, 2),
        "reason": reason,
        "explanation": explanation,
        "projected_battery_soc_pct": (
            None if projected_battery_soc_pct is None else round(projected_battery_soc_pct, 1)
        ),
    }


def _priority(mode: str, remaining_deficit_kw: float, demand_kw: float, surplus_kw: float,
              grid_needed: bool = False) -> str:
    """Deterministic, rule-based priority -- no ML, no health/failure scoring.

    Deficit:
      remaining_deficit_kw > 0 and remaining/demand >= DEFICIT_CRITICAL_RATIO -> "critical"
      remaining_deficit_kw > 0 (below that ratio)                             -> "high"
      remaining_deficit_kw <= 0 and grid_needed (grid_import was the primary
        recommendation because the battery was infeasible, even though it
        "fully covers" the deficit by definition)                            -> "high"
      remaining_deficit_kw <= 0 and not grid_needed (battery alone covered it) -> "medium"
    Surplus:
      surplus_kw/demand >= SURPLUS_SIGNIFICANT_RATIO (a big surplus needing
        decisive allocation)                                                  -> "medium"
      otherwise                                                               -> "normal"
    """
    demand_ref = max(demand_kw, 1e-6)
    if mode == "deficit":
        if remaining_deficit_kw > MIN_ACTION_KWH:
            ratio = remaining_deficit_kw / demand_ref
            return "critical" if ratio >= DEFICIT_CRITICAL_RATIO else "high"
        return "high" if grid_needed else "medium"
    ratio = surplus_kw / demand_ref
    return "medium" if ratio >= SURPLUS_SIGNIFICANT_RATIO else "normal"


def evaluate(
    current: dict,
    forecast_points: list[dict],
    future_prices: list[float],
    battery_capacity_kwh: float = BATTERY_CAPACITY_KWH,
    battery_charge_limit_kw: float | None = None,
    battery_discharge_limit_kw: float | None = None,
    battery_min_soc_pct: float = DEFAULT_BATTERY_MIN_SOC_PCT,
    battery_max_soc_pct: float = DEFAULT_BATTERY_MAX_SOC_PCT,
    battery_charge_efficiency: float = BATTERY_CHARGE_EFFICIENCY,
    battery_discharge_efficiency: float = BATTERY_DISCHARGE_EFFICIENCY,
) -> dict:
    """battery_capacity_kwh (and the other battery_* kwargs) default to the
    original single-station constants for full backward compatibility;
    multi-station callers should pass the requested station's configured
    values. battery_charge_limit_kw/battery_discharge_limit_kw default to
    None, which resolves to battery_capacity_kwh (a permissive 1C-ish rate)
    -- this exactly reproduces the pre-Part-3 behavior, which had no
    explicit rate limit, for any caller that doesn't pass one.

    Mode is decided from the near-term forecast average net balance (the
    same `avg_surplus_next_hour` quantity the engine already computed for
    surplus scoring), not the raw instantaneous reading -- Part 3 Step 2
    asks for the *predicted* net balance to decide mode. The instantaneous
    reading is still what "before" reports (it's the actual current state).
    """
    charge_limit_kw = battery_charge_limit_kw if battery_charge_limit_kw is not None else battery_capacity_kwh
    discharge_limit_kw = battery_discharge_limit_kw if battery_discharge_limit_kw is not None else battery_capacity_kwh

    surplus_kw = current["solar_kw"] + current["wind_kw"] - current["demand_kw"]
    battery_soc = current["battery_soc"]
    price_now = current["price_egp"]
    generation_kw = current["solar_kw"] + current["wind_kw"]
    demand_kw = current["demand_kw"]

    near_term = forecast_points[:4] if forecast_points else []
    avg_surplus_next_hour = _avg([p["forecast_surplus_kw"] for p in near_term], default=surplus_kw)
    avg_future_price = _avg(future_prices, default=price_now)
    price_rising = avg_future_price > price_now * 1.03

    mode = "surplus" if avg_surplus_next_hour >= 0 else "deficit"

    before = {
        "generation_kw": round(generation_kw, 2),
        "demand_kw": round(demand_kw, 2),
        "net_balance_kw": round(surplus_kw, 2),
        "battery_soc_pct": round(battery_soc, 1),
    }

    if mode == "surplus":
        actions = _surplus_actions(
            surplus_kw, avg_surplus_next_hour, battery_soc, battery_capacity_kwh,
            charge_limit_kw, battery_max_soc_pct, battery_charge_efficiency,
            price_now, avg_future_price, price_rising,
        )
    else:
        actions = _deficit_actions(
            avg_surplus_next_hour, battery_soc, battery_capacity_kwh,
            discharge_limit_kw, battery_min_soc_pct, battery_discharge_efficiency,
            price_now, generation_kw, demand_kw,
        )

    actions.sort(key=lambda a: a["score"], reverse=True)
    recommended = actions[0]

    after = _project_after(recommended, before, avg_surplus_next_hour)
    remaining_deficit_kw, secondary_action, secondary_amount_kw = _secondary_plan(
        mode, recommended, avg_surplus_next_hour,
    )
    grid_needed = mode == "deficit" and (recommended["action"] == "grid_import" or secondary_action == "grid_import")
    priority = _priority(mode, remaining_deficit_kw, demand_kw, surplus_kw, grid_needed=grid_needed)

    return {
        "timestamp": current["timestamp"],
        "mode": mode,
        "surplus_kw": round(surplus_kw, 2),
        "net_balance_kw": round(surplus_kw, 2),  # clearer additive alias, same value
        "avg_surplus_next_hour_kw": round(avg_surplus_next_hour, 2),
        "price_now_egp": round(price_now, 3),
        "avg_future_price_egp": round(avg_future_price, 3),
        "battery_soc": round(battery_soc, 1),
        "decision_interval_minutes": DECISION_INTERVAL_MINUTES,
        "priority": priority,
        "before": before,
        "after": after,
        "remaining_deficit_kw": round(remaining_deficit_kw, 2),
        "secondary_action": secondary_action,
        "secondary_amount_kw": round(secondary_amount_kw, 2),
        "ranked_actions": actions,
        "recommended": recommended,
    }


# ---------------------------------------------------------------------------
# Surplus mode (unchanged action set: battery_charge, water_pumping,
# sell_grid, curtail)
# ---------------------------------------------------------------------------

def _surplus_actions(surplus_kw, avg_surplus_next_hour, battery_soc, battery_capacity_kwh,
                      charge_limit_kw, max_soc_pct, charge_efficiency,
                      price_now, avg_future_price, price_rising) -> list[dict]:
    actions = []

    # --- battery_charge ----------------------------------------------------
    # Physically-constrained input energy (Part 3 Step 6): capped by
    # available surplus, the charge-rate limit, and remaining storage
    # capacity (accounting for charge efficiency so projected SoC never
    # exceeds max_soc_pct). expected_kwh reports the STORED (post-
    # efficiency) energy -- the amount actually available later -- which is
    # what the explanation's "avoids buying it back later" reasoning needs.
    if surplus_kw > 0 and battery_soc < max_soc_pct and battery_capacity_kwh > 0:
        available_capacity_kwh = battery_capacity_kwh * (max_soc_pct - battery_soc) / 100
        max_input_by_rate = charge_limit_kw * PLANNING_HOURS
        max_input_by_surplus = max(0.0, avg_surplus_next_hour) * PLANNING_HOURS
        max_input_by_capacity = (available_capacity_kwh / charge_efficiency) if charge_efficiency > 0 else 0.0
        charge_input_kwh = min(max_input_by_rate, max_input_by_surplus, max_input_by_capacity)
        stored_kwh = charge_input_kwh * charge_efficiency
        if stored_kwh > MIN_ACTION_KWH:
            projected_soc = battery_soc + (stored_kwh / battery_capacity_kwh) * 100
            value = stored_kwh * avg_future_price
            co2 = stored_kwh * GRID_CO2_FACTOR_KG_PER_KWH
            trend = "rising" if price_rising else "flat or falling"
            explanation = (
                f"Surplus of {surplus_kw:.1f} kW is forecast to continue (avg "
                f"{avg_surplus_next_hour:.1f} kW over the next hour). Battery is at "
                f"{battery_soc:.0f}% state of charge with room to store "
                f"{stored_kwh:.1f} kWh before reaching its {max_soc_pct:.0f}% maximum. "
                f"Grid price is currently {price_now:.2f} EGP/kWh and trending {trend} "
                f"(avg {avg_future_price:.2f} EGP/kWh over the next few hours). Storing "
                f"{stored_kwh:.1f} kWh now avoids buying it back later, saving an estimated "
                f"{value:.1f} EGP and avoiding {co2:.1f} kg CO2 of grid generation."
            )
            actions.append(_action(
                "battery_charge", stored_kwh, value, co2, explanation,
                amount_kw=charge_input_kwh / PLANNING_HOURS,
                reason="Renewable generation is predicted to exceed demand.",
                projected_battery_soc_pct=projected_soc,
            ))

    # --- water_pumping (flexible load) -----------------------------------
    pump_kw = min(max(surplus_kw, 0.0), WATER_PUMP_CAPACITY_KW)
    pump_kwh = pump_kw * PLANNING_HOURS
    if surplus_kw > 1.0 and pump_kwh > 0.1:
        value = pump_kwh * WATER_PUMP_VALUE_EGP_PER_KWH
        co2 = pump_kwh * GRID_CO2_FACTOR_KG_PER_KWH
        explanation = (
            f"There is {surplus_kw:.1f} kW of immediate surplus, enough to run the water "
            f"pumping/desalination load (rated {WATER_PUMP_CAPACITY_KW:.0f} kW) at "
            f"{pump_kw:.1f} kW. Using {pump_kwh:.1f} kWh of otherwise-wasted surplus for "
            f"pumping is worth an estimated {value:.1f} EGP in produced water value and "
            f"avoids {co2:.1f} kg CO2 versus running the pump from the grid later."
        )
        actions.append(_action(
            "water_pumping", pump_kwh, value, co2, explanation,
            reason="Renewable generation is predicted to exceed demand.",
        ))

    # --- sell_grid ---------------------------------------------------------
    sell_kwh = max(surplus_kw, 0.0) * PLANNING_HOURS
    if surplus_kw > 0 and sell_kwh > 0.05:
        value = sell_kwh * price_now
        co2 = sell_kwh * GRID_CO2_FACTOR_KG_PER_KWH
        explanation = (
            f"Exporting the current {surplus_kw:.1f} kW surplus to the grid at today's "
            f"spot price of {price_now:.2f} EGP/kWh yields an estimated {value:.1f} EGP for "
            f"{sell_kwh:.1f} kWh, while displacing {co2:.1f} kg CO2 of fossil generation "
            f"elsewhere on the grid."
        )
        actions.append(_action(
            "sell_grid", sell_kwh, value, co2, explanation,
            reason="Renewable generation is predicted to exceed demand.",
        ))

    # --- curtail (fallback, always feasible in surplus mode) ----------------
    # Mode is decided from the near-term forecast average (Part 3 Step 2),
    # so it's possible for mode to be "surplus" while the instantaneous
    # reading is momentarily a small deficit (the forecast expects things
    # to turn around shortly). Word the explanation honestly for that case
    # rather than claiming a "surplus" is being wasted when there isn't one
    # right now.
    if surplus_kw > 0:
        wasted_kwh = surplus_kw * PLANNING_HOURS
        explanation = (
            f"Curtailing means the {surplus_kw:.1f} kW surplus ({wasted_kwh:.1f} kWh over "
            f"the next hour) goes unused. This is only recommended when storage, flexible "
            f"load, and grid export are all unavailable or uneconomical."
        )
    else:
        explanation = (
            f"The near-term forecast still averages a net surplus, but the current reading "
            f"shows a momentary {-surplus_kw:.1f} kW shortfall (generation is briefly below "
            f"demand). There is nothing to store, pump, or sell right now -- RA will "
            f"reassess as new readings arrive."
        )
    actions.append(_action(
        "curtail", 0.0, 0.0, 0.0, explanation,
        amount_kw=0.0, reason="Renewable generation is predicted to exceed demand.",
    ))

    return actions


# ---------------------------------------------------------------------------
# Deficit mode (Part 3 -- exactly two actions: battery_discharge, grid_import)
# ---------------------------------------------------------------------------

def _deficit_actions(avg_surplus_next_hour, battery_soc, battery_capacity_kwh,
                      discharge_limit_kw, min_soc_pct, discharge_efficiency,
                      price_now, generation_kw, demand_kw) -> list[dict]:
    deficit_kw = max(0.0, -avg_surplus_next_hour)
    deficit_kwh = deficit_kw * PLANNING_HOURS
    actions = []
    reason = "Demand is predicted to exceed renewable generation."

    # --- battery_discharge ---------------------------------------------
    # Feasible only when: a battery exists, capacity > 0, SoC above the
    # configured minimum, a deficit actually exists, and deliverable power
    # (after efficiency losses) is > 0 (Part 3 Step 4/7).
    delivered_kwh = 0.0
    if battery_capacity_kwh > 0 and battery_soc > min_soc_pct and deficit_kwh > 0:
        usable_stored_kwh = battery_capacity_kwh * (battery_soc - min_soc_pct) / 100
        max_removed_by_rate = discharge_limit_kw * PLANNING_HOURS
        max_energy_removed = min(usable_stored_kwh, max_removed_by_rate)
        deliverable_kwh = max_energy_removed * discharge_efficiency
        if deliverable_kwh > MIN_ACTION_KWH:
            delivered_kwh = min(deficit_kwh, deliverable_kwh)
            energy_removed_kwh = delivered_kwh / discharge_efficiency if discharge_efficiency > 0 else 0.0
            projected_soc = battery_soc - (energy_removed_kwh / battery_capacity_kwh) * 100
            remaining_kwh = deficit_kwh - delivered_kwh

            value = delivered_kwh * price_now  # avoided grid purchase
            co2 = delivered_kwh * GRID_CO2_FACTOR_KG_PER_KWH  # avoided grid emissions

            explanation = (
                f"RA predicts a {deficit_kw:.1f} kW deficit during the next decision "
                f"interval (generation {generation_kw:.1f} kW against {demand_kw:.1f} kW "
                f"of demand). The battery is at {battery_soc:.0f}% state of charge and can "
                f"safely deliver {delivered_kwh / PLANNING_HOURS:.1f} kW without dropping "
                f"below its {min_soc_pct:.0f}% minimum SoC (projected to {projected_soc:.0f}% "
                f"after discharge). RA recommends discharging the battery by "
                f"{delivered_kwh / PLANNING_HOURS:.1f} kW, avoiding an estimated {value:.1f} "
                f"EGP in grid purchases and {co2:.1f} kg of CO2."
            )
            if remaining_kwh > MIN_ACTION_KWH:
                explanation += (
                    f" A remaining {remaining_kwh / PLANNING_HOURS:.1f} kW deficit should be "
                    f"supplied by the grid."
                )
            else:
                explanation += " This fully covers the predicted deficit."

            actions.append(_action(
                "battery_discharge", delivered_kwh, value, co2, explanation,
                amount_kw=delivered_kwh / PLANNING_HOURS, reason=reason,
                projected_battery_soc_pct=projected_soc,
            ))

    # --- grid_import (final fallback; always feasible while a deficit exists) --
    if deficit_kwh > 0:
        cost = deficit_kwh * price_now
        co2_emitted = deficit_kwh * GRID_CO2_FACTOR_KG_PER_KWH
        if delivered_kwh > MIN_ACTION_KWH:
            explanation = (
                f"Importing the full {deficit_kw:.1f} kW deficit from the grid (instead of "
                f"discharging the battery) would cost an estimated {cost:.1f} EGP and emit "
                f"{co2_emitted:.1f} kg of CO2 -- shown here for comparison; RA prefers "
                f"discharging the battery first because it avoids this cost and these "
                f"emissions."
            )
        else:
            battery_reason = (
                "no battery is configured at this station" if battery_capacity_kwh <= 0
                else f"the battery is at or below its {min_soc_pct:.0f}% minimum state of "
                     f"charge and cannot be discharged further"
            )
            explanation = (
                f"RA predicts a {deficit_kw:.1f} kW deficit (generation {generation_kw:.1f} kW "
                f"against {demand_kw:.1f} kW of demand), and {battery_reason}. RA recommends "
                f"importing {deficit_kw:.1f} kW from the grid at {price_now:.2f} EGP/kWh, an "
                f"estimated cost of {cost:.1f} EGP and {co2_emitted:.1f} kg of CO2 emitted."
            )
        actions.append(_action(
            "grid_import", deficit_kwh, -cost, 0.0, explanation,
            amount_kw=deficit_kw, expected_cost_egp=cost, co2_emitted_kg=co2_emitted,
            reason=reason,
        ))

    return actions


# ---------------------------------------------------------------------------
# Shared post-processing: projected after-state + secondary-action plan
# ---------------------------------------------------------------------------

def _project_after(recommended: dict, before: dict, avg_surplus_next_hour: float) -> dict:
    """Projected (not actually executed) state if the recommendation were
    followed. Every action's amount_kw was sized from the near-term
    forecast average (avg_surplus_next_hour), the same quantity used to
    decide mode -- so "after" is computed relative to that same reference,
    not the instantaneous "before" reading, to keep the arithmetic
    internally consistent (before/after can therefore differ from a naive
    before-minus-amount if the instantaneous reading and the forecast
    average aren't identical; before still reports the actual current
    reading, which is its own useful, distinct piece of information).
    net_balance_kw moves toward zero by the action's amount_kw (surplus
    actions consume surplus; battery_discharge offsets a deficit);
    curtail/grid_import leave nothing outstanding to report by definition,
    so their net_balance_kw is 0. battery_soc_pct comes from the action's
    own projected_battery_soc_pct when it touches the battery, else it's
    unchanged from "before".
    """
    action_name = recommended["action"]
    amount_kw = recommended["amount_kw"]
    soc = recommended["projected_battery_soc_pct"]
    if soc is None:
        soc = before["battery_soc_pct"]

    if action_name == "grid_import":
        net = 0.0
    elif action_name == "curtail":
        # Only zero out if there was an actual positive surplus being
        # wasted; if curtail was recommended while the forecast average is
        # a small positive surplus that hasn't materialized instantaneously
        # yet, nothing was actually curtailed, so the state is unchanged.
        net = 0.0 if avg_surplus_next_hour > 0 else avg_surplus_next_hour
    elif action_name == "battery_discharge":
        net = avg_surplus_next_hour + amount_kw
    else:  # battery_charge, water_pumping, sell_grid
        net = avg_surplus_next_hour - amount_kw

    return {"net_balance_kw": round(net, 2), "battery_soc_pct": round(soc, 1)}


def _secondary_plan(mode: str, recommended: dict, avg_surplus_next_hour: float):
    if mode != "deficit":
        return 0.0, None, 0.0

    deficit_kwh = max(0.0, -avg_surplus_next_hour) * PLANNING_HOURS
    if recommended["action"] == "battery_discharge":
        remaining_kwh = max(0.0, deficit_kwh - recommended["expected_kwh"])
        remaining_kw = remaining_kwh / PLANNING_HOURS
        if remaining_kw > MIN_ACTION_KWH:
            return remaining_kw, "grid_import", remaining_kw
        return 0.0, None, 0.0

    # recommended is grid_import itself (battery infeasible) -- it already
    # covers the full deficit on its own, so there's no secondary action.
    return 0.0, None, 0.0
