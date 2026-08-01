const ACTION_LABELS = {
  battery_charge: "Battery Charge",
  battery_discharge: "Battery Discharge",
  water_pumping: "Water Pumping / Desalination",
  sell_grid: "Sell to Grid",
  grid_import: "Grid Support",
  curtail: "Curtailment",
};

const ACTION_COLORS = {
  battery_charge: "bg-emerald-500",
  battery_discharge: "bg-violet-500",
  water_pumping: "bg-cyan-500",
  sell_grid: "bg-amber-500",
  grid_import: "bg-rose-500",
  curtail: "bg-slate-500",
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

function fmtKw(v) {
  return v == null ? "—" : `${v.toFixed(1)} kW`;
}

function fmtPct(v) {
  return v == null ? "—" : `${v.toFixed(0)}%`;
}

function ActionStat({ action }) {
  // grid_import is a cost/emission action; every other action (including
  // battery_discharge) is framed as value/avoided, same convention the
  // surplus actions have always used. Values come straight from the API --
  // no calculation happens here.
  const isGridImport = action.action === "grid_import";
  const moneyLabel = isGridImport ? "Expected Cost" : "Expected Value";
  const moneyValue = isGridImport ? action.expected_cost_egp : action.expected_value_egp;
  const moneyColor = isGridImport ? "text-rose-400" : "text-emerald-400";
  const co2Label = isGridImport ? "CO2 Emitted" : "CO2 Avoided";
  const co2Value = isGridImport ? action.co2_emitted_kg : action.co2_avoided_kg;
  const co2Color = isGridImport ? "text-rose-400" : "text-sky-400";

  return (
    <div className="grid grid-cols-3 gap-3 text-center">
      <div>
        <div className="text-lg font-semibold text-slate-100">{fmtKw(action.amount_kw)}</div>
        <div className="text-xs text-slate-500">Recommended Amount</div>
      </div>
      <div>
        <div className={`text-lg font-semibold ${moneyColor}`}>{moneyValue.toFixed(1)} EGP</div>
        <div className="text-xs text-slate-500">{moneyLabel}</div>
      </div>
      <div>
        <div className={`text-lg font-semibold ${co2Color}`}>{co2Value.toFixed(1)} kg</div>
        <div className="text-xs text-slate-500">{co2Label}</div>
      </div>
    </div>
  );
}

export default function DecisionCard({ decision, onExecute, executing, lastLogged }) {
  if (!decision) return null;
  const top = decision.recommended;
  const isDeficit = decision.mode === "deficit";
  const hasRemainingDeficit = isDeficit && decision.remaining_deficit_kw > 0.05;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-slate-200">Recommended Decision</h2>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs px-2 py-1 rounded-full border capitalize ${MODE_STYLES[decision.mode] || "border-slate-700 text-slate-300"}`}>
            {decision.mode}
          </span>
          <span className={`text-xs px-2 py-1 rounded-full border capitalize ${PRIORITY_STYLES[decision.priority] || "border-slate-700 text-slate-300"}`}>
            {decision.priority}
          </span>
          <span className={`text-xs px-2 py-1 rounded-full text-white ${ACTION_COLORS[top.action] || "bg-slate-600"}`}>
            {ACTION_LABELS[top.action] || top.action}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs bg-slate-950/60 border border-slate-800 rounded-lg p-3">
        <div>
          <div className="text-slate-500 uppercase tracking-wide text-[10px] mb-1">Before</div>
          <div className="text-slate-300">Generation {fmtKw(decision.before.generation_kw)} · Demand {fmtKw(decision.before.demand_kw)}</div>
          <div className="text-slate-300">Net Balance {fmtKw(decision.before.net_balance_kw)} · Battery {fmtPct(decision.before.battery_soc_pct)}</div>
        </div>
        <div>
          <div className="text-slate-500 uppercase tracking-wide text-[10px] mb-1">After (projected)</div>
          <div className="text-slate-300">Net Balance {fmtKw(decision.after.net_balance_kw)}</div>
          <div className="text-slate-300">Battery {fmtPct(decision.after.battery_soc_pct)}</div>
        </div>
      </div>

      {hasRemainingDeficit && (
        <div className="text-xs text-rose-300 bg-rose-950/60 border border-rose-900 rounded-lg px-3 py-2">
          Remaining deficit: <strong>{fmtKw(decision.remaining_deficit_kw)}</strong>
          {decision.secondary_action && (
            <> — {ACTION_LABELS[decision.secondary_action] || decision.secondary_action} needed for {fmtKw(decision.secondary_amount_kw)}</>
          )}
        </div>
      )}

      <ActionStat action={top} />

      <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
        {top.reason && <p className="text-xs text-slate-500 mb-1.5">{top.reason}</p>}
        <p className="text-sm text-slate-300 leading-relaxed">{top.explanation}</p>
      </div>

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
          {decision.ranked_actions.map((a) => {
            const isGridImport = a.action === "grid_import";
            const money = isGridImport ? -a.expected_cost_egp : a.expected_value_egp;
            return (
              <div key={a.action} className="flex items-center justify-between text-sm">
                <span className="text-slate-300">{ACTION_LABELS[a.action] || a.action}</span>
                <span className={money < 0 ? "text-rose-400" : "text-slate-500"}>
                  {money.toFixed(1)} EGP · score {a.score.toFixed(1)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
