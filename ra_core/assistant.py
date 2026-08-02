"""Part 6 -- Grounded RA Assistant.

Answers natural-language questions about the CURRENT RA system state using
only structured, already-calculated context (selected station, current
reading, forecast, decision, station overview, and an optional What-If
result). It explains existing results -- it never recalculates a decision,
never invents a value, and never controls anything.

Two layers, both implemented here:

  1. classify_intent(question) -- a small deterministic, keyword/phrase
     rule-based classifier. No ML model, no embeddings, no LLM call. Given
     the same question text, it always returns the same one of exactly
     seven values: the six supported intents, or "out_of_scope".

  2. answer_question(question, context) -- builds a fully deterministic,
     grounded answer from an AssistantContext (already gathered by the
     caller from ra_core's own shared functions -- this module does no
     I/O, no database access, and no HTTP calls of its own). This is the
     MANDATORY layer; the application is fully functional with only this.

An OPTIONAL LLM wording adapter may sit on top of this module's output
(see backend/app/llm_adapter.py) to rephrase `answer` for more natural
wording. It is disabled by default, never required, and is never allowed
to change a number, a fact, or a recommendation -- only main.py's
endpoint may call it, and only after this module has already produced the
full grounded answer.
"""
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass
class AssistantContext:
    """Only the data required to answer -- gathered by the caller (backend
    endpoint or notebook) from the same shared ra_core functions/backend
    helpers already used by /state, /forecast, /decision, /stations/overview,
    and /simulate. Fields the selected intent doesn't need are left None
    (the caller is expected to avoid the expensive ones -- forecast model
    training, the 3-station overview -- when they aren't needed)."""

    station_id: str
    station_name: str
    energy_type: str
    scenario: str
    current_index: int
    timestamp: str
    current_state: dict | None = None          # {generation_kw, demand_kw, net_balance_kw, battery_soc_pct}
    forecast: dict | None = None                # full forecast_surplus() result
    decision: dict | None = None                # full evaluate() result
    stations_overview: list | None = None       # list of /stations/overview-shaped dicts
    what_if: dict | None = None                 # full simulate_what_if() result, or None


# ---------------------------------------------------------------------------
# Intent classification (deterministic, rule-based)
# ---------------------------------------------------------------------------

INTENTS = (
    "explain_current_status",
    "explain_forecast",
    "explain_decision",
    "compare_stations",
    "explain_what_if",
    "help",
)
OUT_OF_SCOPE = "out_of_scope"

_HELP_PHRASES = [
    "help", "what can i ask", "what do you understand", "what can you do",
    "how do i use you", "how does this work", "what questions",
]
_WHATIF_PHRASES = [
    "what if", "simulation", "simulate", "hypothetical", "impact of",
    "recommendation change", "did the recommendation change", "what changed",
]
_COMPARE_PHRASES = [
    "compare", "which station", "highest priority", "needs attention",
    "three stations", "station comparison", "worst station", "best station",
]
_DECISION_PHRASES = [
    "recommend", "recommendation", "decision", "selected", "chose", "choose",
    "battery discharge", "battery charge", "grid support", "grid import",
    "sell to grid", "curtail", "water pumping", "why was this",
]
_FORECAST_PHRASES = [
    "forecast", "next six hours", "next 6 hours", "later today",
    "what will happen", "energy forecast", "solar trend", "wind trend",
    "demand trend", "upcoming hours", "coming hours",
]
_STATUS_PHRASES = [
    "happening now", "happening", "current status", "how is this station",
    "performing", "status now", "right now", "current state",
    "whats going on", "hows it doing", "how is it doing",
]

# Deliberately generic-sounding decision "why" phrases are NOT keyed on the
# bare word "why" alone -- a bare "why" would over-match unrelated
# out-of-scope questions ("why is the sky blue?"). Decision intent instead
# requires a domain-specific noun/verb (recommend*, decision, selected,
# chose/choose, or one of the six action names).

_CONTROL_VERBS = {
    "discharge", "charge", "turn", "shut", "start", "stop", "activate",
    "execute", "override", "switch", "curtail", "sell", "buy", "import",
    "export", "run", "initiate", "enable", "disable", "trigger", "dispatch",
}
_QUESTION_STARTERS = {
    "what", "why", "which", "who", "when", "where", "how", "is", "are",
    "do", "does", "can", "could", "would", "will", "should", "help",
}


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)  # punctuation/hyphens -> space
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_control_request(question: str) -> bool:
    """True for imperative equipment-control phrasing ("Discharge the
    battery now.") as opposed to a question about a past/current decision
    ("Why did RA choose battery discharge?"). Deliberately narrow: the
    normalized text must both start with a known control verb AND NOT
    start with (or contain, for "?") question phrasing."""
    normalized = _normalize(question)
    if not normalized or "?" in (question or ""):
        return False
    words = normalized.split()
    if not words:
        return False
    return words[0] in _CONTROL_VERBS and words[0] not in _QUESTION_STARTERS


def classify_intent(question: str) -> str:
    """Deterministic, case-insensitive, punctuation-tolerant keyword/phrase
    matching. Always returns one of the six INTENTS values or OUT_OF_SCOPE
    -- nothing else, no ML, no LLM call."""
    normalized = _normalize(question)
    if not normalized:
        return OUT_OF_SCOPE
    if is_control_request(question):
        return OUT_OF_SCOPE

    for phrases, intent in (
        (_HELP_PHRASES, "help"),
        (_WHATIF_PHRASES, "explain_what_if"),
        (_COMPARE_PHRASES, "compare_stations"),
        (_DECISION_PHRASES, "explain_decision"),
        (_FORECAST_PHRASES, "explain_forecast"),
        (_STATUS_PHRASES, "explain_current_status"),
    ):
        if any(p in normalized for p in phrases):
            return intent
    return OUT_OF_SCOPE


# ---------------------------------------------------------------------------
# Grounded answers
# ---------------------------------------------------------------------------

_ACTION_LABELS = {
    "battery_charge": "Battery Charge",
    "battery_discharge": "Battery Discharge",
    "water_pumping": "Water Pumping / Desalination",
    "sell_grid": "Sell to Grid",
    "grid_import": "Grid Support",
    "curtail": "Curtailment",
}


def _label(action: str | None) -> str:
    if not action:
        return "—"
    return _ACTION_LABELS.get(action, action.replace("_", " ").title())


_OUT_OF_SCOPE_MESSAGE = (
    "I can explain RA station status, forecasts, recommendations, station "
    "comparisons, and the latest What-If simulation."
)
_CONTROL_REFUSAL_MESSAGE = (
    "RA is a decision-support prototype. It recommends actions but does "
    "not send control commands to real equipment."
)
_WHATIF_MISSING_MESSAGE = "Run a What-If simulation first, then I can explain its impact."

_HELP_EXAMPLES = [
    ("Current status", "What is happening now?"),
    ("Forecast", "What is expected during the next six hours?"),
    ("Decision explanation", "Why was this decision selected?"),
    ("Station comparison", "Which station needs attention?"),
    ("What-If impact", "What changed in the latest What-If simulation?"),
]


def _answer_out_of_scope(question: str):
    if is_control_request(question):
        return _CONTROL_REFUSAL_MESSAGE, [], []
    return _OUT_OF_SCOPE_MESSAGE, [], []


def _answer_help(context: AssistantContext):
    examples = "; ".join(f'{label} (e.g. "{ex}")' for label, ex in _HELP_EXAMPLES)
    answer = (
        "I can explain RA's current station status, forecasts, recommended decisions, station "
        f"comparisons, and the latest What-If simulation. Try: {examples}."
    )
    facts = [{"label": label, "value": ex, "unit": None} for label, ex in _HELP_EXAMPLES]
    return answer, facts, []


def _answer_status(context: AssistantContext):
    cs = context.current_state
    generated_from = ["current_state"]
    if not cs:
        return f"I don't have current state data for {context.station_name} right now.", [], generated_from

    net = cs["net_balance_kw"]
    sentences = [
        f"{context.station_name} is currently generating {cs['generation_kw']:.1f} kW against "
        f"{cs['demand_kw']:.1f} kW of demand, a net {'surplus' if net >= 0 else 'deficit'} of "
        f"{abs(net):.1f} kW. Battery is at {cs['battery_soc_pct']:.0f}% state of charge."
    ]
    facts = [
        {"label": "Generation", "value": cs["generation_kw"], "unit": "kW"},
        {"label": "Demand", "value": cs["demand_kw"], "unit": "kW"},
        {"label": "Net Balance", "value": cs["net_balance_kw"], "unit": "kW"},
        {"label": "Battery SoC", "value": cs["battery_soc_pct"], "unit": "%"},
    ]

    decision = context.decision
    if decision:
        generated_from.append("decision")
        action_label = _label(decision["recommended"]["action"])
        sentences.append(
            f"RA is in {decision['mode']} mode with {decision['priority']} priority; the current "
            f"recommendation is {action_label}."
        )
        facts.append({"label": "Recommended Action", "value": action_label, "unit": None})
        facts.append({"label": "Priority", "value": decision["priority"], "unit": None})

    return " ".join(sentences), facts[:6], generated_from


def _answer_forecast(context: AssistantContext):
    fc = context.forecast
    generated_from = ["forecast"]
    points = (fc or {}).get("forecast") or []
    if not points:
        return f"I don't have a forecast available for {context.station_name} right now.", [], generated_from

    first, last = points[0], points[-1]
    horizon_hours = last["horizon_hour"]
    if last["net_balance_kw"] > first["net_balance_kw"] + 0.05:
        net_trend = "improving"
    elif last["net_balance_kw"] < first["net_balance_kw"] - 0.05:
        net_trend = "worsening"
    else:
        net_trend = "steady"
    expected_mode = "surplus" if last["net_balance_kw"] >= 0 else "deficit"

    sentences = [
        f"Over the next {horizon_hours:.0f} hours, RA expects {context.station_name}'s net balance to "
        f"trend {net_trend}, reaching an estimated {last['net_balance_kw']:.1f} kW ({expected_mode}) by "
        f"the end of the window (range {last['net_balance_lower_kw']:.1f} to "
        f"{last['net_balance_upper_kw']:.1f} kW)."
    ]
    conf = last.get("net_balance_confidence_pct")
    if conf is not None:
        sentences.append(
            f"Model confidence at that horizon is {conf:.0f}% -- a measure of how tight the "
            f"historical prediction error has been, not the probability the forecast is correct."
        )

    facts = [
        {"label": "Solar (end of window)", "value": last["solar_kw"], "unit": "kW"},
        {"label": "Wind (end of window)", "value": last["wind_kw"], "unit": "kW"},
        {"label": "Demand (end of window)", "value": last["demand_kw"], "unit": "kW"},
        {"label": "Net Balance (end of window)", "value": last["net_balance_kw"], "unit": "kW"},
    ]
    if conf is not None:
        facts.append({"label": "Net Balance Confidence", "value": conf, "unit": "%"})
    return " ".join(sentences), facts[:6], generated_from


def _answer_decision(context: AssistantContext):
    decision = context.decision
    generated_from = ["decision"]
    if not decision:
        return f"I don't have a current recommendation to explain for {context.station_name} right now.", [], generated_from

    rec = decision["recommended"]
    action_label = _label(rec["action"])
    sentences = [rec["explanation"]]

    ranked = decision.get("ranked_actions") or []
    if len(ranked) > 1:
        sentences.append(f"The next-best alternative RA considered was {_label(ranked[1]['action'])}.")

    remaining = decision.get("remaining_deficit_kw", 0) or 0
    if remaining > 0.05:
        sentences.append(f"A remaining {remaining:.1f} kW deficit is not covered by this action alone.")

    facts = [
        {"label": "Recommended Action", "value": action_label, "unit": None},
        {"label": "Mode", "value": decision["mode"], "unit": None},
        {"label": "Priority", "value": decision["priority"], "unit": None},
        {"label": "Net Balance Before", "value": decision["before"]["net_balance_kw"], "unit": "kW"},
        {"label": "Net Balance After", "value": decision["after"]["net_balance_kw"], "unit": "kW"},
    ]
    net_econ = rec.get("expected_value_egp", 0) - rec.get("expected_cost_egp", 0)
    if abs(net_econ) > 0.005:
        facts.append({"label": "Net Economic Impact", "value": round(net_econ, 2), "unit": "EGP"})
    return " ".join(sentences), facts[:6], generated_from


def _answer_compare(context: AssistantContext):
    overview = context.stations_overview
    generated_from = ["stations_overview"]
    if not overview:
        return "I don't have station overview data available right now.", [], generated_from

    priority_rank = {"critical": 3, "high": 2, "medium": 1, "normal": 0}
    most_urgent = max(overview, key=lambda s: priority_rank.get(s["priority"], 0))

    parts = [
        f"{s['name']} ({s['station_id']}): {s['status_label'].lower()} priority, net balance "
        f"{s['net_balance_kw']:+.1f} kW, recommended {_label(s['recommended_action'])}"
        for s in overview
    ]
    sentences = [
        f"Across the three stations, {most_urgent['name']} currently needs the most attention "
        f"({most_urgent['priority']} priority, {_label(most_urgent['recommended_action'])} recommended).",
        "; ".join(parts) + ".",
    ]
    facts = [
        {"label": f"{s['station_id']} priority", "value": s["priority"], "unit": None}
        for s in overview
    ]
    return " ".join(sentences), facts[:6], generated_from


def _answer_what_if(context: AssistantContext):
    wi = context.what_if
    if not wi:
        return _WHATIF_MISSING_MESSAGE, [], []

    generated_from = ["what_if"]
    sentences = [wi["explanation"]]
    impact = wi["impact"]
    facts = [
        {"label": "Generation Change", "value": impact["generation_change_kw"], "unit": "kW"},
        {"label": "Net Balance Change", "value": impact["net_balance_change_kw"], "unit": "kW"},
        {"label": "Expected Value Change", "value": impact["expected_value_change_egp"], "unit": "EGP"},
        {"label": "CO2 Avoided Change", "value": impact["co2_avoided_change_kg"], "unit": "kg"},
    ]
    if impact.get("decision_changed"):
        facts.append({
            "label": "Recommendation Change",
            "value": f"{_label(wi['baseline']['recommended_action'])} -> {_label(wi['hypothetical']['recommended_action'])}",
            "unit": None,
        })
    return " ".join(sentences), facts[:6], generated_from


_ANSWER_GENERATORS = {
    "help": _answer_help,
    "explain_current_status": _answer_status,
    "explain_forecast": _answer_forecast,
    "explain_decision": _answer_decision,
    "compare_stations": _answer_compare,
    "explain_what_if": _answer_what_if,
}


def answer_question(question: str, context: AssistantContext) -> dict:
    """Main entry point: classify, then generate a fully grounded,
    deterministic answer from `context` alone. Never touches a database,
    the network, or global state. Same (question, context) always produces
    the same output."""
    intent = classify_intent(question)

    if intent == OUT_OF_SCOPE:
        answer, facts, generated_from = _answer_out_of_scope(question)
    else:
        answer, facts, generated_from = _ANSWER_GENERATORS[intent](context)

    return {
        "intent": intent,
        "station_id": context.station_id,
        "answer": answer,
        "facts": facts,
        "generated_from": generated_from,
        "grounding": {
            "scenario": context.scenario,
            "current_index": context.current_index,
            "timestamp": context.timestamp,
            "station_id": context.station_id,
            "what_if_included": context.what_if is not None,
            "mode": "offline_deterministic",
        },
    }
