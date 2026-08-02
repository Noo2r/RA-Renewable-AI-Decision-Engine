import { useEffect, useRef, useState } from "react";
import { api } from "../api";

const QUICK_QUESTIONS = [
  { text: "What is happening now?", requiresWhatIf: false },
  { text: "What is expected during the next six hours?", requiresWhatIf: false },
  { text: "Why was this decision selected?", requiresWhatIf: false },
  { text: "Which station needs attention?", requiresWhatIf: false },
  { text: "What changed in the latest What-If simulation?", requiresWhatIf: true },
];

const STALE_MESSAGE = "System context changed. Ask RA again for an updated explanation.";

function FactChip({ fact }) {
  const value = typeof fact.value === "number" ? fact.value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : fact.value;
  return (
    <div className="bg-slate-950/60 border border-slate-800 rounded-lg px-2.5 py-1.5 flex flex-col min-w-[110px]">
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{fact.label}</span>
      <span className="text-sm text-slate-200 font-medium">
        {value}
        {fact.unit ? <span className="text-slate-500 text-xs"> {fact.unit}</span> : null}
      </span>
    </div>
  );
}

function whatIfInputsEqual(a, b) {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.solar_capacity_change_pct === b.solar_capacity_change_pct &&
    a.wind_capacity_change_pct === b.wind_capacity_change_pct &&
    a.demand_change_pct === b.demand_change_pct &&
    a.battery_capacity_change_pct === b.battery_capacity_change_pct
  );
}

export default function AssistantPanel({ stationId, scenario, currentIndex, whatIfInputs }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [askedContext, setAskedContext] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stale, setStale] = useState(false);
  const isFirstRender = useRef(true);

  // Grounding-context change (station/scenario/index/What-If inputs) --
  // clear the previous answer rather than leave it looking current.
  // Typing in the question box must NOT trigger this (it isn't a
  // dependency here).
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    if (
      askedContext &&
      (askedContext.stationId !== stationId ||
        askedContext.scenario !== scenario ||
        askedContext.currentIndex !== currentIndex ||
        !whatIfInputsEqual(askedContext.whatIfInputs, whatIfInputs))
    ) {
      setAnswer(null);
      setAskedContext(null);
      setError(null);
      setStale(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationId, scenario, currentIndex, whatIfInputs]);

  const ask = async (text) => {
    const trimmed = (text ?? question).trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setStale(false);
    try {
      const body = { station_id: stationId, question: trimmed };
      if (whatIfInputs) body.what_if_inputs = whatIfInputs;
      const r = await api.assistantQuery(body);
      setAnswer(r);
      setAskedContext({ stationId, scenario, currentIndex, whatIfInputs });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleQuickQuestion = (text) => {
    setQuestion(text);
    ask(text);
  };

  const handleClear = () => {
    setQuestion("");
    setAnswer(null);
    setAskedContext(null);
    setError(null);
    setStale(false);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-1">
        <h2 className="text-sm font-semibold text-slate-200">RA Assistant</h2>
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Offline · Grounded in current RA data</span>
      </div>
      <p className="text-xs text-slate-500 -mt-2">RA explains calculated system results. It does not control real equipment.</p>

      <div className="flex flex-wrap gap-1.5">
        {QUICK_QUESTIONS.map((q) => {
          const disabled = q.requiresWhatIf && !whatIfInputs;
          return (
            <button
              key={q.text}
              onClick={() => handleQuickQuestion(q.text)}
              disabled={disabled || loading}
              title={disabled ? "Run a What-If simulation first" : undefined}
              className="text-xs px-2.5 py-1 rounded-full border border-slate-700 text-slate-300 hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {q.text}
            </button>
          );
        })}
      </div>

      <div className="flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") ask();
          }}
          placeholder="Ask RA about the current station…"
          className="flex-1 text-xs px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-950 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500"
        />
        <button
          onClick={() => ask()}
          disabled={loading || !question.trim()}
          className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 border border-indigo-500 text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Asking…" : "Ask"}
        </button>
        <button
          onClick={handleClear}
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500"
        >
          Clear
        </button>
      </div>

      {error && (
        <div className="bg-rose-950 border border-rose-800 text-rose-300 text-xs rounded-lg p-3">{error}</div>
      )}

      {stale && !answer && !loading && !error && (
        <div className="bg-amber-950 border border-amber-800 text-amber-300 text-xs rounded-lg p-3">
          {STALE_MESSAGE}
        </div>
      )}

      {!answer && !error && !loading && !stale && (
        <div className="text-xs text-slate-500 border border-slate-800 rounded-lg p-4 text-center">
          Ask a question above, or pick a quick question, to get a grounded explanation of the current station.
        </div>
      )}

      {answer && (
        <div className="flex flex-col gap-3">
          <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-3 text-sm text-slate-200 leading-relaxed">
            {answer.answer}
          </div>

          {answer.facts && answer.facts.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {answer.facts.map((f, i) => (
                <FactChip key={`${f.label}-${i}`} fact={f} />
              ))}
            </div>
          )}

          <div className="text-[10px] text-slate-500 flex flex-wrap gap-x-3 gap-y-1">
            <span className="capitalize">Intent: {answer.intent.replace(/_/g, " ")}</span>
            <span>Station: {answer.station_id}</span>
            <span className="capitalize">Scenario: {answer.grounding.scenario}</span>
            {answer.grounding.timestamp && (
              <span>
                {new Date(answer.grounding.timestamp).toLocaleString(undefined, {
                  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                })}
              </span>
            )}
            <span>{answer.grounding.mode === "llm_rewrite" ? "LLM-rewritten wording" : "Offline deterministic"}</span>
          </div>
        </div>
      )}
    </div>
  );
}
