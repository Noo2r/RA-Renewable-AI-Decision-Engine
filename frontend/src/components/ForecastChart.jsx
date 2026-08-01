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

export default function ForecastChart({ forecast }) {
  if (!forecast) return null;
  const { history, forecast: futurePoints, model_quality } = forecast;

  const historyData = history.map((h) => ({
    time: formatTime(h.timestamp),
    actual: h.actual_surplus_kw,
    forecast: null,
  }));

  const nowLabel = historyData.length ? historyData[historyData.length - 1].time : null;
  const bridge = history.length
    ? [{ time: nowLabel, actual: history[history.length - 1].actual_surplus_kw, forecast: history[history.length - 1].actual_surplus_kw }]
    : [];

  const futureData = futurePoints.map((f) => ({
    time: formatTime(f.timestamp),
    actual: null,
    actualLater: f.actual_surplus_kw,
    forecast: f.forecast_surplus_kw,
  }));

  const data = [...historyData, ...bridge, ...futureData];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-slate-200">Surplus Forecast (next 6h)</h2>
        {model_quality?.generation_mae_kw != null && (
          <span className="text-xs text-slate-500">
            Model MAE — gen {model_quality.generation_mae_kw} kW · demand {model_quality.demand_mae_kw} kW
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
          <YAxis stroke="#64748b" fontSize={12} label={{ value: "kW", angle: -90, position: "insideLeft", fill: "#64748b" }} />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
            labelStyle={{ color: "#cbd5e1" }}
          />
          <Legend />
          {nowLabel && <ReferenceLine x={nowLabel} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: "now", fill: "#f59e0b", fontSize: 12 }} />}
          <Line type="monotone" dataKey="actual" name="Actual surplus" stroke="#38bdf8" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="forecast" name="Forecast surplus" stroke="#a78bfa" strokeWidth={2} strokeDasharray="5 3" dot={false} />
          <Line type="monotone" dataKey="actualLater" name="Actual (once known)" stroke="#38bdf8" strokeWidth={1} strokeOpacity={0.4} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
