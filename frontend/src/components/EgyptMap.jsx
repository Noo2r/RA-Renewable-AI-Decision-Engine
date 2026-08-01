import { useState } from "react";
import { projectToSvg } from "../lib/mapProjection";

// Simplified, hand-drawn outline of Egypt (NOT a GIS/GeoJSON asset) -- a
// small set of approximate (latitude, longitude) boundary points, chosen to
// be recognizable at a glance, not survey-accurate. Projected once at
// module load through the same projectToSvg() helper used for stations, so
// the outline and the markers share one coordinate system.
const EGYPT_OUTLINE_LATLON = [
  [31.5, 25.0], [31.7, 31.5], [31.4, 32.4], [31.2, 32.9],
  [31.3, 34.5], [29.6, 34.9], [28.0, 34.3], [27.7, 34.6],
  [28.9, 33.2], [29.9, 32.6], [29.4, 32.3], [27.2, 33.8],
  [23.5, 35.6], [22.0, 35.9], [22.0, 25.0],
];
const EGYPT_OUTLINE_POINTS = EGYPT_OUTLINE_LATLON.map(([lat, lon]) => {
  const { x, y } = projectToSvg(lat, lon);
  return `${x.toFixed(1)},${y.toFixed(1)}`;
}).join(" ");

const STATUS_COLORS = {
  normal: "#10b981", // green
  warning: "#eab308", // yellow
  critical: "#ef4444", // red
  unknown: "#64748b", // neutral gray fallback
};

const STATUS_GLYPHS = {
  normal: "N",
  warning: "W",
  critical: "C",
  unknown: "?",
};

const ACTION_LABELS = {
  battery_charge: "Battery Charge",
  battery_discharge: "Battery Discharge",
  water_pumping: "Water Pumping / Desalination",
  sell_grid: "Sell to Grid",
  grid_import: "Grid Support",
  curtail: "Curtailment",
};

function fmtKw(v) {
  return typeof v === "number" ? `${v.toFixed(1)} kW` : "—";
}

function fmtPct(v) {
  return typeof v === "number" ? `${v.toFixed(0)}%` : "—";
}

function Legend() {
  return (
    <div className="flex flex-col gap-1 text-xs text-slate-400">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: STATUS_COLORS.normal }} />
          Green — Normal
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: STATUS_COLORS.warning }} />
          Yellow — Warning
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: STATUS_COLORS.critical }} />
          Red — Critical
        </span>
      </div>
      <p className="text-[10px] text-slate-500">
        Status is based on the current RA recommendation priority, not equipment health or a failure diagnosis.
      </p>
    </div>
  );
}

function StationPreview({ station }) {
  if (!station) {
    return (
      <div className="text-xs text-slate-500 border border-slate-800 rounded-lg p-3">
        Hover, focus, or select a marker to see station details.
      </div>
    );
  }
  const status = station.status || "unknown";
  return (
    <div className="border border-slate-800 rounded-lg p-3 flex flex-col gap-1 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-200">{station.name || station.station_id}</span>
        <span
          className="text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide"
          style={{ background: `${STATUS_COLORS[status] || STATUS_COLORS.unknown}22`, color: STATUS_COLORS[status] || STATUS_COLORS.unknown }}
        >
          {station.status_label || "Unknown"}
        </span>
      </div>
      <div className="text-slate-500 capitalize">{station.energy_type || "unknown"} station</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-slate-300 mt-1">
        <span>Generation: {fmtKw(station.generation_kw)}</span>
        <span>Demand: {fmtKw(station.demand_kw)}</span>
        <span>Net Balance: {fmtKw(station.net_balance_kw)}</span>
        <span>Battery SoC: {fmtPct(station.battery_soc_pct)}</span>
        <span className="capitalize">Mode: {station.mode || "—"}</span>
        <span className="capitalize">Priority: {station.priority || "—"}</span>
      </div>
      <div className="text-slate-400 mt-1">
        Recommended: {ACTION_LABELS[station.recommended_action] || station.recommended_action || "—"}
      </div>
    </div>
  );
}

export default function EgyptMap({ stations, selectedStationId, onSelectStation, loading, error, onRetry }) {
  const [previewId, setPreviewId] = useState(null);

  const safeStations = Array.isArray(stations) ? stations : [];
  const previewStation =
    safeStations.find((s) => s.station_id === previewId) ||
    safeStations.find((s) => s.station_id === selectedStationId) ||
    null;

  const showStaleMapWithWarning = error && safeStations.length > 0;
  const showFullError = error && safeStations.length === 0;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-1">
        <h2 className="text-sm font-semibold text-slate-200">Egypt Station Map</h2>
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Demo Map — approximate station locations</span>
      </div>

      {showStaleMapWithWarning && (
        <div className="text-xs bg-amber-950 border border-amber-800 text-amber-300 rounded-lg p-2 flex items-center justify-between gap-2">
          <span>Map data could not refresh ({error}). Showing last known state.</span>
          {onRetry && (
            <button onClick={onRetry} className="shrink-0 px-2 py-0.5 rounded border border-amber-700 hover:border-amber-500">
              Retry
            </button>
          )}
        </div>
      )}

      {showFullError && (
        <div className="text-xs bg-rose-950 border border-rose-800 text-rose-300 rounded-lg p-3 flex items-center justify-between gap-2">
          <span>Could not load station map ({error}).</span>
          {onRetry && (
            <button onClick={onRetry} className="shrink-0 px-2 py-1 rounded border border-rose-700 hover:border-rose-500">
              Retry
            </button>
          )}
        </div>
      )}

      {loading && !showFullError && safeStations.length === 0 && (
        <div className="text-xs text-slate-500 border border-slate-800 rounded-lg p-6 text-center animate-pulse">
          Loading station map…
        </div>
      )}

      {!showFullError && safeStations.length === 0 && !loading && (
        <div className="text-xs text-slate-500 border border-slate-800 rounded-lg p-6 text-center">
          No station data available.
        </div>
      )}

      {safeStations.length > 0 && (
        <div className="flex flex-col md:flex-row gap-4 items-start">
          <svg
            viewBox="0 0 400 400"
            role="img"
            aria-labelledby="egypt-map-title egypt-map-desc"
            className="w-full max-w-[280px] mx-auto md:mx-0"
          >
            <title id="egypt-map-title">Map of Egypt showing RA demo station locations</title>
            <desc id="egypt-map-desc">
              A simplified outline of Egypt with three interactive markers for solar-01, wind-01, and hybrid-01,
              colored green, yellow, or red by each station&apos;s current recommendation priority.
            </desc>
            <polygon points={EGYPT_OUTLINE_POINTS} fill="#1e293b" stroke="#475569" strokeWidth="1.5" />

            {safeStations.map((station) => {
              const lat = station.latitude;
              const lon = station.longitude;
              if (typeof lat !== "number" || typeof lon !== "number") return null;
              const { x, y } = projectToSvg(lat, lon);
              const status = station.status && STATUS_COLORS[station.status] ? station.status : "unknown";
              const isSelected = station.station_id === selectedStationId;
              const label = `${station.name || station.station_id}, status ${station.status_label || "Unknown"}${
                isSelected ? ", currently selected" : ""
              }`;

              const select = () => onSelectStation && onSelectStation(station.station_id);

              return (
                <g
                  key={station.station_id}
                  transform={`translate(${x.toFixed(1)},${y.toFixed(1)})`}
                  tabIndex={0}
                  role="button"
                  aria-label={label}
                  aria-pressed={isSelected}
                  className="cursor-pointer outline-none"
                  onClick={select}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      select();
                    }
                  }}
                  onMouseEnter={() => setPreviewId(station.station_id)}
                  onMouseLeave={() => setPreviewId(null)}
                  onFocus={() => setPreviewId(station.station_id)}
                  onBlur={() => setPreviewId(null)}
                >
                  {isSelected && <circle r="11" fill="none" stroke="#f8fafc" strokeWidth="2" opacity="0.9" />}
                  {previewId === station.station_id && !isSelected && (
                    <circle r="11" fill="none" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="3 2" opacity="0.9" />
                  )}
                  <circle r="8" fill={STATUS_COLORS[status]} stroke="#0f172a" strokeWidth="1.5" />
                  <text textAnchor="middle" dy="3" fontSize="8" fontWeight="700" fill="#0f172a">
                    {STATUS_GLYPHS[status]}
                  </text>
                </g>
              );
            })}
          </svg>

          <div className="flex-1 min-w-[200px] flex flex-col gap-3">
            <Legend />
            <StationPreview station={previewStation} />
          </div>
        </div>
      )}
    </div>
  );
}
