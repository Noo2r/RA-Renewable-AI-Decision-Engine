import { useEffect, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend as RechartsLegend,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";

const ACTION_LABELS = {
  battery_charge: "Battery Charge",
  battery_discharge: "Battery Discharge",
  water_pumping: "Water Pumping / Desalination",
  sell_grid: "Sell to Grid",
  grid_import: "Grid Support",
  curtail: "Curtailment",
};

const MODE_STYLES = {
  surplus: "bg-emerald-950 text-emerald-300 border-emerald-800",
  deficit: "bg-rose-950 text-rose-300 border-rose-800",
};

// Matches DecisionCard's ascending warm-intensity gradient (normal=
// neutral, medium=soft gold, high=amber, critical=red) for the same four
// raw priority values, kept distinct from the map's simplified 3-color
// status.
const PRIORITY_STYLES = {
  critical: "bg-rose-950 text-rose-300 border-rose-800",
  high: "bg-amber-950 text-amber-300 border-amber-800",
  medium: "bg-yellow-950 text-yellow-300 border-yellow-800",
  normal: "bg-ra-surface-hover text-ra-text-secondary border-ra-border",
};

const SLIDERS = [
  { key: "solar", label: "Solar Capacity", min: -50, max: 100, requires: "solar" },
  { key: "wind", label: "Wind Capacity", min: -50, max: 100, requires: "wind" },
  { key: "demand", label: "Demand", min: -30, max: 50, requires: null },
  { key: "battery", label: "Battery Capacity", min: -50, max: 100, requires: null },
];

function fmtKw(v) {
  return typeof v === "number" ? `${v.toFixed(1)} kW` : "—";
}
function fmtKwh(v) {
  return typeof v === "number" ? `${v.toFixed(1)} kWh` : "—";
}
function fmtPct(v) {
  return typeof v === "number" ? `${v.toFixed(0)}%` : "—";
}
function fmtEgp(v) {
  return typeof v === "number" ? `${v.toFixed(1)} EGP` : "—";
}
function fmtDelta(v, unit) {
  if (typeof v !== "number") return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)} ${unit}`;
}
function deltaColor(v, higherIsBetter = true) {
  if (typeof v !== "number" || Math.abs(v) < 0.05) return "text-ra-text-muted";
  const positive = higherIsBetter ? v > 0 : v < 0;
  return positive ? "text-emerald-400" : "text-rose-400";
}

function Row({ label, baseline, hypothetical, delta, deltaGood = true }) {
  return (
    <div className="grid grid-cols-4 gap-2 text-xs py-1.5 border-b border-ra-border-soft last:border-0">
      <span className="text-ra-text-muted">{label}</span>
      <span className="text-ra-text-secondary text-right">{baseline}</span>
      <span className="text-ra-primary text-right font-medium">{hypothetical}</span>
      <span className={`text-right ${deltaColor(delta, deltaGood)}`}>
        {typeof delta === "number" ? fmtDelta(delta, "") : delta}
      </span>
    </div>
  );
}

function Badge({ value, styles, fallback = "border-ra-border text-ra-text-secondary" }) {
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border capitalize ${styles[value] || fallback}`}>
      {value || "—"}
    </span>
  );
}

export default function WhatIfPanel({ stationId, station, scenario, currentIndex, onWhatIfChange }) {
  const [inputs, setInputs] = useState({ solar: 0, wind: 0, demand: 0, battery: 0 });
  const [result, setResult] = useState(null);
  const [runContext, setRunContext] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // Invalidates an in-flight /simulate response if the station changes (or
  // another run starts) before it resolves -- otherwise a slow response for
  // a station the user has already navigated away from could land after
  // the station-change effect below has already cleared this panel, and
  // overwrite it with a result that no longer matches what's on screen.
  const requestIdRef = useRef(0);
  // Synchronous guard: React state updates aren't synchronous, so two
  // handleRun() calls fired in the same tick would both still read
  // `loading` as false from the same stale render. A ref blocks the second.
  const loadingRef = useRef(false);

  // Report the current, non-stale What-If inputs (or null) up to the
  // parent so the Assistant panel (Part 6) can ground explain_what_if
  // answers in them, without duplicating simulation state -- runContext is
  // the single source of truth here; it's already cleared exactly when
  // station/scenario/index change (see the two effects below). Shape
  // matches the /simulate and /assistant/query request body fields.
  useEffect(() => {
    if (!onWhatIfChange) return;
    onWhatIfChange(
      runContext
        ? {
            solar_capacity_change_pct: runContext.inputs.solar,
            wind_capacity_change_pct: runContext.inputs.wind,
            demand_change_pct: runContext.inputs.demand,
            battery_capacity_change_pct: runContext.inputs.battery,
          }
        : null
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runContext]);

  const hasSolar = (station?.solar_capacity_kw ?? 0) > 0;
  const hasWind = (station?.wind_capacity_kw ?? 0) > 0;
  const applicable = { solar: hasSolar, wind: hasWind, demand: true, battery: true };

  // Station itself changed -- the sliders' meaning (applicability, base
  // capacities) no longer matches what's on screen, so reset everything.
  useEffect(() => {
    requestIdRef.current++; // invalidate any in-flight /simulate for the previous station
    setInputs({ solar: 0, wind: 0, demand: 0, battery: 0 });
    setResult(null);
    setRunContext(null);
    setError(null);
  }, [stationId]);

  // Scenario or the simulated clock advanced -- the underlying real system
  // state has changed, so a previous result no longer describes "now".
  // Sliders are left alone; only the stale result is cleared.
  useEffect(() => {
    if (runContext && (runContext.scenario !== scenario || runContext.currentIndex !== currentIndex)) {
      setResult(null);
      setRunContext(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, currentIndex]);

  const inputsMatchLastRun =
    runContext &&
    runContext.inputs.solar === inputs.solar &&
    runContext.inputs.wind === inputs.wind &&
    runContext.inputs.demand === inputs.demand &&
    runContext.inputs.battery === inputs.battery;
  const resultIsPending = result && runContext && !inputsMatchLastRun;

  const handleSlider = (key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  };

  const handleRun = async () => {
    if (loadingRef.current) return; // a simulation is already in flight -- ignore a double-click
    loadingRef.current = true;
    const myId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const body = {
        station_id: stationId,
        solar_capacity_change_pct: hasSolar ? inputs.solar : 0,
        wind_capacity_change_pct: hasWind ? inputs.wind : 0,
        demand_change_pct: inputs.demand,
        battery_capacity_change_pct: inputs.battery,
      };
      const r = await api.simulateWhatIf(body);
      if (myId !== requestIdRef.current) return; // superseded by a station change or another run
      setResult(r);
      setRunContext({ scenario: r.scenario, currentIndex: r.current_index, inputs: { ...inputs } });
    } catch (e) {
      if (myId !== requestIdRef.current) return;
      setError(e.message);
    } finally {
      loadingRef.current = false;
      if (myId === requestIdRef.current) setLoading(false);
    }
  };

  const handleReset = () => {
    requestIdRef.current++; // invalidate any in-flight /simulate started before Reset was clicked
    setInputs({ solar: 0, wind: 0, demand: 0, battery: 0 });
    setResult(null);
    setRunContext(null);
    setError(null);
  };

  const chartData = result
    ? [
        { metric: "Generation", Baseline: result.baseline.forecast_generation_kw, Hypothetical: result.hypothetical.forecast_generation_kw },
        { metric: "Demand", Baseline: result.baseline.forecast_demand_kw, Hypothetical: result.hypothetical.forecast_demand_kw },
        { metric: "Net Balance", Baseline: result.baseline.forecast_net_balance_kw, Hypothetical: result.hypothetical.forecast_net_balance_kw },
      ]
    : [];

  return (
    <div className="bg-ra-surface border border-ra-border-soft rounded-xl p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-1">
        <h2 className="text-sm font-semibold text-ra-primary">What-If Simulator</h2>
        <span className="text-[10px] uppercase tracking-wide text-ra-text-muted">Hypothetical — does not change live state</span>
      </div>
      <p className="text-xs text-ra-text-muted -mt-2">
        What-If results are hypothetical and do not change the live map or station state.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {SLIDERS.map((s) => {
          const enabled = applicable[s.requires ?? s.key];
          return (
            <div key={s.key} className={enabled ? "" : "opacity-50"}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-ra-text-secondary">{s.label}</span>
                <span className="text-ra-text-muted font-mono">{inputs[s.key] > 0 ? "+" : ""}{inputs[s.key]}%</span>
              </div>
              <input
                type="range"
                min={s.min}
                max={s.max}
                step={5}
                value={inputs[s.key]}
                disabled={!enabled}
                onChange={(e) => handleSlider(s.key, Number(e.target.value))}
                className="w-full accent-ra-primary disabled:cursor-not-allowed"
                aria-label={`${s.label} change percent`}
              />
              {!enabled && (
                <p className="text-[10px] text-ra-text-muted mt-0.5">
                  Not applicable — {station?.name || stationId} has no configured {s.key} capacity.
                </p>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={handleRun}
          disabled={loading}
          className="text-xs px-3 py-1.5 rounded-lg bg-ra-primary hover:bg-ra-primary-strong text-ra-bg font-semibold transition shadow-[0_0_10px_var(--ra-primary-glow)] hover:shadow-[0_0_16px_var(--ra-primary-glow)] disabled:bg-ra-surface-hover disabled:text-ra-text-muted disabled:shadow-none disabled:cursor-not-allowed"
        >
          {loading ? "Running…" : "Run Simulation"}
        </button>
        <button
          onClick={handleReset}
          className="text-xs px-3 py-1.5 rounded-lg border border-ra-border text-ra-text-secondary hover:border-ra-primary-dark hover:text-ra-text transition"
        >
          Reset
        </button>
        {resultIsPending && (
          <span className="text-xs text-amber-400">Inputs changed — run again to update the result.</span>
        )}
      </div>

      {error && (
        <div className="bg-rose-950 border border-rose-800 text-rose-300 text-xs rounded-lg p-3">{error}</div>
      )}

      {!result && !error && (
        <div className="text-xs text-ra-text-muted border border-ra-border-soft rounded-lg p-4 text-center">
          Adjust the sliders above and click Run Simulation to compare a hypothetical scenario against the current
          baseline.
        </div>
      )}

      {result && (
        <div className={`flex flex-col gap-4 ${resultIsPending ? "opacity-60" : ""}`}>
          <div className="flex items-center gap-2 flex-wrap">
            <Badge value={result.hypothetical.mode} styles={MODE_STYLES} />
            <Badge value={result.hypothetical.priority} styles={PRIORITY_STYLES} />
            {result.impact.decision_changed && (
              <span className="text-[10px] px-2 py-0.5 rounded-full border border-ra-primary-dark bg-ra-primary-soft text-ra-primary">
                Decision changed
              </span>
            )}
          </div>

          <div>
            <div className="grid grid-cols-4 gap-2 text-[10px] uppercase tracking-wide text-ra-text-muted pb-1 border-b border-ra-border-soft">
              <span>Metric</span>
              <span className="text-right">Baseline</span>
              <span className="text-right">Hypothetical</span>
              <span className="text-right">Δ Impact</span>
            </div>
            <Row label="Generation (1h avg)" baseline={fmtKw(result.baseline.forecast_generation_kw)}
                 hypothetical={fmtKw(result.hypothetical.forecast_generation_kw)}
                 delta={result.impact.generation_change_kw} />
            <Row label="Demand (1h avg)" baseline={fmtKw(result.baseline.forecast_demand_kw)}
                 hypothetical={fmtKw(result.hypothetical.forecast_demand_kw)}
                 delta={result.impact.demand_change_kw} deltaGood={false} />
            <Row label="Net Balance (1h avg)" baseline={fmtKw(result.baseline.forecast_net_balance_kw)}
                 hypothetical={fmtKw(result.hypothetical.forecast_net_balance_kw)}
                 delta={result.impact.net_balance_change_kw} />
            <Row label="Battery Capacity" baseline={fmtKwh(result.baseline.battery_capacity_kwh)}
                 hypothetical={fmtKwh(result.hypothetical.battery_capacity_kwh)}
                 delta={result.impact.battery_capacity_change_kwh} />
            <Row label="Recommended Action"
                 baseline={ACTION_LABELS[result.baseline.recommended_action] || result.baseline.recommended_action}
                 hypothetical={ACTION_LABELS[result.hypothetical.recommended_action] || result.hypothetical.recommended_action}
                 delta={result.impact.decision_changed ? "changed" : "same"} />
            <Row label="Expected Value" baseline={fmtEgp(result.baseline.expected_value_egp)}
                 hypothetical={fmtEgp(result.hypothetical.expected_value_egp)}
                 delta={result.impact.expected_value_change_egp} />
            <Row label="Expected Cost" baseline={fmtEgp(result.baseline.expected_cost_egp)}
                 hypothetical={fmtEgp(result.hypothetical.expected_cost_egp)}
                 delta={result.impact.expected_cost_change_egp} deltaGood={false} />
            <Row label="CO2 Avoided" baseline={`${result.baseline.co2_avoided_kg.toFixed(1)} kg`}
                 hypothetical={`${result.hypothetical.co2_avoided_kg.toFixed(1)} kg`}
                 delta={result.impact.co2_avoided_change_kg} />
            <Row label="CO2 Emitted" baseline={`${result.baseline.co2_emitted_kg.toFixed(1)} kg`}
                 hypothetical={`${result.hypothetical.co2_emitted_kg.toFixed(1)} kg`}
                 delta={result.impact.co2_emitted_change_kg} deltaGood={false} />
            <Row label="Remaining Deficit" baseline={fmtKw(result.baseline.remaining_deficit_kw)}
                 hypothetical={fmtKw(result.hypothetical.remaining_deficit_kw)}
                 delta={result.impact.remaining_deficit_change_kw} deltaGood={false} />
          </div>

          <div className="h-48 bg-ra-bg-elevated border border-ra-border-soft rounded-lg p-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#3a3217" />
                <XAxis dataKey="metric" tick={{ fontSize: 11, fill: "#9f967c" }} />
                <YAxis tick={{ fontSize: 11, fill: "#9f967c" }} label={{ value: "kW", angle: -90, position: "insideLeft", fill: "#9f967c", fontSize: 11 }} />
                <RechartsTooltip
                  contentStyle={{ background: "#14120b", border: "1px solid #3a3217", fontSize: 12 }}
                  formatter={(v) => `${v.toFixed(1)} kW`}
                />
                <RechartsLegend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="Baseline" fill="#8a8272" radius={[3, 3, 0, 0]} />
                <Bar dataKey="Hypothetical" fill="#eab308" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-ra-bg-elevated border border-ra-border-soft rounded-lg p-3 text-xs text-ra-text-secondary leading-relaxed">
            {result.explanation}
          </div>
        </div>
      )}
    </div>
  );
}
