import { useMemo, useState } from "react";
import { createGeoProjection, polygonsToPathD } from "../lib/mapProjection";
import { getEgyptPolygons } from "../lib/egyptGeometry";

// SVG canvas the country geometry is fit into. Chosen close to the real
// Egypt bounding box's aspect ratio (lon span ~12.2 deg, lat span ~9.7
// deg) so the fitted map uses most of the canvas without much empty
// padding on either axis; createGeoProjection() still centers/pads it
// exactly regardless of the exact ratio chosen here.
const VIEWBOX = { width: 380, height: 320 };
const MAP_PADDING = 18;

// Small hardcoded, approximate (latitude, longitude) waypoints roughly
// following the Nile from southern Egypt (near Aswan) north through the
// characteristic Qena/Sohag/Asyut bend, Cairo, and into the Delta. This is
// a decorative sketch for visual recognizability, NOT a surveyed river
// course -- it is not sourced from any river dataset.
const NILE_WAYPOINTS_LATLON = [
  [23.97, 32.87], // near Aswan
  [24.70, 32.90],
  [25.68, 32.64], // Luxor
  [26.55, 31.70], // westward bend near Qena/Sohag
  [27.18, 31.19], // Asyut
  [28.11, 30.75], // Minya
  [29.07, 31.10], // Beni Suef
  [30.04, 31.24], // Cairo
  [30.90, 31.00],
  [31.45, 30.60], // toward the Delta / Mediterranean
];

const SHORT_LABELS = {
  "solar-01": "South Solar",
  "wind-01": "Gulf Wind",
  "hybrid-01": "Hybrid Hub",
};

// Per-station label offset (dx, dy in SVG units) from marker center --
// handled manually since there are exactly three known, fixed stations;
// this is not a general label-collision system.
const LABEL_OFFSETS = {
  "solar-01": { dx: 12, dy: 4 },
  "wind-01": { dx: 12, dy: -10 },
  "hybrid-01": { dx: -12, dy: 4, anchor: "end" },
};

const STATUS_COLORS = {
  normal: "#10b981", // green
  warning: "#eab308", // yellow
  critical: "#ef4444", // red
  unknown: "#64748b", // neutral gray fallback
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

// Tiny inline energy-type glyphs (no icon library, no emoji -- emoji glyph
// shapes vary across operating systems). Color is fixed dark so it reads
// against every status color; the STATUS color communicates operational
// status, this symbol communicates energy type only.
function EnergySymbol({ energyType }) {
  const stroke = "#14120b";
  if (energyType === "solar") {
    return (
      <g stroke={stroke} strokeWidth="1" strokeLinecap="round">
        <circle r="2" fill={stroke} stroke="none" />
        <line x1="0" y1="-5.2" x2="0" y2="-3.4" />
        <line x1="0" y1="3.4" x2="0" y2="5.2" />
        <line x1="-5.2" y1="0" x2="-3.4" y2="0" />
        <line x1="3.4" y1="0" x2="5.2" y2="0" />
        <line x1="-3.7" y1="-3.7" x2="-2.4" y2="-2.4" />
        <line x1="2.4" y1="2.4" x2="3.7" y2="3.7" />
        <line x1="-3.7" y1="3.7" x2="-2.4" y2="2.4" />
        <line x1="2.4" y1="-2.4" x2="3.7" y2="-3.7" />
      </g>
    );
  }
  if (energyType === "wind") {
    return (
      <g stroke={stroke} strokeWidth="1" strokeLinecap="round">
        <circle r="0.9" fill={stroke} stroke="none" />
        <line x1="0" y1="0" x2="0" y2="-5.2" />
        <line x1="0" y1="0" x2="4.5" y2="2.6" />
        <line x1="0" y1="0" x2="-4.5" y2="2.6" />
        <line x1="0" y1="1" x2="0" y2="5.2" strokeWidth="0.8" />
      </g>
    );
  }
  // hybrid: a compact sun-on-top / turbine-below combination
  return (
    <g stroke={stroke} strokeWidth="1" strokeLinecap="round">
      <circle r="1.4" fill={stroke} stroke="none" />
      <line x1="0" y1="-5.2" x2="0" y2="-3.2" />
      <line x1="-3.4" y1="-3.4" x2="-2.1" y2="-2.1" />
      <line x1="3.4" y1="-3.4" x2="2.1" y2="-2.1" />
      <line x1="0" y1="0" x2="3.9" y2="3.3" />
      <line x1="0" y1="0" x2="-3.9" y2="3.3" />
      <line x1="0" y1="1" x2="0" y2="5.2" strokeWidth="0.8" />
    </g>
  );
}

function Legend() {
  return (
    <div className="flex flex-col gap-1 text-xs text-ra-text-secondary">
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
      <p className="text-[10px] text-ra-text-muted">
        Status is based on the current RA recommendation priority, not equipment health or a failure diagnosis.
        Marker symbols show energy type only.
      </p>
    </div>
  );
}

function StationPreview({ station }) {
  if (!station) {
    return (
      <div className="text-xs text-ra-text-muted border border-ra-border-soft rounded-lg p-3">
        Hover, focus, or select a marker to see station details.
      </div>
    );
  }
  const status = station.status || "unknown";
  return (
    <div className="border border-ra-border-soft rounded-lg p-3 flex flex-col gap-2 text-xs">
      <div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-base font-semibold text-ra-text leading-tight">{station.name || station.station_id}</span>
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide shrink-0"
            style={{ background: `${STATUS_COLORS[status] || STATUS_COLORS.unknown}22`, color: STATUS_COLORS[status] || STATUS_COLORS.unknown }}
          >
            {station.status_label || "Unknown"}
          </span>
        </div>
        <div className="text-ra-text-muted capitalize">{station.energy_type || "unknown"} station</div>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-ra-text-secondary">
        <span>Generation: {fmtKw(station.generation_kw)}</span>
        <span>Demand: {fmtKw(station.demand_kw)}</span>
        <span>Net Balance: {fmtKw(station.net_balance_kw)}</span>
        <span>Battery SoC: {fmtPct(station.battery_soc_pct)}</span>
        <span className="capitalize">Mode: {station.mode || "—"}</span>
        <span className="capitalize">Priority: {station.priority || "—"}</span>
      </div>

      <div className="text-ra-text-muted border-t border-ra-border-soft pt-2">
        Recommended: <span className="text-ra-text">{ACTION_LABELS[station.recommended_action] || station.recommended_action || "—"}</span>
      </div>
    </div>
  );
}

export default function EgyptMap({ stations, selectedStationId, onSelectStation, loading, error, onRetry }) {
  const [previewId, setPreviewId] = useState(null);

  // Geometry + projection are derived only from the bundled asset and the
  // fixed viewBox -- neither depends on station/overview data, so they're
  // computed once and reused across re-renders (ticks/autoplay would
  // otherwise re-walk ~3.5k boundary coordinate pairs every few seconds).
  const { polygons: egyptPolygons, error: geometryError } = useMemo(() => getEgyptPolygons(), []);
  const projection = useMemo(
    () => (egyptPolygons.length > 0 ? createGeoProjection(egyptPolygons, VIEWBOX.width, VIEWBOX.height, MAP_PADDING) : null),
    [egyptPolygons]
  );
  const egyptPathD = useMemo(
    () => (projection ? polygonsToPathD(egyptPolygons, projection.project) : ""),
    [egyptPolygons, projection]
  );
  const nilePathD = useMemo(() => {
    if (!projection) return "";
    const pts = NILE_WAYPOINTS_LATLON.map(([lat, lon]) => projection.project(lat, lon)).filter(Boolean);
    if (pts.length < 2) return "";
    const [first, ...rest] = pts;
    return `M ${first.x.toFixed(1)} ${first.y.toFixed(1)} ` + rest.map((p) => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  }, [projection]);

  const safeStations = Array.isArray(stations) ? stations : [];
  const previewStation =
    safeStations.find((s) => s.station_id === previewId) ||
    safeStations.find((s) => s.station_id === selectedStationId) ||
    null;

  const showStaleMapWithWarning = error && safeStations.length > 0;
  const showFullError = error && safeStations.length === 0;
  const showGeometryError = !error && (geometryError || !projection) && safeStations.length >= 0;

  return (
    <div className="bg-ra-surface border border-ra-border-soft rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-1">
        <h2 className="text-sm font-semibold text-ra-primary">Egypt Station Map</h2>
        <span className="text-[10px] uppercase tracking-wide text-ra-text-muted">Demo Map — approximate station locations</span>
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
        <div className="text-xs text-ra-text-muted border border-ra-border-soft rounded-lg p-6 text-center animate-pulse">
          Loading station map…
        </div>
      )}

      {!showFullError && safeStations.length === 0 && !loading && (
        <div className="text-xs text-ra-text-muted border border-ra-border-soft rounded-lg p-6 text-center">
          No station data available.
        </div>
      )}

      {!showFullError && safeStations.length > 0 && showGeometryError && (
        <div className="text-xs bg-rose-950 border border-rose-800 text-rose-300 rounded-lg p-3">
          Could not render the Egypt boundary ({geometryError || "unknown geometry error"}). Station markers are unavailable
          until this is fixed.
        </div>
      )}

      {!showFullError && !showGeometryError && safeStations.length > 0 && (
        <div className="flex flex-col md:flex-row gap-4 items-start">
          <div className="w-full md:w-[40%] md:max-w-[420px] shrink-0">
            <svg
              viewBox={`0 0 ${VIEWBOX.width} ${VIEWBOX.height}`}
              role="img"
              aria-labelledby="egypt-map-title egypt-map-desc"
              className="w-full h-auto"
            >
              <title id="egypt-map-title">Map of Egypt showing RA demo station locations</title>
              <desc id="egypt-map-desc">
                An outline of Egypt, including the Sinai Peninsula, traced from a bundled boundary file, with three
                interactive markers for solar-01, wind-01, and hybrid-01, colored green, yellow, or red by each
                station&apos;s current recommendation priority.
              </desc>

              <path
                d={egyptPathD}
                fill="#241f16"
                stroke="#7a6428"
                strokeWidth="1.25"
                strokeLinejoin="round"
                fillRule="evenodd"
                aria-hidden="true"
              />

              {/* The Nile intentionally stays blue -- it represents water,
                  not the brand accent. */}
              {nilePathD && (
                <path
                  d={nilePathD}
                  fill="none"
                  stroke="#38bdf8"
                  strokeWidth="1.1"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity="0.45"
                  aria-hidden="true"
                />
              )}

              {safeStations.map((station) => {
                const lat = station.latitude;
                const lon = station.longitude;
                const point = projection.project(lat, lon);
                if (!point) return null;
                const { x, y } = point;
                const status = station.status && STATUS_COLORS[station.status] ? station.status : "unknown";
                const isSelected = station.station_id === selectedStationId;
                const label = `${station.name || station.station_id}, ${station.energy_type || "unknown"} station, status ${
                  station.status_label || "Unknown"
                }${isSelected ? ", currently selected" : ""}`;
                const shortLabel = SHORT_LABELS[station.station_id];
                const offset = LABEL_OFFSETS[station.station_id] || { dx: 12, dy: 4 };

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
                    {shortLabel && (
                      <text
                        x={offset.dx}
                        y={offset.dy}
                        textAnchor={offset.anchor || "start"}
                        fontSize="8.5"
                        fontWeight="600"
                        fill="#fff8dc"
                        stroke="#14120b"
                        strokeWidth="2.5"
                        paintOrder="stroke"
                        pointerEvents="none"
                        aria-hidden="true"
                      >
                        {shortLabel}
                      </text>
                    )}
                    {isSelected && <circle r="12.5" fill="none" stroke="#f6c744" strokeWidth="2" opacity="0.95" />}
                    {previewId === station.station_id && !isSelected && (
                      <circle r="12.5" fill="none" stroke="#facc15" strokeWidth="1.5" strokeDasharray="3 2" opacity="0.9" />
                    )}
                    <circle r="9" fill={STATUS_COLORS[status]} stroke="#14120b" strokeWidth="1.5" />
                    <EnergySymbol energyType={station.energy_type} />
                  </g>
                );
              })}
            </svg>
          </div>

          <div className="flex-1 min-w-[220px] flex flex-col gap-3">
            <Legend />
            <StationPreview station={previewStation} />
          </div>
        </div>
      )}
    </div>
  );
}
