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

export const api = {
  getState: () => request("/state"),
  getForecast: (hours = 6) => request(`/forecast?hours=${hours}`),
  getDecision: () => request("/decision"),
  logDecision: () => request("/decision/log", { method: "POST" }),
  getHistory: (limit = 20) => request(`/history?limit=${limit}`),
  getScenarios: () => request("/scenarios"),
  setScenario: (scenario) =>
    request("/scenario", { method: "POST", body: JSON.stringify({ scenario }) }),
  tick: (steps = 1) => request("/tick", { method: "POST", body: JSON.stringify({ steps }) }),
};
