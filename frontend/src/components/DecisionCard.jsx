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
  water_pumping: "bg-teal-500",
  sell_grid: "bg-amber-500",
  grid_import: "bg-rose-500",
  curtail: "bg-slate-500",
};

const MODE_STYLES = {
  surplus: "bg-emerald-950 text-emerald-300 border-emerald-800",
  deficit: "bg-rose-950 text-rose-300 border-rose-800",
};

// Priority badges use an ascending warm-intensity gradient (distinct from
// the map's simplified 3-color status) so all four raw priority values
// stay visually distinguishable: normal=neutral, medium=soft gold,
// high=amber, critical=red.
const PRIORITY_STYLES = {
  critical: "bg-rose-950 text-rose-300 border-rose-800",
  high: "bg-amber-950 text-amber-300 border-amber-800",
  medium: "bg-yellow-950 text-yellow-300 border-yellow-800",
  normal: "bg-ra-surface-hover text-ra-text-secondary border-ra-border",
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
  const co2Color = isGridImport ? "text-rose-400" : "text-emerald-400";

  return (
    <div className="grid grid-cols-3 gap-3 text-center">
      <div>
        <div className="text-lg font-semibold text-ra-text">{fmtKw(action.amount_kw)}</div>
        <div className="text-xs text-ra-text-muted">Recommended Amount</div>
      </div>
      <div>
        <div className={`text-lg font-semibold ${moneyColor}`}>{moneyValue.toFixed(1)} EGP</div>
        <div className="text-xs text-ra-text-muted">{moneyLabel}</div>
      </div>
      <div>
        <div className={`text-lg font-semibold ${co2Color}`}>{co2Value.toFixed(1)} kg</div>
        <div className="text-xs text-ra-text-muted">{co2Label}</div>
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
    <div className="bg-ra-surface border border-ra-border-soft rounded-xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-ra-primary">Recommended Decision</h2>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs px-2 py-1 rounded-full border capitalize ${MODE_STYLES[decision.mode] || "border-ra-border text-ra-text-secondary"}`}>
            {decision.mode}
          </span>
          <span className={`text-xs px-2 py-1 rounded-full border capitalize ${PRIORITY_STYLES[decision.priority] || "border-ra-border text-ra-text-secondary"}`}>
            {decision.priority}
          </span>
          <span className={`text-xs px-2 py-1 rounded-full text-white ${ACTION_COLORS[top.action] || "bg-slate-600"}`}>
            {ACTION_LABELS[top.action] || top.action}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs bg-ra-bg-elevated border border-ra-border-soft rounded-lg p-3">
        <div>
          <div className="text-ra-text-muted uppercase tracking-wide text-[10px] mb-1">Before</div>
          <div className="text-ra-text-secondary">Generation {fmtKw(decision.before.generation_kw)} · Demand {fmtKw(decision.before.demand_kw)}</div>
          <div className="text-ra-text-secondary">Net Balance {fmtKw(decision.before.net_balance_kw)} · Battery {fmtPct(decision.before.battery_soc_pct)}</div>
        </div>
        <div>
          <div className="text-ra-text-muted uppercase tracking-wide text-[10px] mb-1">After (projected)</div>
          <div className="text-ra-text-secondary">Net Balance {fmtKw(decision.after.net_balance_kw)}</div>
          <div className="text-ra-text-secondary">Battery {fmtPct(decision.after.battery_soc_pct)}</div>
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

      <div className="bg-ra-bg-elevated border border-ra-border-soft rounded-lg p-3">
        {top.reason && <p className="text-xs text-ra-text-muted mb-1.5">{top.reason}</p>}
        <p className="text-sm text-ra-text-secondary leading-relaxed">{top.explanation}</p>
      </div>

      <button
        onClick={onExecute}
        disabled={executing}
        className="self-start px-4 py-2 rounded-lg bg-ra-primary hover:bg-ra-primary-strong text-ra-bg font-semibold text-sm transition shadow-[0_0_10px_var(--ra-primary-glow)] hover:shadow-[0_0_16px_var(--ra-primary-glow)] disabled:bg-ra-surface-hover disabled:text-ra-text-muted disabled:shadow-none disabled:cursor-not-allowed"
      >
        {executing ? "Logging…" : "Execute & Log Decision"}
      </button>
      {lastLogged && (
        <span className="text-xs text-emerald-400">Logged decision #{lastLogged.id} — {ACTION_LABELS[lastLogged.logged.action]}</span>
      )}

      <div className="border-t border-ra-border-soft pt-3">
        <h3 className="text-xs uppercase tracking-wide text-ra-text-muted mb-2">All ranked options</h3>
        <div className="flex flex-col gap-2">
          {decision.ranked_actions.map((a) => {
            const isGridImport = a.action === "grid_import";
            const money = isGridImport ? -a.expected_cost_egp : a.expected_value_egp;
            return (
              <div key={a.action} className="flex items-center justify-between text-sm">
                <span className="text-ra-text-secondary">{ACTION_LABELS[a.action] || a.action}</span>
                <span className={money < 0 ? "text-rose-400" : "text-ra-text-muted"}>
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
