#!/usr/bin/env python3
"""RA demo reset: put the running backend into a known, verified starting
state before a presentation.

Does exactly one meaningful write: POST /scenario, which already resets
the shared simulated clock back to ra_core.config.DEFAULT_START_INDEX as
part of switching scenarios (see backend/app/main.py's set_scenario) -- so
no separate reset endpoint is needed. Never touches the SQLite database
directly, never deletes it, and never logs a decision (history is left
exactly as it was).

Usage:
    python scripts/reset_demo.py
    python scripts/reset_demo.py --scenario sunny --backend http://127.0.0.1:8000
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"

# The verified starting scenario for a live demo (see the Part 7A report's
# "Verified demo states" section): "sunny" at the default simulated index
# reproduces a clear, immediately visible surplus recommendation (Battery
# Charge, medium priority) on the default Hybrid Energy Hub station.
VERIFIED_STARTING_SCENARIO = "sunny"

REQUEST_TIMEOUT_SECONDS = 10


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default=DEFAULT_BACKEND_URL, help=f"Backend base URL (default: {DEFAULT_BACKEND_URL})")
    parser.add_argument("--scenario", default=VERIFIED_STARTING_SCENARIO,
                         help=f"Scenario to reset to (default: {VERIFIED_STARTING_SCENARIO})")
    args = parser.parse_args()

    try:
        health = _get(f"{args.backend}/health")
        if health.get("status") != "ok":
            print(f"[FAIL] Backend at {args.backend} is not healthy: {health}")
            return 1
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"[FAIL] Cannot reach backend at {args.backend}: {e}")
        print("       Is it running? Start it with: python start.py")
        return 1

    try:
        result = _post(f"{args.backend}/scenario", {"scenario": args.scenario})
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"[FAIL] POST /scenario returned HTTP {e.code}: {detail}")
        return 1
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"[FAIL] POST /scenario failed: {e}")
        return 1

    try:
        state = _get(f"{args.backend}/state")
        timestamp = state["reading"]["timestamp"]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"[FAIL] GET /state failed after reset: {e}")
        return 1

    print("RA demo reset complete.")
    print(f"  Scenario:       {result['scenario']}")
    print(f"  Current index:  {result['current_index']} / {result['total_points'] - 1}")
    print(f"  Timestamp:      {timestamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
