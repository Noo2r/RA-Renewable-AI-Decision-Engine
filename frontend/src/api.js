const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status}`);
  }
  return res.json();
}

function withStation(params, stationId) {
  const search = new URLSearchParams(params);
  if (stationId) search.set("station_id", stationId);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  getStations: () => request("/stations"),
  getState: (stationId) => request(`/state${withStation({}, stationId)}`),
  getForecast: (hours = 6, stationId) => request(`/forecast${withStation({ hours }, stationId)}`),
  getDecision: (stationId) => request(`/decision${withStation({}, stationId)}`),
  logDecision: (stationId) =>
    request(`/decision/log${withStation({}, stationId)}`, { method: "POST" }),
  getHistory: (limit = 20, stationId) => request(`/history${withStation({ limit }, stationId)}`),
  getScenarios: () => request("/scenarios"),
  setScenario: (scenario) =>
    request("/scenario", { method: "POST", body: JSON.stringify({ scenario }) }),
  tick: (steps = 1) => request("/tick", { method: "POST", body: JSON.stringify({ steps }) }),
};
