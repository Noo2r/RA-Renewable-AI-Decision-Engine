"""Part 6 tests: ra_core.assistant -- deterministic intent classifier and
grounded answer generation."""
import re

import pytest

from ra_core.assistant import (
    AssistantContext,
    answer_question,
    classify_intent,
    is_control_request,
)
from ra_core.data_generator import generate_series
from ra_core.decision_engine import evaluate, status_from_priority, STATUS_LABELS
from ra_core.forecasting import forecast_surplus
from ra_core.stations import get_station, list_stations
from ra_core.what_if import simulate_what_if

STATION_ID = "hybrid-01"
SCENARIO = "sunny"
INDEX = 136


def _build_full_context(what_if=None):
    station = get_station(STATION_ID)
    df = generate_series(SCENARIO, station_id=station.id)
    reading = df.iloc[INDEX].to_dict()
    all_rows = df.to_dict("records")
    future_rows = all_rows[INDEX + 1: INDEX + 13]
    fc = forecast_surplus(all_rows, INDEX, station_id=station.id)
    future_prices = [r["price_egp"] for r in future_rows]
    decision = evaluate(
        reading, fc["forecast"], future_prices,
        battery_capacity_kwh=station.battery_capacity_kwh,
        battery_charge_limit_kw=station.battery_charge_limit_kw,
        battery_discharge_limit_kw=station.battery_discharge_limit_kw,
        battery_min_soc_pct=station.battery_min_soc_pct,
        battery_max_soc_pct=station.battery_max_soc_pct,
        battery_charge_efficiency=station.battery_charge_efficiency,
        battery_discharge_efficiency=station.battery_discharge_efficiency,
    )
    current_state = {
        "generation_kw": round(reading["solar_kw"] + reading["wind_kw"], 2),
        "demand_kw": round(reading["demand_kw"], 2),
        "net_balance_kw": round(reading["solar_kw"] + reading["wind_kw"] - reading["demand_kw"], 2),
        "battery_soc_pct": round(reading["battery_soc"], 1),
    }

    overview = []
    for s in list_stations():
        df_s = generate_series(SCENARIO, station_id=s.id)
        rows_s = df_s.to_dict("records")
        reading_s = rows_s[INDEX]
        future_rows_s = rows_s[INDEX + 1: INDEX + 13]
        fc_s = forecast_surplus(rows_s, INDEX, station_id=s.id)
        prices_s = [r["price_egp"] for r in future_rows_s]
        result_s = evaluate(
            reading_s, fc_s["forecast"], prices_s,
            battery_capacity_kwh=s.battery_capacity_kwh,
            battery_charge_limit_kw=s.battery_charge_limit_kw,
            battery_discharge_limit_kw=s.battery_discharge_limit_kw,
            battery_min_soc_pct=s.battery_min_soc_pct,
            battery_max_soc_pct=s.battery_max_soc_pct,
            battery_charge_efficiency=s.battery_charge_efficiency,
            battery_discharge_efficiency=s.battery_discharge_efficiency,
        )
        status = status_from_priority(result_s["priority"])
        overview.append({
            "station_id": s.id, "name": s.name, "energy_type": s.energy_type,
            "generation_kw": round(reading_s["solar_kw"] + reading_s["wind_kw"], 2),
            "demand_kw": round(reading_s["demand_kw"], 2),
            "net_balance_kw": result_s["net_balance_kw"],
            "battery_soc_pct": round(reading_s["battery_soc"], 1),
            "mode": result_s["mode"], "priority": result_s["priority"],
            "recommended_action": result_s["recommended"]["action"],
            "status": status, "status_label": STATUS_LABELS.get(status, "Unknown"),
        })

    return AssistantContext(
        station_id=station.id, station_name=station.name, energy_type=station.energy_type,
        scenario=SCENARIO, current_index=INDEX, timestamp=reading["timestamp"],
        current_state=current_state, forecast=fc, decision=decision,
        stations_overview=overview, what_if=what_if,
    )


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "What is happening now?",
    "How is this station performing?",
    "What is the current status?",
])
def test_classifier_status_questions(question):
    assert classify_intent(question) == "explain_current_status"


@pytest.mark.parametrize("question", [
    "What is expected during the next six hours?",
    "What will happen later today?",
    "What is the energy forecast?",
])
def test_classifier_forecast_questions(question):
    assert classify_intent(question) == "explain_forecast"


@pytest.mark.parametrize("question", [
    "Why did RA choose battery discharge?",
    "Why is grid support recommended?",
    "Why was this decision selected?",
])
def test_classifier_decision_questions(question):
    assert classify_intent(question) == "explain_decision"


@pytest.mark.parametrize("question", [
    "Which station needs attention?",
    "Which station has the highest priority?",
    "Compare the three stations.",
])
def test_classifier_compare_questions(question):
    assert classify_intent(question) == "compare_stations"


@pytest.mark.parametrize("question", [
    "What changed in the simulation?",
    "Why did the recommendation change?",
    "What was the impact of increasing solar capacity?",
    "What changed in the latest What-If simulation?",
])
def test_classifier_what_if_questions(question):
    assert classify_intent(question) == "explain_what_if"


@pytest.mark.parametrize("question", [
    "What can I ask?",
    "Help",
    "What do you understand?",
])
def test_classifier_help_questions(question):
    assert classify_intent(question) == "help"


@pytest.mark.parametrize("question", [
    "Why is the sky blue?",
    "What is the weather in Cairo tomorrow?",
    "Write me a poem about the ocean.",
    "What is 2 + 2?",
    "Tell me a joke.",
])
def test_classifier_out_of_scope_questions(question):
    assert classify_intent(question) == "out_of_scope"


def test_classifier_is_case_insensitive():
    assert classify_intent("WHAT IS HAPPENING NOW?") == "explain_current_status"
    assert classify_intent("wHaT iS HaPpEnInG nOw?") == "explain_current_status"


def test_classifier_handles_punctuation():
    assert classify_intent("What is happening now?!?") == "explain_current_status"
    assert classify_intent("what-if... simulation??") == "explain_what_if"
    assert classify_intent("Which station, exactly, needs attention???") == "compare_stations"


@pytest.mark.parametrize("question", ["", "   ", "\n\t", None])
def test_classifier_handles_empty_input(question):
    assert classify_intent(question) == "out_of_scope"


def test_classifier_returns_only_documented_values():
    from ra_core.assistant import INTENTS, OUT_OF_SCOPE
    allowed = set(INTENTS) | {OUT_OF_SCOPE}
    sample_questions = [
        "What is happening now?", "forecast please", "why", "compare",
        "simulate this", "help me", "asdkjaslkdj", "", "Discharge now",
    ]
    for q in sample_questions:
        assert classify_intent(q) in allowed


def test_control_request_detection():
    assert is_control_request("Discharge the battery now.") is True
    assert is_control_request("Turn off the pump.") is True
    assert is_control_request("Why did RA choose battery discharge?") is False
    assert is_control_request("What is happening now?") is False


def test_control_request_is_classified_out_of_scope():
    assert classify_intent("Discharge the battery now.") == "out_of_scope"
    assert classify_intent("Sell to the grid immediately.") == "out_of_scope"


# ---------------------------------------------------------------------------
# Grounded answers
# ---------------------------------------------------------------------------

def test_status_answer_uses_actual_state_values():
    context = _build_full_context()
    result = answer_question("What is happening now?", context)
    assert result["intent"] == "explain_current_status"
    cs = context.current_state
    assert f"{cs['generation_kw']:.1f}" in result["answer"]
    assert f"{cs['demand_kw']:.1f}" in result["answer"]


def test_forecast_answer_uses_actual_forecast_values():
    context = _build_full_context()
    result = answer_question("What is expected during the next six hours?", context)
    assert result["intent"] == "explain_forecast"
    last_point = context.forecast["forecast"][-1]
    assert f"{last_point['net_balance_kw']:.1f}" in result["answer"]


def test_decision_answer_preserves_the_selected_recommendation():
    context = _build_full_context()
    result = answer_question("Why was this decision selected?", context)
    assert result["intent"] == "explain_decision"
    # The decision engine's own explanation text must be used verbatim
    # (not independently re-derived) -- the answer generator never picks a
    # different action than context.decision["recommended"].
    assert context.decision["recommended"]["explanation"] in result["answer"]
    action_fact = next(f for f in result["facts"] if f["label"] == "Recommended Action")
    from ra_core.assistant import _label
    assert action_fact["value"] == _label(context.decision["recommended"]["action"])


def test_compare_answer_uses_all_three_station_overviews():
    context = _build_full_context()
    result = answer_question("Which station needs attention?", context)
    assert result["intent"] == "compare_stations"
    for s in context.stations_overview:
        assert s["station_id"] in result["answer"]


def test_compare_answer_does_not_use_health_or_failure_terminology():
    context = _build_full_context()
    result = answer_question("Which station needs attention?", context)
    forbidden = ["health", "failure", "broken", "malfunction", "diagnos"]
    lowered = result["answer"].lower()
    for word in forbidden:
        assert word not in lowered


def test_what_if_answer_uses_regenerated_simulation_results():
    what_if = simulate_what_if(STATION_ID, SCENARIO, INDEX, solar_capacity_change_pct=20, battery_capacity_change_pct=50)
    context = _build_full_context(what_if=what_if)
    result = answer_question("What changed in the simulation?", context)
    assert result["intent"] == "explain_what_if"
    assert what_if["explanation"] == result["answer"]
    assert result["grounding"]["what_if_included"] is True


def test_what_if_without_inputs_asks_user_to_run_a_simulation():
    context = _build_full_context(what_if=None)
    result = answer_question("What changed in the simulation?", context)
    assert result["intent"] == "explain_what_if"
    assert result["answer"] == "Run a What-If simulation first, then I can explain its impact."
    assert result["facts"] == []
    assert result["grounding"]["what_if_included"] is False


def test_missing_data_handled_without_invention():
    station = get_station(STATION_ID)
    bare_context = AssistantContext(
        station_id=station.id, station_name=station.name, energy_type=station.energy_type,
        scenario=SCENARIO, current_index=INDEX, timestamp="2026-07-02T10:00:00",
        current_state=None, forecast=None, decision=None, stations_overview=None, what_if=None,
    )
    for question in [
        "What is happening now?", "What is expected during the next six hours?",
        "Why was this decision selected?", "Which station needs attention?",
        "What changed in the simulation?",
    ]:
        result = answer_question(question, bare_context)
        assert result["facts"] == []
        assert result["answer"]  # a clear "no data" sentence, never a crash
        # No fabricated numeric kW figure anywhere in the "no data" message.
        assert re.search(r"\d+(\.\d+)?\s*kw", result["answer"], re.IGNORECASE) is None


def test_answers_are_deterministic():
    context = _build_full_context()
    r1 = answer_question("What is happening now?", context)
    r2 = answer_question("What is happening now?", context)
    assert r1 == r2


# ---------------------------------------------------------------------------
# Facts and metadata
# ---------------------------------------------------------------------------

def test_facts_contain_valid_labels_and_units():
    context = _build_full_context()
    result = answer_question("What is happening now?", context)
    assert 1 <= len(result["facts"]) <= 6
    for fact in result["facts"]:
        assert set(fact.keys()) == {"label", "value", "unit"}
        assert isinstance(fact["label"], str) and fact["label"]
        assert fact["unit"] is None or isinstance(fact["unit"], str)


def test_facts_correspond_to_context():
    context = _build_full_context()
    result = answer_question("What is happening now?", context)
    fact_values = {f["label"]: f["value"] for f in result["facts"]}
    assert fact_values["Generation"] == context.current_state["generation_kw"]
    assert fact_values["Battery SoC"] == context.current_state["battery_soc_pct"]


def test_grounding_station_scenario_index_are_correct():
    context = _build_full_context()
    result = answer_question("What is happening now?", context)
    g = result["grounding"]
    assert g["station_id"] == context.station_id
    assert g["scenario"] == context.scenario
    assert g["current_index"] == context.current_index
    assert g["timestamp"] == context.timestamp


def test_what_if_grounding_marked_correctly():
    what_if = simulate_what_if(STATION_ID, SCENARIO, INDEX, demand_change_pct=10)
    with_wi = _build_full_context(what_if=what_if)
    without_wi = _build_full_context(what_if=None)
    assert answer_question("What is happening now?", with_wi)["grounding"]["what_if_included"] is True
    assert answer_question("What is happening now?", without_wi)["grounding"]["what_if_included"] is False


def test_offline_mode_is_reported_correctly():
    context = _build_full_context()
    result = answer_question("What is happening now?", context)
    assert result["grounding"]["mode"] == "offline_deterministic"


def test_response_shape_contains_all_required_top_level_fields():
    context = _build_full_context()
    result = answer_question("Help", context)
    for key in ("intent", "station_id", "answer", "facts", "generated_from", "grounding"):
        assert key in result
