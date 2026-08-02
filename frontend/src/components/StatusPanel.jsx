function Stat({ label, value, sub, accent }) {
  return (
    <div className="bg-ra-surface border border-ra-border-soft rounded-xl p-4 flex flex-col gap-1 hover:border-ra-border transition">
      <span className="text-xs uppercase tracking-wide text-ra-text-muted">{label}</span>
      <span className={`text-2xl font-semibold ${accent || "text-ra-text"}`}>{value}</span>
      {sub && <span className="text-xs text-ra-text-muted">{sub}</span>}
    </div>
  );
}

export default function StatusPanel({ state }) {
  if (!state) return null;
  const { reading, surplus_kw, generation_kw } = state;
  const surplusPositive = surplus_kw >= 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Stat
        label="Generation"
        value={`${generation_kw.toFixed(1)} kW`}
        sub={`Solar ${reading.solar_kw.toFixed(1)} · Wind ${reading.wind_kw.toFixed(1)}`}
      />
      <Stat label="Demand" value={`${reading.demand_kw.toFixed(1)} kW`} />
      <Stat
        label={surplusPositive ? "Surplus" : "Deficit"}
        value={`${Math.abs(surplus_kw).toFixed(1)} kW`}
        accent={surplusPositive ? "text-emerald-400" : "text-rose-400"}
      />
      <Stat
        label="Battery SoC"
        value={`${reading.battery_soc.toFixed(0)}%`}
        sub={`${reading.battery_soc >= 90 ? "Nearly full" : reading.battery_soc <= 10 ? "Low" : "Healthy"}`}
      />
      <Stat label="Grid Price" value={`${reading.price_egp.toFixed(2)} EGP/kWh`} />
      <Stat label="Cloud Cover" value={`${(reading.cloud_cover * 100).toFixed(0)}%`} />
      <Stat label="Wind Speed" value={`${reading.wind_speed.toFixed(1)} m/s`} />
      <Stat
        label="Simulated Time"
        value={new Date(reading.timestamp).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })}
      />
    </div>
  );
}
