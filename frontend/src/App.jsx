import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import StatusPanel from "./components/StatusPanel.jsx";
import ForecastChart from "./components/ForecastChart.jsx";
import DecisionCard from "./components/DecisionCard.jsx";
import HistoryTimeline from "./components/HistoryTimeline.jsx";
import EgyptMap from "./components/EgyptMap.jsx";
import WhatIfPanel from "./components/WhatIfPanel.jsx";
import AssistantPanel from "./components/AssistantPanel.jsx";

const SCENARIO_LABELS = {
  sunny: "Sunny Day",
  cloudy: "Cloudy / Intermittent",
  windy: "High Wind",
  high_demand: "High Demand",
};

export default function App() {
  const [scenarios, setScenarios] = useState([]);
  const [stations, setStations] = useState([]);
  const [stationId, setStationId] = useState(null); // null -> backend defaults to hybrid-01
  const [state, setState] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [decision, setDecision] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [executing, setExecuting] = useState(false);
  const executingRef = useRef(false); // synchronous guard -- see busyRef below for why state alone isn't enough
  const [lastLogged, setLastLogged] = useState(null);
  const [autoPlay, setAutoPlay] = useState(false);
  const intervalRef = useRef(null);
  const [overview, setOverview] = useState([]);
  const [overviewError, setOverviewError] = useState(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  // Owned by WhatIfPanel via onWhatIfChange -- the current non-stale
  // What-If input percentages (or null), shared with AssistantPanel so it
  // can ground explain_what_if answers without a second copy of the
  // simulation state.
  const [whatIfInputs, setWhatIfInputs] = useState(null);
  // Guards against rapid station/scenario/tick switching: each refresh
  // captures the id current at call time and only applies its result if
  // nothing newer has started since -- otherwise an in-flight response for
  // a station/scenario the user has already navigated away from could
  // overwrite the current, correct view with stale data.
  const overviewRequestIdRef = useRef(0);
  const allRequestIdRef = useRef(0);
  // Busy guard for scenario/tick/auto-advance controls (shared, since they
  // all mutate the same one global simulated clock/scenario and must not
  // overlap) -- a ref so the auto-advance interval always reads the live
  // value, not the one captured when the interval was created.
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const setBusyBoth = (v) => {
    busyRef.current = v;
    setBusy(v);
  };

  const selectedStation = stations.find((s) => s.id === stationId);

  // Map overview is independent of which single station is selected (it
  // covers all three stations at once), so it deliberately does NOT depend
  // on stationId -- selecting a station only changes which marker is
  // highlighted, it never triggers a new /stations/overview request.
  const refreshOverview = useCallback(async () => {
    const myId = ++overviewRequestIdRef.current;
    try {
      const r = await api.getStationsOverview();
      if (myId !== overviewRequestIdRef.current) return; // superseded by a newer refresh
      setOverview(r.stations);
      setOverviewError(null);
    } catch (e) {
      if (myId !== overviewRequestIdRef.current) return;
      setOverviewError(e.message);
    } finally {
      if (myId === overviewRequestIdRef.current) setOverviewLoading(false);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    const myId = ++allRequestIdRef.current;
    try {
      const [s, f, d, h] = await Promise.all([
        api.getState(stationId),
        api.getForecast(6, stationId),
        api.getDecision(stationId),
        api.getHistory(20, stationId),
      ]);
      if (myId !== allRequestIdRef.current) return; // a newer station/refresh superseded this one
      setState(s);
      setForecast(f);
      setDecision(d);
      setHistory(h.decisions);
      setError(null);
    } catch (e) {
      if (myId !== allRequestIdRef.current) return;
      setError(e.message);
    }
  }, [stationId]);

  useEffect(() => {
    api.getScenarios().then((r) => setScenarios(r.scenarios)).catch(() => {});
    api
      .getStations()
      .then((r) => {
        setStations(r.stations);
        setStationId(r.default_station_id);
      })
      .catch(() => {});
    refreshOverview();
  }, [refreshOverview]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    if (autoPlay) {
      intervalRef.current = setInterval(async () => {
        if (busyRef.current) return; // previous tick (auto or manual) still in flight -- skip this beat
        setBusyBoth(true);
        try {
          const res = await api.tick(1);
          if (res.current_index >= res.total_points - 1) {
            setAutoPlay(false);
          }
          await refreshAll();
          await refreshOverview();
        } catch (e) {
          setError(e.message);
        } finally {
          setBusyBoth(false);
        }
      }, 2500);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    return () => intervalRef.current && clearInterval(intervalRef.current);
  }, [autoPlay, refreshAll, refreshOverview]);

  const handleScenario = async (scenario) => {
    if (busyRef.current) return;
    setBusyBoth(true);
    setAutoPlay(false);
    setLastLogged(null);
    try {
      await api.setScenario(scenario);
      await refreshAll();
      await refreshOverview();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyBoth(false);
    }
  };

  const handleStationChange = (id) => {
    setLastLogged(null);
    setStationId(id);
  };

  const handleTick = async (steps) => {
    if (busyRef.current) return;
    setBusyBoth(true);
    try {
      await api.tick(steps);
      await refreshAll();
      await refreshOverview();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyBoth(false);
    }
  };

  const handleExecute = async () => {
    if (executingRef.current) return; // guards against a second submission racing in before the button re-renders disabled
    executingRef.current = true;
    setExecuting(true);
    try {
      const res = await api.logDecision(stationId);
      setLastLogged(res);
      const h = await api.getHistory(20, stationId);
      setHistory(h.decisions);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      executingRef.current = false;
      setExecuting(false);
    }
  };

  return (
    <div className="min-h-screen text-ra-text px-4 md:px-10 py-6 flex flex-col gap-6">
      <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            <span className="text-ra-primary drop-shadow-[0_0_10px_var(--ra-primary-glow)]">RA</span>
            <span className="text-ra-text"> — Renewable AI Decision Engine</span>
          </h1>
          <p className="text-sm text-ra-text-secondary">
            Turning renewable surplus into explainable, automated decisions.
            {selectedStation && (
              <span className="text-ra-text-secondary">
                {" "}
                — {selectedStation.name} <span className="text-ra-text-muted">({selectedStation.energy_type})</span>
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={stationId || ""}
            onChange={(e) => handleStationChange(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-full border border-ra-border bg-ra-surface text-ra-text-secondary hover:border-ra-primary-dark transition"
          >
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <span className="w-px h-5 bg-ra-border" />
          {scenarios.map((s) => (
            <button
              key={s}
              onClick={() => handleScenario(s)}
              disabled={busy}
              className={`text-xs px-3 py-1.5 rounded-full border transition disabled:opacity-50 disabled:cursor-not-allowed ${
                state?.scenario === s
                  ? "bg-ra-primary border-ra-primary-strong text-ra-bg font-semibold shadow-[0_0_10px_var(--ra-primary-glow)]"
                  : "border-ra-border text-ra-text-secondary hover:border-ra-primary-dark hover:text-ra-text"
              }`}
            >
              {SCENARIO_LABELS[s] || s}
            </button>
          ))}
        </div>
      </header>

      <p className="text-xs text-ra-text-muted -mt-2 max-w-3xl">
        RA is a decision-support prototype using deterministic synthetic station data. It does not control real
        equipment.
      </p>

      {error && (
        <div className="bg-rose-950 border border-rose-800 text-rose-300 text-sm rounded-lg p-3">
          {error} — is the backend running on port 8000?
        </div>
      )}

      <StatusPanel state={state} />

      <EgyptMap
        stations={overview}
        selectedStationId={stationId}
        onSelectStation={handleStationChange}
        loading={overviewLoading}
        error={overviewError}
        onRetry={refreshOverview}
      />

      <div className="flex items-center gap-3">
        <button
          onClick={() => handleTick(1)}
          disabled={busy}
          className="text-xs px-3 py-1.5 rounded-lg border border-ra-border text-ra-text-secondary hover:border-ra-primary-dark hover:text-ra-text transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Advance 15 min
        </button>
        <button
          onClick={() => handleTick(4)}
          disabled={busy}
          className="text-xs px-3 py-1.5 rounded-lg border border-ra-border text-ra-text-secondary hover:border-ra-primary-dark hover:text-ra-text transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Advance 1 hour
        </button>
        <button
          onClick={() => setAutoPlay((p) => !p)}
          className={`text-xs px-3 py-1.5 rounded-lg border transition ${
            autoPlay
              ? "bg-ra-primary border-ra-primary-strong text-ra-bg font-semibold shadow-[0_0_10px_var(--ra-primary-glow)]"
              : "border-ra-border text-ra-text-secondary hover:border-ra-primary-dark hover:text-ra-text"
          }`}
        >
          {autoPlay ? "Pause Auto-Advance" : "Play Auto-Advance"}
        </button>
        {state?.at_end && <span className="text-xs text-amber-400">End of simulated dataset reached.</span>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <ForecastChart forecast={forecast} />
        </div>
        <DecisionCard decision={decision} onExecute={handleExecute} executing={executing} lastLogged={lastLogged} />
      </div>

      <WhatIfPanel
        stationId={stationId}
        station={selectedStation}
        scenario={state?.scenario}
        currentIndex={state?.current_index}
        onWhatIfChange={setWhatIfInputs}
      />

      <AssistantPanel
        stationId={stationId}
        scenario={state?.scenario}
        currentIndex={state?.current_index}
        whatIfInputs={whatIfInputs}
      />

      <HistoryTimeline history={history} />
    </div>
  );
}
