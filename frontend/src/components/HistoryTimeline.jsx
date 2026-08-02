const ACTION_LABELS = {
  battery_charge: "Battery Charge",
  battery_discharge: "Battery Discharge",
  water_pumping: "Water Pumping",
  sell_grid: "Sell to Grid",
  grid_import: "Grid Support",
  curtail: "Curtailment",
};

export default function HistoryTimeline({ history }) {
  if (!history || history.length === 0) {
    return (
      <div className="bg-ra-surface border border-ra-border-soft rounded-xl p-4">
        <h2 className="text-sm font-semibold text-ra-primary mb-2">Decision Log</h2>
        <p className="text-sm text-ra-text-muted">No decisions logged yet — execute a recommendation to see it here.</p>
      </div>
    );
  }

  return (
    <div className="bg-ra-surface border border-ra-border-soft rounded-xl p-4">
      <h2 className="text-sm font-semibold text-ra-primary mb-3">Decision Log</h2>
      <div className="flex flex-col gap-2 max-h-64 overflow-y-auto pr-1">
        {history.map((d) => {
          const isGridImport = d.action === "grid_import";
          const money = isGridImport ? -(d.expected_cost_egp ?? 0) : d.expected_value_egp;
          const co2 = isGridImport ? (d.co2_emitted_kg ?? 0) : d.co2_avoided_kg;
          return (
            <div key={d.id} className="flex items-center justify-between text-sm border-b border-ra-border-soft pb-2 last:border-0">
              <div>
                <div className="text-ra-text">
                  {ACTION_LABELS[d.action] || d.action}
                  {d.mode && <span className="text-xs text-ra-text-muted capitalize"> · {d.mode}</span>}
                </div>
                <div className="text-xs text-ra-text-muted">
                  {new Date(d.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </div>
              </div>
              <div className="text-right">
                <div className={money < 0 ? "text-rose-400" : "text-emerald-400"}>{money.toFixed(1)} EGP</div>
                <div className="text-xs text-ra-text-muted">{co2.toFixed(1)} kg CO2{isGridImport ? " emitted" : " avoided"}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
