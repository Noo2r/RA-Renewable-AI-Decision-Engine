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

  const selectedStation = stations.find((s) => s.id === stationId);

  // Map overview is independent of which single station is selected (it
  // covers all three stations at once), so it deliberately does NOT depend
  // on stationId -- selecting a station only changes which marker is
  // highlighted, it never triggers a new /stations/overview request.
  const refreshOverview = useCallback(async () => {
    try {
      const r = await api.getStationsOverview();
      setOverview(r.stations);
      setOverviewError(null);
    } catch (e) {
      setOverviewError(e.message);
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      const [s, f, d, h] = await Promise.all([
        api.getState(stationId),
        api.getForecast(6, stationId),
        api.getDecision(stationId),
        api.getHistory(20, stationId),
      ]);
      setState(s);
      setForecast(f);
      setDecision(d);
      setHistory(h.decisions);
      setError(null);
    } catch (e) {
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
        const res = await api.tick(1);
        if (res.current_index >= res.total_points - 1) {
          setAutoPlay(false);
        }
        refreshAll();
        refreshOverview();
      }, 2500);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    return () => intervalRef.current && clearInterval(intervalRef.current);
  }, [autoPlay, refreshAll, refreshOverview]);

  const handleScenario = async (scenario) => {
    setAutoPlay(false);
    setLastLogged(null);
    await api.setScenario(scenario);
    await refreshAll();
    await refreshOverview();
  };

  const handleStationChange = (id) => {
    setLastLogged(null);
    setStationId(id);
  };

  const handleTick = async (steps) => {
    await api.tick(steps);
    await refreshAll();
    await refreshOverview();
  };

  const handleExecute = async () => {
    setExecuting(true);
    try {
      const res = await api.logDecision(stationId);
      setLastLogged(res);
      const h = await api.getHistory(20, stationId);
      setHistory(h.decisions);
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 px-4 md:px-10 py-6 flex flex-col gap-6">
      <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">RA — Renewable AI Decision Engine</h1>
          <p className="text-sm text-slate-400">
            Turning renewable surplus into explainable, automated decisions.
            {selectedStation && (
              <span className="text-slate-300">
                {" "}
                — {selectedStation.name} <span className="text-slate-500">({selectedStation.energy_type})</span>
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={stationId || ""}
            onChange={(e) => handleStationChange(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-full border border-slate-700 bg-slate-900 text-slate-300 hover:border-slate-500"
          >
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <span className="w-px h-5 bg-slate-800" />
          {scenarios.map((s) => (
            <button
              key={s}
              onClick={() => handleScenario(s)}
              className={`text-xs px-3 py-1.5 rounded-full border transition ${
                state?.scenario === s
                  ? "bg-indigo-600 border-indigo-500 text-white"
                  : "border-slate-700 text-slate-300 hover:border-slate-500"
              }`}
            >
              {SCENARIO_LABELS[s] || s}
            </button>
          ))}
        </div>
      </header>

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
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500"
        >
          Advance 15 min
        </button>
        <button
          onClick={() => handleTick(4)}
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500"
        >
          Advance 1 hour
        </button>
        <button
          onClick={() => setAutoPlay((p) => !p)}
          className={`text-xs px-3 py-1.5 rounded-lg border transition ${
            autoPlay
              ? "bg-emerald-600 border-emerald-500 text-white"
              : "border-slate-700 text-slate-300 hover:border-slate-500"
          }`}
        >
          {autoPlay ? "Pause Auto-Advance" : "Play Auto-Advance"}
        </button>
        {state?.at_end && <span className="text-xs text-amber-400">End of simulated dataset reached.</span>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <ForecastChart forecast={forecast} />
          <HistoryTimeline history={history} />
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
    </div>
  );
}
