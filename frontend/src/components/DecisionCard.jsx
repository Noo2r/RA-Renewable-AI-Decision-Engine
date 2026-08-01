const ACTION_LABELS = {
  battery_charge: "Store in Battery",
  water_pumping: "Run Water Pumping / Desalination",
  sell_grid: "Sell to Grid",
  curtail: "Curtail",
};

const ACTION_COLORS = {
  battery_charge: "bg-emerald-500",
  water_pumping: "bg-cyan-500",
  sell_grid: "bg-amber-500",
  curtail: "bg-slate-500",
};

export default function DecisionCard({ decision, onExecute, executing, lastLogged }) {
  if (!decision) return null;
  const top = decision.recommended;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Recommended Decision</h2>
        <span className={`text-xs px-2 py-1 rounded-full text-white ${ACTION_COLORS[top.action]}`}>
          {ACTION_LABELS[top.action] || top.action}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-lg font-semibold text-slate-100">{top.expected_kwh.toFixed(1)} kWh</div>
          <div className="text-xs text-slate-500">Energy</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-emerald-400">{top.expected_value_egp.toFixed(1)} EGP</div>
          <div className="text-xs text-slate-500">Expected Value</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-sky-400">{top.co2_avoided_kg.toFixed(1)} kg</div>
          <div className="text-xs text-slate-500">CO2 Avoided</div>
        </div>
      </div>

      <p className="text-sm text-slate-300 leading-relaxed bg-slate-950/60 border border-slate-800 rounded-lg p-3">
        {top.explanation}
      </p>

      <button
        onClick={onExecute}
        disabled={executing}
        className="self-start px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium transition"
      >
        {executing ? "Logging…" : "Execute & Log Decision"}
      </button>
      {lastLogged && (
        <span className="text-xs text-emerald-400">Logged decision #{lastLogged.id} — {ACTION_LABELS[lastLogged.logged.action]}</span>
      )}

      <div className="border-t border-slate-800 pt-3">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">All ranked options</h3>
        <div className="flex flex-col gap-2">
          {decision.ranked_actions.map((a) => (
            <div key={a.action} className="flex items-center justify-between text-sm">
              <span className="text-slate-300">{ACTION_LABELS[a.action] || a.action}</span>
              <span className="text-slate-500">
                {a.expected_value_egp.toFixed(1)} EGP · score {a.score.toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
