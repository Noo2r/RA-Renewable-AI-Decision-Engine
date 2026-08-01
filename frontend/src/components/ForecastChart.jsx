import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function fmt(v) {
  return v == null ? "—" : `${v.toFixed(1)} kW`;
}

function ConfidencePill({ label, value }) {
  if (value == null) {
    return (
      <div className="flex flex-col items-center px-2">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
        <span className="text-xs text-slate-600">n/a</span>
      </div>
    );
  }
  const color = value >= 90 ? "text-emerald-400" : value >= 70 ? "text-amber-400" : "text-rose-400";
  return (
    <div className="flex flex-col items-center px-2">
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
      <span className={`text-sm font-semibold ${color}`}>{value.toFixed(0)}%</span>
    </div>
  );
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  const isForecast = row.solarForecast != null || row.windForecast != null || row.demandForecast != null;

  const line = (name, actualKey, forecastKey, lowerKey, upperKey, confKey, methodKey) => {
    const actual = row[actualKey];
    const fc = row[forecastKey];
    if (actual == null && fc == null) return null;
    if (methodKey && row[methodKey] === "structural_zero") {
      return (
        <div key={name} className="text-slate-500">
          {name}: structurally unavailable (0 kW)
        </div>
      );
    }
    if (fc != null) {
      const lo = row[lowerKey];
      const hi = row[upperKey];
      const conf = row[confKey];
      return (
        <div key={name} className="text-slate-200">
          {name}: {fmt(fc)}
          {lo != null && hi != null && (
            <span className="text-slate-500"> (est. range {fmt(lo)}–{fmt(hi)})</span>
          )}
          {conf != null && <span className="text-slate-500"> · confidence {conf.toFixed(0)}%</span>}
        </div>
      );
    }
    return (
      <div key={name} className="text-slate-200">
        {name} (actual): {fmt(actual)}
      </div>
    );
  };

  return (
    <div className="bg-slate-950 border border-slate-700 rounded-lg p-3 text-xs space-y-1 max-w-xs">
      <div className="text-slate-400 font-medium">{label}</div>
      {line("Solar", "solarActual", "solarForecast", "solarLower", "solarUpper", "solarConfidence", "solarMethod")}
      {line("Wind", "windActual", "windForecast", "windLower", "windUpper", "windConfidence", "windMethod")}
      {line("Demand", "demandActual", "demandForecast", "demandLower", "demandUpper", "demandConfidence")}
      {isForecast && (
        <div className="text-slate-500 pt-1 border-t border-slate-800">Estimated forecast range, not a guarantee.</div>
      )}
    </div>
  );
}

export default function ForecastChart({ forecast }) {
  if (!forecast) return null;
  const { history, forecast: futurePoints, model_quality } = forecast;

  const solarAvailable = !futurePoints.length || futurePoints[0].solar_method !== "structural_zero";
  const windAvailable = !futurePoints.length || futurePoints[0].wind_method !== "structural_zero";

  const historyData = history.map((h) => ({
    time: formatTime(h.timestamp),
    solarActual: h.actual_solar_kw,
    windActual: h.actual_wind_kw,
    demandActual: h.actual_demand_kw,
  }));

  const nowLabel = historyData.length ? historyData[historyData.length - 1].time : null;
  const lastHistory = history[history.length - 1];
  const bridge = lastHistory
    ? [{
        time: nowLabel,
        solarActual: lastHistory.actual_solar_kw,
        windActual: lastHistory.actual_wind_kw,
        demandActual: lastHistory.actual_demand_kw,
        solarForecast: lastHistory.actual_solar_kw,
        windForecast: lastHistory.actual_wind_kw,
        demandForecast: lastHistory.actual_demand_kw,
      }]
    : [];

  const futureData = futurePoints.map((f) => ({
    time: formatTime(f.timestamp),
    solarForecast: f.solar_kw,
    solarLower: f.solar_lower_kw,
    solarUpper: f.solar_upper_kw,
    solarConfidence: f.solar_confidence_pct,
    solarMethod: f.solar_method,
    windForecast: f.wind_kw,
    windLower: f.wind_lower_kw,
    windUpper: f.wind_upper_kw,
    windConfidence: f.wind_confidence_pct,
    windMethod: f.wind_method,
    demandForecast: f.demand_kw,
    demandLower: f.demand_lower_kw,
    demandUpper: f.demand_upper_kw,
    demandConfidence: f.demand_confidence_pct,
  }));

  const data = [...historyData, ...bridge, ...futureData];
  const nextHour = futurePoints[3] || futurePoints[futurePoints.length - 1]; // ~T+1h (4 steps @15min)

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Component Forecast (next 6h)</h2>
        {model_quality && (
          <span className="text-xs text-slate-500">
            Validation MAE — solar {model_quality.solar_mae_kw ?? "n/a"} · wind {model_quality.wind_mae_kw ?? "n/a"} ·
            {" "}demand {model_quality.demand_mae_kw} kW
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
          <YAxis stroke="#64748b" fontSize={12} label={{ value: "kW", angle: -90, position: "insideLeft", fill: "#64748b" }} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          {nowLabel && <ReferenceLine x={nowLabel} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: "now", fill: "#f59e0b", fontSize: 12 }} />}

          {solarAvailable && (
            <>
              <Line type="monotone" dataKey="solarActual" name="Solar (actual)" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="solarForecast" name="Solar (forecast)" stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls={false} />
            </>
          )}
          {windAvailable && (
            <>
              <Line type="monotone" dataKey="windActual" name="Wind (actual)" stroke="#38bdf8" strokeWidth={2} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="windForecast" name="Wind (forecast)" stroke="#38bdf8" strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls={false} />
            </>
          )}
          <Line type="monotone" dataKey="demandActual" name="Demand (actual)" stroke="#a78bfa" strokeWidth={2} dot={false} connectNulls={false} />
          <Line type="monotone" dataKey="demandForecast" name="Demand (forecast)" stroke="#a78bfa" strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>

      {!solarAvailable && (
        <div className="text-xs text-slate-500 mt-1">Solar: structurally unavailable at this station (0 kW capacity).</div>
      )}
      {!windAvailable && (
        <div className="text-xs text-slate-500 mt-1">Wind: structurally unavailable at this station (0 kW capacity).</div>
      )}

      {nextHour && (
        <div className="mt-3 pt-3 border-t border-slate-800">
          <div className="text-xs text-slate-500 mb-1">Next-Hour Forecast Confidence (model-confidence score, not a probability)</div>
          <div className="flex flex-wrap">
            <ConfidencePill label="Solar" value={nextHour.solar_method === "structural_zero" ? null : nextHour.solar_confidence_pct} />
            <ConfidencePill label="Wind" value={nextHour.wind_method === "structural_zero" ? null : nextHour.wind_confidence_pct} />
            <ConfidencePill label="Demand" value={nextHour.demand_confidence_pct} />
            <ConfidencePill label="Net Balance" value={nextHour.net_balance_confidence_pct} />
          </div>
        </div>
      )}
    </div>
  );
}
