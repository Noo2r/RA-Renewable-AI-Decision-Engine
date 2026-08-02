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
    <div className="bg-ra-bg-elevated border border-ra-border rounded-lg px-2.5 py-1.5 flex flex-col min-w-[110px]">
      <span className="text-[10px] uppercase tracking-wide text-ra-text-muted">{fact.label}</span>
      <span className="text-sm text-ra-text font-medium">
        {value}
        {fact.unit ? <span className="text-ra-text-muted text-xs"> {fact.unit}</span> : null}
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
  // Invalidates an in-flight /assistant/query response if the grounding
  // context changes (or a new question is asked) before it resolves --
  // otherwise a slow response for a station/scenario/index the user has
  // already navigated away from could land after the context-change effect
  // below has already cleared this panel, overwriting it with an answer
  // that no longer matches what's grounded on screen.
  const requestIdRef = useRef(0);
  // React state updates aren't synchronous, so two ask() calls fired back
  // to back in the same tick (e.g. mashing Enter) would both still read
  // `loading` as false from the same stale render and both proceed. A ref
  // is read/written synchronously, so it actually blocks the second call.
  const loadingRef = useRef(false);

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
      requestIdRef.current++; // invalidate any in-flight query grounded in the old context
      setAnswer(null);
      setAskedContext(null);
      setError(null);
      setStale(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationId, scenario, currentIndex, whatIfInputs]);

  const ask = async (text) => {
    if (loadingRef.current) return; // a request is already in flight -- ignore Enter/click double-fire
    const trimmed = (text ?? question).trim();
    if (!trimmed) return;
    loadingRef.current = true;
    const myId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    setStale(false);
    try {
      const body = { station_id: stationId, question: trimmed };
      if (whatIfInputs) body.what_if_inputs = whatIfInputs;
      const r = await api.assistantQuery(body);
      if (myId !== requestIdRef.current) return; // superseded by a context change or another ask
      setAnswer(r);
      setAskedContext({ stationId, scenario, currentIndex, whatIfInputs });
    } catch (e) {
      if (myId !== requestIdRef.current) return;
      setError(e.message);
    } finally {
      loadingRef.current = false;
      if (myId === requestIdRef.current) setLoading(false);
    }
  };

  const handleQuickQuestion = (text) => {
    setQuestion(text);
    ask(text);
  };

  const handleClear = () => {
    requestIdRef.current++; // invalidate any in-flight query started before Clear was clicked
    setQuestion("");
    setAnswer(null);
    setAskedContext(null);
    setError(null);
    setStale(false);
  };

  return (
    <div className="bg-ra-surface border border-ra-border-soft rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-1">
        <h2 className="text-sm font-semibold text-ra-primary">RA Assistant</h2>
        <span className="text-[10px] uppercase tracking-wide text-ra-text-muted">Offline · Grounded in current RA data</span>
      </div>
      <p className="text-xs text-ra-text-muted -mt-2">RA explains calculated system results. It does not control real equipment.</p>

      <div className="flex flex-wrap gap-1.5">
        {QUICK_QUESTIONS.map((q) => {
          const disabled = q.requiresWhatIf && !whatIfInputs;
          return (
            <button
              key={q.text}
              onClick={() => handleQuickQuestion(q.text)}
              disabled={disabled || loading}
              title={disabled ? "Run a What-If simulation first" : undefined}
              className="text-xs px-2.5 py-1 rounded-full border border-ra-border-soft text-ra-text-secondary hover:border-ra-primary-dark hover:text-ra-primary transition disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-ra-border-soft disabled:hover:text-ra-text-secondary"
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
          className="flex-1 text-xs px-3 py-1.5 rounded-lg border border-ra-border bg-ra-bg-elevated text-ra-text placeholder:text-ra-text-muted focus:outline-none focus:border-ra-focus"
        />
        <button
          onClick={() => ask()}
          disabled={loading || !question.trim()}
          className="text-xs px-3 py-1.5 rounded-lg bg-ra-primary hover:bg-ra-primary-strong text-ra-bg font-semibold transition shadow-[0_0_10px_var(--ra-primary-glow)] hover:shadow-[0_0_16px_var(--ra-primary-glow)] disabled:bg-ra-surface-hover disabled:text-ra-text-muted disabled:shadow-none disabled:cursor-not-allowed"
        >
          {loading ? "Asking…" : "Ask"}
        </button>
        <button
          onClick={handleClear}
          className="text-xs px-3 py-1.5 rounded-lg border border-ra-border text-ra-text-secondary hover:border-ra-primary-dark hover:text-ra-text transition"
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
        <div className="text-xs text-ra-text-muted border border-ra-border-soft rounded-lg p-4 text-center">
          Ask a question above, or pick a quick question, to get a grounded explanation of the current station.
        </div>
      )}

      {answer && (
        <div className="flex flex-col gap-3">
          <div className="bg-ra-bg-elevated border border-ra-border-soft rounded-lg p-3 text-sm text-ra-text leading-relaxed">
            {answer.answer}
          </div>

          {answer.facts && answer.facts.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {answer.facts.map((f, i) => (
                <FactChip key={`${f.label}-${i}`} fact={f} />
              ))}
            </div>
          )}

          <div className="text-[10px] text-ra-text-muted flex flex-wrap gap-x-3 gap-y-1">
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
