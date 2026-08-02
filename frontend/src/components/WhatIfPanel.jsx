import { useEffect, useState } from "react";
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

const PRIORITY_STYLES = {
  critical: "bg-rose-950 text-rose-300 border-rose-800",
  high: "bg-amber-950 text-amber-300 border-amber-800",
  medium: "bg-sky-950 text-sky-300 border-sky-800",
  normal: "bg-slate-800 text-slate-300 border-slate-700",
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
  if (typeof v !== "number" || Math.abs(v) < 0.05) return "text-slate-400";
  const positive = higherIsBetter ? v > 0 : v < 0;
  return positive ? "text-emerald-400" : "text-rose-400";
}

function Row({ label, baseline, hypothetical, delta, deltaGood = true }) {
  return (
    <div className="grid grid-cols-4 gap-2 text-xs py-1.5 border-b border-slate-800/60 last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-300 text-right">{baseline}</span>
      <span className="text-slate-100 text-right font-medium">{hypothetical}</span>
      <span className={`text-right ${deltaColor(delta, deltaGood)}`}>
        {typeof delta === "number" ? fmtDelta(delta, "") : delta}
      </span>
    </div>
  );
}

function Badge({ value, styles, fallback = "border-slate-700 text-slate-300" }) {
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border capitalize ${styles[value] || fallback}`}>
      {value || "—"}
    </span>
  );
}

export default function WhatIfPanel({ stationId, station, scenario, currentIndex }) {
  const [inputs, setInputs] = useState({ solar: 0, wind: 0, demand: 0, battery: 0 });
  const [result, setResult] = useState(null);
  const [runContext, setRunContext] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const hasSolar = (station?.solar_capacity_kw ?? 0) > 0;
  const hasWind = (station?.wind_capacity_kw ?? 0) > 0;
  const applicable = { solar: hasSolar, wind: hasWind, demand: true, battery: true };

  // Station itself changed -- the sliders' meaning (applicability, base
  // capacities) no longer matches what's on screen, so reset everything.
  useEffect(() => {
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
      setResult(r);
      setRunContext({ scenario: r.scenario, currentIndex: r.current_index, inputs: { ...inputs } });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
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
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-1">
        <h2 className="text-sm font-semibold text-slate-200">What-If Simulator</h2>
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Hypothetical — does not change live state</span>
      </div>
      <p className="text-xs text-slate-500 -mt-2">
        What-If results are hypothetical and do not change the live map or station state.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {SLIDERS.map((s) => {
          const enabled = applicable[s.requires ?? s.key];
          return (
            <div key={s.key} className={enabled ? "" : "opacity-50"}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-slate-300">{s.label}</span>
                <span className="text-slate-400 font-mono">{inputs[s.key] > 0 ? "+" : ""}{inputs[s.key]}%</span>
              </div>
              <input
                type="range"
                min={s.min}
                max={s.max}
                step={5}
                value={inputs[s.key]}
                disabled={!enabled}
                onChange={(e) => handleSlider(s.key, Number(e.target.value))}
                className="w-full accent-indigo-500 disabled:cursor-not-allowed"
                aria-label={`${s.label} change percent`}
              />
              {!enabled && (
                <p className="text-[10px] text-slate-500 mt-0.5">
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
          className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 border border-indigo-500 text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Running…" : "Run Simulation"}
        </button>
        <button
          onClick={handleReset}
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500"
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
        <div className="text-xs text-slate-500 border border-slate-800 rounded-lg p-4 text-center">
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
              <span className="text-[10px] px-2 py-0.5 rounded-full border border-indigo-700 bg-indigo-950 text-indigo-300">
                Decision changed
              </span>
            )}
          </div>

          <div>
            <div className="grid grid-cols-4 gap-2 text-[10px] uppercase tracking-wide text-slate-500 pb-1 border-b border-slate-800">
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

          <div className="h-48 bg-slate-950/60 border border-slate-800 rounded-lg p-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="metric" tick={{ fontSize: 11, fill: "#94a3b8" }} />
                <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} label={{ value: "kW", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }} />
                <RechartsTooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", fontSize: 12 }}
                  formatter={(v) => `${v.toFixed(1)} kW`}
                />
                <RechartsLegend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="Baseline" fill="#64748b" radius={[3, 3, 0, 0]} />
                <Bar dataKey="Hypothetical" fill="#6366f1" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-3 text-xs text-slate-300 leading-relaxed">
            {result.explanation}
          </div>
        </div>
      )}
    </div>
  );
}
