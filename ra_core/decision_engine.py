"""RA's core decision engine.

Given the current site state and a short-horizon forecast, scores each
candidate action for the current surplus (or deficit) by expected economic
value + environmental value, then produces a plain-language explanation of
the top recommendation. This is deliberately a transparent, template-driven
scoring model (not a black box) so every number in the explanation traces
back to a feature the judge/user can see on the dashboard.
"""
from ra_core.config import (
    BATTERY_CAPACITY_KWH,
    GRID_CO2_FACTOR_KG_PER_KWH,
    WATER_PUMP_CAPACITY_KW,
    WATER_PUMP_VALUE_EGP_PER_KWH,
)

CO2_SHADOW_PRICE_EGP_PER_KG = 0.3  # environmental value folded into ranking score
PLANNING_HOURS = 1.0  # dispatch actions are evaluated over the next hour


def _avg(values, default=0.0):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else default


def evaluate(current: dict, forecast_points: list[dict], future_prices: list[float]) -> dict:
    surplus_kw = current["solar_kw"] + current["wind_kw"] - current["demand_kw"]
    battery_soc = current["battery_soc"]
    price_now = current["price_egp"]

    near_term = forecast_points[:4] if forecast_points else []
    avg_surplus_next_hour = _avg([p["forecast_surplus_kw"] for p in near_term], default=surplus_kw)
    avg_future_price = _avg(future_prices, default=price_now)
    price_rising = avg_future_price > price_now * 1.03

    actions = []

    # --- battery_charge --------------------------------------------------
    headroom_kwh = BATTERY_CAPACITY_KWH * (1 - battery_soc / 100)
    charge_kwh = max(0.0, min(avg_surplus_next_hour, BATTERY_CAPACITY_KWH)) * PLANNING_HOURS
    charge_kwh = min(charge_kwh, headroom_kwh)
    if surplus_kw > 0 and battery_soc < 95 and charge_kwh > 0.05:
        value = charge_kwh * avg_future_price
        co2 = charge_kwh * GRID_CO2_FACTOR_KG_PER_KWH
        trend = "rising" if price_rising else "flat or falling"
        explanation = (
            f"Surplus of {surplus_kw:.1f} kW is forecast to continue (avg "
            f"{avg_surplus_next_hour:.1f} kW over the next hour). Battery is at "
            f"{battery_soc:.0f}% state of charge with {headroom_kwh:.1f} kWh of headroom. "
            f"Grid price is currently {price_now:.2f} EGP/kWh and trending {trend} "
            f"(avg {avg_future_price:.2f} EGP/kWh over the next few hours). Storing "
            f"{charge_kwh:.1f} kWh now avoids buying it back later, saving an estimated "
            f"{value:.1f} EGP and avoiding {co2:.1f} kg CO2 of grid generation."
        )
        actions.append(_action("battery_charge", charge_kwh, value, co2, explanation))

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
        actions.append(_action("water_pumping", pump_kwh, value, co2, explanation))

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
        actions.append(_action("sell_grid", sell_kwh, value, co2, explanation))

    # --- curtail (fallback, always feasible) --------------------------------
    if surplus_kw > 0:
        wasted_kwh = surplus_kw * PLANNING_HOURS
        explanation = (
            f"Curtailing means the {surplus_kw:.1f} kW surplus ({wasted_kwh:.1f} kWh over "
            f"the next hour) goes unused. This is only recommended when storage, flexible "
            f"load, and grid export are all unavailable or uneconomical."
        )
        actions.append(_action("curtail", 0.0, 0.0, 0.0, explanation))
    else:
        explanation = (
            f"No surplus is currently available (generation is "
            f"{current['solar_kw'] + current['wind_kw']:.1f} kW against "
            f"{current['demand_kw']:.1f} kW of demand, a deficit of {-surplus_kw:.1f} kW). "
            f"There is nothing to store, pump, or sell right now."
        )
        actions.append(_action("curtail", 0.0, 0.0, 0.0, explanation))

    actions.sort(key=lambda a: a["score"], reverse=True)
    return {
        "timestamp": current["timestamp"],
        "surplus_kw": round(surplus_kw, 2),
        "avg_surplus_next_hour_kw": round(avg_surplus_next_hour, 2),
        "price_now_egp": round(price_now, 3),
        "avg_future_price_egp": round(avg_future_price, 3),
        "battery_soc": round(battery_soc, 1),
        "ranked_actions": actions,
        "recommended": actions[0],
    }


def _action(name: str, kwh: float, value_egp: float, co2_kg: float, explanation: str) -> dict:
    score = value_egp + co2_kg * CO2_SHADOW_PRICE_EGP_PER_KG
    return {
        "action": name,
        "expected_kwh": round(kwh, 2),
        "expected_value_egp": round(value_egp, 2),
        "co2_avoided_kg": round(co2_kg, 2),
        "score": round(score, 2),
        "explanation": explanation,
    }
