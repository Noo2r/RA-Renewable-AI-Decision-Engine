# RA — Renewable AI Decision Engine

RA turns renewable-energy readings into an explained, actionable recommendation
every 15 simulated minutes: **Prediction** (forecast solar/wind/demand with
confidence), **Decision** (rank battery/grid/flexible-load actions), **Explanation**
(a plain-language reason tracing back to the numbers on screen), and
**Simulation** (a side-effect-free What-If comparison).

RA is a **decision-support prototype**, not autonomous control — it never
sends a command to real equipment, and every screen says so. All station data
is **deterministic synthetic data**, seeded for reproducibility — not
measured data from a real facility (see `docs/RA_Final_Project_Documentation.md`,
Section 5, for the full disclosure and data-generation methodology).

Everything runs **locally, offline by default** — no external services or API
keys required. An optional LLM wording adapter for the assistant is disabled
unless explicitly configured (see [Notes on the "AI" in RA](#notes-on-the-ai-in-ra)).

There are **two front ends sharing one engine**: a FastAPI + React dashboard,
and a self-contained Jupyter notebook. Both import the same `ra_core/`
package, so they can never drift apart on numbers or logic.

## Full documentation

For the complete architecture, data methodology, validation results, and
business/technical presentation material, see:

- [`docs/RA_Final_Project_Documentation.md`](docs/RA_Final_Project_Documentation.md)
  (also available as [`.docx`](docs/RA_Final_Project_Documentation.docx) and
  [`.pdf`](docs/RA_Final_Project_Documentation.pdf) — all three contain the
  same content)
- [`docs/PRESENTATION_REFERENCE.md`](docs/PRESENTATION_REFERENCE.md) — business
  and technical presentation slide storylines

## Feature overview

- **Multi-station monitoring** — 3 demo stations (one solar, one wind, one
  hybrid), switchable from the dashboard, sharing one global scenario and
  simulated clock.
- **Egypt map** — all 3 stations at a glance, colored by the same priority
  the decision engine computes, rendered from a locally bundled GeoJSON
  asset (no external map tiles).
- **Component forecasting** — solar, wind, and demand forecast independently
  up to 6 hours ahead, each with an empirical uncertainty range and a
  model-confidence score.
- **Surplus and deficit decisions** — 6 possible actions (battery charge,
  water pumping, sell to grid, curtail, battery discharge, grid import),
  scored by economic + environmental value and ranked transparently.
- **What-If simulator** — compare a hypothetical solar/wind/demand/battery
  capacity change against the real baseline, without ever touching the real
  station configuration or logged history.
- **RA Assistant** — a deterministic, offline, grounded question-answering
  layer that explains current status, forecasts, decisions, station
  comparisons, and What-If results in plain language.
- **Solar Gold themed dashboard** — a polished, accessible dark UI built with
  React, Vite, Tailwind, and Recharts.

## Architecture

```
ra_core/              Shared core — no FastAPI/React dependency
  config.py             site + simulation constants
  stations.py            the 3-station registry (StationConfig)
  data_generator.py     deterministic synthetic time-series generator (per scenario/station)
  forecasting.py        per-component (solar/wind/demand) forecast with intervals + confidence
  decision_engine.py    surplus/deficit action scoring, ranking, and priority
  what_if.py             side-effect-free hypothetical station comparison
  assistant.py            deterministic intent classification + grounded answers
  kpi.py                 aggregates logged decisions into utilization/CO2/value KPIs (notebook-only)

backend/              FastAPI service (imports ra_core)
  app/
    config.py            re-exports ra_core.config + backend-only DB_PATH
    db.py                 SQLite persistence (readings, sim clock, decision log)
    seed.py               seeds all 4 scenarios x 3 stations on first run
    llm_adapter.py        optional, disabled-by-default LLM wording rewrite for the assistant
    main.py                REST API — 14 endpoints, see below

frontend/              React + Tailwind + Recharts dashboard (Vite), Solar Gold theme

notebook/              Jupyter notebook front end (imports ra_core directly, no backend/HTTP)
  RA_notebook_demo.ipynb  status/forecast/decision views + a What-If simulator + KPI summary

scripts/
  reset_demo.py          resets the running backend to a verified starting scenario/index
  smoke_test.py           read-only health check against a running backend (9 checks)

docs/                  Final project documentation (Markdown/DOCX/PDF) + presentation reference
```

Data flows one direction: synthetic generator → SQLite (backend) → forecasting
+ decision engine → presentation layer (REST API + dashboard, or notebook
widgets). Neither front end owns any calculation logic — `ra_core/` does, so
the dashboard and the notebook can never disagree on a number.

### Simulated clock

There's no real-time feed — instead a `current_index` pointer in SQLite marks
"now" inside a pre-generated 4-day, 15-minute-resolution series per scenario
(384 points). `POST /tick` advances it (used by the dashboard's "Advance" and
"Play Auto-Advance" controls). This makes the demo fully repeatable and lets
you scrub through simulated time without waiting in real time.

## Setup

### One-click (recommended)

```bash
python setup.py    # or setup.bat / setup.sh — creates backend/venv, installs both sides
python start.py    # or start.bat / start.sh — starts backend + frontend, opens the browser
```

`start.py` prints a readiness banner once both services are up:

```
RA backend ready: http://localhost:8000
RA API docs: http://localhost:8000/docs
RA dashboard ready: http://localhost:5173
Assistant mode: offline deterministic
Map mode: offline local GeoJSON
```

Press Ctrl+C to stop. If a backend or frontend is already running on the
expected port, `start.py` reuses it instead of starting a duplicate.

### Manual setup

#### 1. Backend (Python 3.10+)

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows; use "source venv/bin/activate" on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The database (`backend/ra.db`) is created and seeded automatically on first
startup — all 4 scenarios × 3 stations are generated and stored, no manual
steps needed.

#### 2. Frontend (Node 18+)

```bash
cd frontend
npm install
npm run dev
```

Open the printed local URL (default `http://localhost:5173`). The frontend
expects the API at `http://localhost:8000` (override with `VITE_API_URL`).

#### 3. Notebook (optional second front end)

```bash
cd notebook
python -m venv venv        # or reuse backend/venv, which already has these deps
venv\Scripts\activate
pip install -r requirements.txt
jupyter lab RA_notebook_demo.ipynb
```

No backend or frontend server needs to be running — the notebook generates
its own copy of the same deterministic dataset directly from `ra_core`.

### Resetting and smoke-testing a running demo

```bash
python scripts/reset_demo.py    # returns to the verified starting scenario/index
python scripts/smoke_test.py    # 9 read-only checks against the running backend
```

Both scripts exit non-zero on failure and never modify the database, scenario,
or decision history beyond what `reset_demo.py` explicitly does (a scenario
reset via the existing `POST /scenario` endpoint).

## API

14 REST endpoints (see `docs/RA_Final_Project_Documentation.md`, Appendix A,
for the full reference):

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness check |
| `/scenarios` | GET | List the 4 scenario presets |
| `/stations` | GET | List the 3 registered stations |
| `/stations/overview` | GET | Current snapshot for all 3 stations (map data) |
| `/scenario` | POST `{"scenario": "cloudy"}` | Switch scenario, resets the simulated clock |
| `/tick` | POST `{"steps": 1}` | Advance the simulated clock (1 step = 15 min) |
| `/state` | GET | Current reading for one station |
| `/forecast?hours=6` | GET | Component forecast (solar/wind/demand) for one station |
| `/decision` | GET | Ranked actions with expected kWh / EGP / CO2 and explanations |
| `/decision/log` | POST | Logs the current top recommendation to history |
| `/history?limit=20` | GET | Past logged decisions for one station |
| `/national/summary` | GET | Aggregated totals across all 3 stations |
| `/simulate` | POST | Side-effect-free What-If comparison |
| `/assistant/query` | POST | Grounded natural-language question answering |

## Demo script (3-5 minutes)

1. **Open the dashboard** (`http://localhost:5173`). It loads into a
   mid-morning **sunny day** on the Hybrid Energy Hub with ~18 kW of surplus
   already showing — generation, demand, battery SoC, price, and weather are
   all live, alongside the Egypt map showing all 3 stations at once.
2. **Point at the forecast chart.** Solid lines are actual history; dashed
   lines are the forecast for solar, wind, and demand independently, each
   with a shaded uncertainty range and a confidence score — call out the
   reported MAE (kW) as a concrete accuracy number.
3. **Point at the Recommended Decision card.** Read the explanation aloud —
   it names the exact surplus, battery headroom, current vs. forecast price,
   and the EGP/CO2 impact that produced the ranking. Show "All ranked
   options" underneath to prove it's a scored comparison, not a hard-coded
   answer.
4. **Click "Execute & Log Decision."** The action appears immediately in the
   Decision Log — the "surplus detected → forecast shown → decision
   recommended → outcome logged" loop RA exists to close.
5. **Open the What-If Simulator.** Try "what if battery capacity were +100%"
   on a station currently recommending grid import — watch the recommendation
   flip to battery discharge, with the avoided cost and emissions quantified.
6. **Ask the RA Assistant** "Why was this decision selected?" and get the
   same reasoning back in plain language, grounded in the current station's
   real numbers.
7. **Switch stations or scenarios** (e.g. to "Cloudy / Intermittent" or
   "High Wind") to show the engine adapting — different generation mix,
   different recommendation, different explanation — rather than always
   returning the same answer.

## Notes on the "AI" in RA

- **Forecasting**: a `GradientBoostingRegressor` per component (solar, wind,
  demand) per station, using time-of-day + weather features, validated
  against a chronological (never shuffled) 80/20 holdout split — reported
  honestly as `model_quality` in the `/forecast` response, not a claimed
  accuracy percentage.
- **Decision engine**: a transparent, rule-scored ranking (not a black box)
  over up to 6 actions, each valued in EGP + kg CO2 from a documented
  formula — every number in the explanation traces back to a value shown on
  the dashboard.
- **Assistant**: a deterministic keyword-based intent classifier and
  template-driven answer generator — no ML model, no embeddings, and no LLM
  call by default. An optional LLM wording rewrite exists
  (`RA_ASSISTANT_LLM_ENABLED=true` in a local `.env`, see `.env.example`) but
  is off unless explicitly configured, and can never change a number, a
  fact, or the recommendation — only rephrase the wording.

## Testing

```bash
pytest -q
```

295 automated tests across 12 files cover the API, forecasting, decision
engine (surplus and deficit), What-If isolation and validation, the
assistant, station registry integrity, and numerical edge cases (zero
battery capacity, zero demand, dataset-end forecasting, NaN/Infinity safety).

## Swapping the use case

The action list (`ra_core/decision_engine.py`) and the synthetic data knobs
(`ra_core/data_generator.py`, `ra_core/stations.py`) are intentionally
isolated from the API/db/frontend/notebook layers, so the surplus-use-case
or station roster can be re-targeted by editing shared `ra_core/` files —
both front ends pick up the change automatically.
