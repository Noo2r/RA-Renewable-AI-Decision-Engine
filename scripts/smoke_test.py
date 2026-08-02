#!/usr/bin/env python3
"""RA smoke test: read-only sanity check against a running backend.

Verifies health, the station registry shape, default station state,
component forecast, decision recommendation, station overview, national
summary, a What-If simulation, and a grounded assistant answer -- and that
no response body ever contains a raw NaN/Infinity token.

Every check is a GET or a side-effect-free POST (/simulate,
/assistant/query, both read-only by design -- see ra_core.what_if and
ra_core.assistant). This script never calls /tick, /scenario, or
/decision/log, so it never changes the scenario, the simulated clock, or
decision history.

Usage:
    python scripts/smoke_test.py [--backend http://127.0.0.1:8000]

Exit code is 0 if every check passes, 1 otherwise.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_SECONDS = 15
EXPECTED_STATION_COUNT = 3


class SmokeTestFailure(Exception):
    """Raised by a check to report one specific, human-readable failure."""


def _request(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, raw, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, raw, None


def _assert_no_nan_or_inf(raw_text: str, context: str):
    # json.loads happily accepts the non-standard NaN/Infinity/-Infinity
    # tokens Python's json module emits for non-finite floats (rather than
    # raising), so the raw response text -- not the parsed object -- is
    # what must be checked.
    if "NaN" in raw_text or "Infinity" in raw_text:
        raise SmokeTestFailure(f"{context}: response body contains a non-finite NaN/Infinity token")


def check_health(backend):
    status, raw, body = _request("GET", f"{backend}/health")
    if status != 200:
        raise SmokeTestFailure(f"GET /health returned {status}")
    if not body or body.get("status") != "ok":
        raise SmokeTestFailure(f"GET /health body was {body!r}, expected status=ok")
    return "backend is healthy"


def check_stations(backend):
    status, raw, body = _request("GET", f"{backend}/stations")
    if status != 200:
        raise SmokeTestFailure(f"GET /stations returned {status}")
    _assert_no_nan_or_inf(raw, "GET /stations")
    stations = (body or {}).get("stations", [])
    if len(stations) != EXPECTED_STATION_COUNT:
        raise SmokeTestFailure(f"expected exactly {EXPECTED_STATION_COUNT} stations, got {len(stations)}")
    if not body.get("default_station_id"):
        raise SmokeTestFailure("default_station_id missing")
    return f"{len(stations)} stations registered, default={body['default_station_id']}"


def check_default_station_state(backend):
    status, raw, body = _request("GET", f"{backend}/state")
    if status != 200:
        raise SmokeTestFailure(f"GET /state returned {status}")
    _assert_no_nan_or_inf(raw, "GET /state")
    for key in ("scenario", "current_index", "total_points", "reading", "surplus_kw", "generation_kw"):
        if key not in (body or {}):
            raise SmokeTestFailure(f"GET /state missing field '{key}'")
    return f"scenario={body['scenario']} index={body['current_index']}/{body['total_points'] - 1}"


def check_forecast(backend):
    status, raw, body = _request("GET", f"{backend}/forecast?hours=6")
    if status != 200:
        raise SmokeTestFailure(f"GET /forecast returned {status}")
    _assert_no_nan_or_inf(raw, "GET /forecast")
    if not body or "forecast" not in body or "model_quality" not in body:
        raise SmokeTestFailure("GET /forecast missing forecast/model_quality fields")
    return f"{len(body['forecast'])} forecast points"


def check_decision(backend):
    status, raw, body = _request("GET", f"{backend}/decision")
    if status != 200:
        raise SmokeTestFailure(f"GET /decision returned {status}")
    _assert_no_nan_or_inf(raw, "GET /decision")
    for key in ("mode", "priority", "recommended", "ranked_actions"):
        if key not in (body or {}):
            raise SmokeTestFailure(f"GET /decision missing field '{key}'")
    return f"mode={body['mode']} recommended={body['recommended']['action']}"


def check_stations_overview(backend):
    status, raw, body = _request("GET", f"{backend}/stations/overview")
    if status != 200:
        raise SmokeTestFailure(f"GET /stations/overview returned {status}")
    _assert_no_nan_or_inf(raw, "GET /stations/overview")
    stations = (body or {}).get("stations", [])
    if len(stations) != EXPECTED_STATION_COUNT:
        raise SmokeTestFailure(f"expected {EXPECTED_STATION_COUNT} stations in overview, got {len(stations)}")
    return f"{len(stations)} stations in overview"


def check_national_summary(backend):
    status, raw, body = _request("GET", f"{backend}/national/summary")
    if status != 200:
        raise SmokeTestFailure(f"GET /national/summary returned {status}")
    _assert_no_nan_or_inf(raw, "GET /national/summary")
    if not body or "totals" not in body or "station_count" not in body:
        raise SmokeTestFailure("GET /national/summary missing totals/station_count fields")
    if body["station_count"] != EXPECTED_STATION_COUNT:
        raise SmokeTestFailure(f"expected station_count={EXPECTED_STATION_COUNT}, got {body['station_count']}")
    return f"national generation={body['totals']['generation_kw']} kW"


def check_what_if_simulation(backend):
    # hybrid-01 (the default station) has both solar and wind capacity, so
    # this can never trip the "no configured capacity" validation error.
    status, raw, body = _request("POST", f"{backend}/simulate", {"solar_capacity_change_pct": 20})
    if status != 200:
        raise SmokeTestFailure(f"POST /simulate returned {status}")
    _assert_no_nan_or_inf(raw, "POST /simulate")
    for key in ("baseline", "hypothetical", "impact", "explanation"):
        if key not in (body or {}):
            raise SmokeTestFailure(f"POST /simulate missing field '{key}'")
    return "what-if simulation produced baseline/hypothetical/impact"


def check_assistant(backend):
    status, raw, body = _request("POST", f"{backend}/assistant/query", {"question": "What is happening now?"})
    if status != 200:
        raise SmokeTestFailure(f"POST /assistant/query returned {status}")
    _assert_no_nan_or_inf(raw, "POST /assistant/query")
    if not (body or {}).get("answer"):
        raise SmokeTestFailure("POST /assistant/query returned an empty answer")
    mode = body.get("grounding", {}).get("mode")
    if mode not in ("offline_deterministic", "llm_rewrite"):
        raise SmokeTestFailure(f"unexpected grounding.mode: {mode!r}")
    return f"intent={body['intent']} mode={mode}"


CHECKS = [
    ("Health", check_health),
    ("Exactly three stations", check_stations),
    ("Default station state", check_default_station_state),
    ("Component forecast", check_forecast),
    ("Decision recommendation", check_decision),
    ("Station overview", check_stations_overview),
    ("National summary", check_national_summary),
    ("What-If simulation", check_what_if_simulation),
    ("Grounded assistant answer", check_assistant),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default=DEFAULT_BACKEND_URL, help=f"Backend base URL (default: {DEFAULT_BACKEND_URL})")
    args = parser.parse_args()

    print(f"RA smoke test against {args.backend}")
    print("=" * 60)

    failures = 0
    for name, check in CHECKS:
        try:
            detail = check(args.backend)
            print(f"[PASS] {name} -- {detail}")
        except SmokeTestFailure as e:
            print(f"[FAIL] {name} -- {e}")
            failures += 1
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[FAIL] {name} -- unexpected error: {e}")
            failures += 1

    print("=" * 60)
    total = len(CHECKS)
    print(f"{total - failures}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
