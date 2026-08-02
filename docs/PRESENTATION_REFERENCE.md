# RA — Presentation Reference

**Companion to:** `docs/RA_Final_Project_Documentation.md` (v1.0, verified commit `090e954`, 295/295 tests passing)

This file maps two suggested presentation storylines — business and technical — to specific evidence
(tables, figures, and numbers) already verified in the main documentation. It does not introduce any new
claim, number, or feature; every bullet below points back to a specific section of the main document.

Slide counts are suggestions, not templates — adjust wording and pacing for the actual audience and time
slot, but keep the evidence pointers as written so nothing presented drifts from what is documented.

---

## Business Presentation Storyline (8–12 slides)

| # | Slide title | Talking point | Evidence to use |
|---|---|---|---|
| 1 | Title | RA — Renewable AI Decision Engine. Decision support, not automation. Synthetic-data prototype. | Cover page metadata (main doc) |
| 2 | The problem | Renewable generation is variable; demand doesn't track it; batteries and grid decisions are constrained; dashboards only show what happened, not what to do. | Section 1 (Problem), Table 1-1 |
| 3 | Who feels this pain | Site operators, multi-site asset managers, planners, and non-technical stakeholders each lack a different piece of the picture today. | Section 3.1–3.3, Table 3-1 |
| 4 | The solution, in one sentence | Prediction + Decision + Explanation + Simulation — one connected loop, not four separate tools. | Section 2, Executive Summary |
| 5 | Why RA is more than a dashboard | Forward view, ranked recommendation, plain-language reasoning, built-in hypothesis testing. | Table 2-1 |
| 6 | Demo — a clear surplus | Live: hybrid station, sunny scenario, default state → Battery Charge recommended, with EGP value and CO2 avoided shown. | Table 7-5 (row 1), Figure 9 |
| 7 | Demo — a deficit and a what-if | Live: same station 11 hours later → Grid Import recommended (battery empty). Ask "what if the battery were twice as large?" → recommendation flips to Battery Discharge. | Table 7-5 (rows 3–4), Figure 10 |
| 8 | Demo — ask the assistant | Type "Why was this decision selected?" and get the same reasoning back in plain language. | Section 6.4, Table 6-3 |
| 9 | Impact today vs. tomorrow | Be explicit: decision speed and consistency are demonstrated today; cost/emissions savings are a mechanism, not yet a measured outcome. | Section 8.1 vs. 8.2, Table 8-1 |
| 10 | Scalability | From 3 demo stations and synthetic data to real telemetry, more sites, and national-scale coordination. | Section 10.1–10.2 |
| 11 | Future vision | Real SCADA/IoT integration, real weather forecasts, human-approval workflows before any real-equipment integration. | Section 10 (all) |
| 12 | Close / ask | What RA proves today (a working, tested, explainable decision loop) and what would be needed to take the next step (real data, a pilot site). | Section 11 (Conclusion) |

**Delivery notes**

- Slides 6–8 are live-demo slides. Reset to a known state first with `python scripts/reset_demo.py` — it
  prints the resulting scenario, index, and timestamp so you can confirm you're at the documented baseline
  before presenting.
- Keep the disclosure sentence ("decision-support prototype using deterministic synthetic station data — it
  does not control real equipment") visible or spoken at least once early — it is on the dashboard itself
  (header) and should be on the title or problem slide too.
- Never state a specific EGP or CO2 savings figure as a *real-world achieved* result — every number shown
  in the demo is an internally consistent estimate from synthetic data (Section 8, note in Section 3.3).

---

## Technical Presentation Storyline (10–15 slides)

| # | Slide title | Talking point | Evidence to use |
|---|---|---|---|
| 1 | Architecture overview | Four layers: presentation (React + notebook), application (FastAPI), shared core (ra_core), data (SQLite). One core, two front ends. | Figure 1, Section 4.1–4.4 |
| 2 | Data flow | Synthetic data → forecasting → confidence → decision engine → What-If → assistant → API → UI/notebook. | Figure 2 |
| 3 | Data and scenarios | 3 stations, 4 scenarios, 15-minute interval, deterministic seeding, structural-zero handling. | Section 5, Tables 5-1/5-2 |
| 4 | Forecasting models | Per-component GradientBoostingRegressor (n_estimators=60, max_depth=3, learning_rate=0.1); solar/wind/demand forecast independently. | Figure 3, Section 4.6 |
| 5 | Validation methodology | Chronological 80/20 holdout (never shuffled); honest out-of-sample MAE. | Section 7.2, Table 7-2 |
| 6 | Confidence scoring | Model-confidence, not probability; derived from raw interval width; clamped [50, 99]; provably non-increasing with horizon. | Section 6.1 |
| 7 | Decision engine | Deterministic, rule-based scoring (value + CO2 shadow price − cost); surplus vs. deficit action sets; priority thresholds. | Figure 4, Section 6.2, Table 6-1 |
| 8 | Battery constraints | Rate limit, usable SoC band, round-trip efficiency all enforced simultaneously; zero-capacity and boundary cases explicitly handled. | Figure 5, Section 7.3, Table 7-3 |
| 9 | What-If isolation | `dataclasses.replace()` hypothetical copy; real registry never mutated; both runs share weather/seed/index. | Figure 6, Section 7.4 |
| 10 | Assistant grounding | Deterministic keyword intent classifier (no ML/embeddings); context gathered only from existing endpoint functions; optional LLM rewrites wording only. | Figure 7, Section 4.10–4.11 |
| 11 | API surface | 14 REST endpoints; read vs. write clearly separated; no unintended side effects. | Appendix A, Section 7.4 |
| 12 | Test suite | 295 tests across 12 files; edge cases (zero battery, zero demand, dataset end, NaN/Infinity sweep) added during hardening. | Table 7-1, Section 7.1 |
| 13 | Reliability hardening | Request-ID and busy-state guards against race conditions from rapid clicking; verified live (3 rapid submits → 1 request). | Section 9.4, Table 9-1 |
| 14 | Limitations | Ground-truth weather assumption, fixed 3-station registry, no real-data validation yet, no auth/production hardening. | Section 9.1–9.3 |
| 15 | Future work | Real SCADA/IoT, real weather forecasts, national-scale optimization, model monitoring, cybersecurity, human approval workflows. | Section 10 |

**Delivery notes**

- Slide 6 (confidence) is the most commonly misunderstood point in Q&A — be ready to explain explicitly
  that a 96% confidence score is *not* "96% likely to be correct."
- Slide 9 (What-If isolation) and slide 13 (reliability) are good places to cite specific test names if the
  audience is engineering-heavy — Section 7 lists them by name (e.g.
  `test_no_database_or_global_state_dependency`, `test_zero_battery_capacity_does_not_crash`).
- If asked "why not use an LLM for the decision itself" — the answer is in Section 4.10/6.4: RA's core
  reasoning is deterministic and rule-based by design, for auditability; the *only* optional LLM usage is a
  disabled-by-default wording rewrite that cannot change a number or a recommendation (Section 4.11).

---

## Shared ground rules for both storylines

- Every number presented must trace to a table or figure in `RA_Final_Project_Documentation.md` — if asked
  for a number not in that document, say so rather than estimating live.
- Always use the words "decision support" and "recommendation," never "autonomous control" or "automatically
  executes" — RA never sends a command to real equipment, and the assistant explicitly refuses imperative
  control phrasing (Section 6.4, Table 6-3).
- If a live demo fails during a presentation, the fallback is the screenshots already embedded in the main
  document (Figures 9–10) plus `python scripts/smoke_test.py`, which prints a clear PASS/FAIL status against
  the running backend in seconds.
