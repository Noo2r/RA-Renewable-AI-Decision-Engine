# RA — Renewable AI Decision Engine

RA turns renewable energy surplus into smart, automated, **explainable**
decisions. It watches a simulated solar + wind site (generation, battery
state of charge, grid demand/price, weather), forecasts the next 1-6 hours
of surplus, and recommends what to do with it — store it, sell it, run a
flexible load, or curtail — with a plain-language reason for every call.

This is an MVP built for a demo/pitch: everything runs locally against a
seeded synthetic dataset, no external services or API keys required.

There are **two front ends sharing one engine**: a FastAPI + React web
dashboard, and a self-contained Jupyter notebook. Both import the same
`ra_core/` package, so they can never drift apart on numbers or logic —
pick whichever fits the room.

## Architecture

```
ra_core/              Shared core — no FastAPI/React dependency
  config.py             site + simulation constants
  data_generator.py     deterministic synthetic time-series generator (per scenario)
  forecasting.py        GradientBoostingRegressor forecast of generation/demand -> surplus
  decision_engine.py    scores actions (battery/pump/sell/curtail) + writes explanations
  kpi.py                aggregates logged decisions into utilization/CO2/value KPIs

backend/              FastAPI service (imports ra_core)
  app/
    config.py            re-exports ra_core.config + backend-only DB_PATH
    db.py                 SQLite persistence (readings, sim clock, decision log)
    seed.py               seeds all 4 scenarios on first run
    main.py                REST API: /state /forecast /decision /history /scenario /tick

frontend/              React + Tailwind + Recharts dashboard (Vite)

notebook/              Jupyter notebook front end (imports ra_core)
  RA_notebook_demo.ipynb  same state/forecast/decision views + a What-If simulator
```

Data flows one direction: synthetic generator → (SQLite, for the web app)
→ forecasting + decision engine → presentation layer (REST API + dashboard,
or notebook widgets). Swapping SQLite for Postgres/InfluxDB later only
touches `backend/app/db.py`; neither front end's numbers are affected
because neither owns the underlying logic — `ra_core/` does.

### Simulated clock

There's no real-time feed — instead a `current_index` pointer in SQLite
marks "now" inside a pre-generated 4-day, 15-minute-resolution series per
scenario. `POST /tick` advances it (used by the dashboard's "Advance" and
"Play Auto-Advance" controls). This makes the demo fully repeatable and lets
you scrub forward/backward through a day without waiting in real time.

## Setup

### 1. Backend (Python 3.10+)

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The database (`backend/ra.db`) is created and seeded automatically on first
startup — all 4 scenarios (sunny, cloudy, windy, high_demand) are generated
and stored, no manual steps needed. Re-run `python -m app.seed` to force a
full re-seed.

### 2. Frontend (Node 18+)

```bash
cd frontend
npm install
npm run dev
```

Open the printed local URL (default `http://localhost:5173`). The frontend
expects the API at `http://localhost:8000` (override with `VITE_API_URL`).

### 3. Notebook (optional second front end)

```bash
cd notebook
python -m venv venv        # or reuse backend/venv, which already has these deps
venv\Scripts\activate
pip install -r requirements.txt
jupyter lab RA_notebook_demo.ipynb
```

Launch Jupyter from the repo root (or from `notebook/` — the notebook
locates `ra_core/` automatically either way) and choose **Run All**. No
backend or frontend server needs to be running; the notebook generates its
own copy of the same deterministic dataset directly from `ra_core`. See
[`notebook/RA_notebook_demo.ipynb`](notebook/RA_notebook_demo.ipynb) for
its own walkthrough — it mirrors the web dashboard's status panel, forecast
chart, decision card, and ranked actions, and adds an interactive What-If
simulator (solar capacity / demand growth / dust-storm sliders) and a KPI
summary that the web app doesn't currently expose.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/state` | GET | Current reading + surplus/deficit for the active scenario |
| `/forecast?hours=6` | GET | Recent actual surplus + forecast surplus for the next N hours |
| `/decision` | GET | Ranked actions with expected kWh / EGP / CO2 and explanations |
| `/decision/log` | POST | Logs the current top recommendation to the decision history |
| `/history?limit=20` | GET | Past logged decisions for the active scenario |
| `/scenarios` | GET | Available scenario names |
| `/scenario` | POST `{"scenario": "cloudy"}` | Switch scenario, resets simulated clock |
| `/tick` | POST `{"steps": 1}` | Advance the simulated clock (1 step = 15 min) |

## Demo script (3-5 minutes)

1. **Open the dashboard** (`http://localhost:5173`). It loads directly into
   a mid-morning **sunny day** with ~18 kW of surplus already showing —
   generation, demand, battery SoC, price, and weather are all live in the
   status panel. No setup, no clicking through empty states.
2. **Point at the forecast chart.** The solid line is actual surplus
   history; the dashed line is the model's forecast for the next 6 hours,
   with the underlying `actual` value revealed alongside it once time
   passes — call out the reported MAE (kW) as a concrete accuracy number.
3. **Point at the Recommended Decision card.** Read the explanation aloud —
   it names the exact surplus, battery headroom, current vs. forecast
   price, and the EGP/CO2 impact that produced the ranking. Show the "All
   ranked options" list underneath to prove it's not a single hard-coded
   answer — it's a scored comparison.
4. **Click "Execute & Log Decision."** The action appears immediately in
   the Decision Log on the left — this is the "surplus detected → forecast
   shown → decision recommended → outcome logged" loop the product exists
   to close.
5. **Click "Advance 1 hour" a couple of times** (or hit "Play
   Auto-Advance"). Watch battery SoC climb, and watch the recommendation
   itself change — once the battery nears full, RA switches its top pick
   from "Store in Battery" to "Sell to Grid" automatically, with a new
   explanation reflecting the new state.
6. **Switch to the "Cloudy / Intermittent" scenario.** Generation drops,
   the site swings into a small deficit, and the recommendation changes to
   "Curtail" with an explanation stating plainly that there's no surplus
   to act on right now — proving the engine adapts to the scenario rather
   than always returning the same answer.
7. **Switch to "High Demand"** to show the reverse: price volatility and
   demand both rise, and the ranked actions and EGP values shift again.

This closes the story: **surplus detected → forecast shown → decision
recommended with a reason → outcome logged → engine adapts as conditions
change.**

## Notes on the "AI" in RA

- Forecasting: a `GradientBoostingRegressor` per target (generation,
  demand) using time-of-day + weather features, validated against a
  held-out 20% split of the simulated history (reported as `model_quality`
  in the `/forecast` response).
- Decision engine: rule-gated, ML-scored ranking over 4 actions (battery
  charge, water pumping/desalination, grid sale, curtail), each valued in
  EGP + kg CO2 avoided from a transparent formula — every number in the
  explanation traces back to a value shown on the dashboard, by design
  (no black box).

## Swapping the use case

The action list (`battery_charge`, `water_pumping`, `sell_grid`, `curtail`)
lives entirely in `ra_core/decision_engine.py`; the synthetic data knobs
(cloud cover, wind, demand scale, price volatility) live in
`ra_core/data_generator.py`. Both are intentionally isolated from the
API/db/frontend/notebook layers so the surplus-use-case can be re-targeted
(e.g. swap water pumping for EV charging or cold storage pre-cooling) by
editing one shared file — both front ends pick up the change automatically.
