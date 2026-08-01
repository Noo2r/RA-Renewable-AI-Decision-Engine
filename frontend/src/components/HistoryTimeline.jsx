const ACTION_LABELS = {
  battery_charge: "Store in Battery",
  water_pumping: "Water Pumping",
  sell_grid: "Sell to Grid",
  curtail: "Curtail",
};

export default function HistoryTimeline({ history }) {
  if (!history || history.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-200 mb-2">Decision Log</h2>
        <p className="text-sm text-slate-500">No decisions logged yet — execute a recommendation to see it here.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-200 mb-3">Decision Log</h2>
      <div className="flex flex-col gap-2 max-h-64 overflow-y-auto pr-1">
        {history.map((d) => (
          <div key={d.id} className="flex items-center justify-between text-sm border-b border-slate-800/60 pb-2 last:border-0">
            <div>
              <div className="text-slate-200">{ACTION_LABELS[d.action] || d.action}</div>
              <div className="text-xs text-slate-500">
                {new Date(d.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
              </div>
            </div>
            <div className="text-right">
              <div className="text-emerald-400">{d.expected_value_egp.toFixed(1)} EGP</div>
              <div className="text-xs text-slate-500">{d.co2_avoided_kg.toFixed(1)} kg CO2</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
