#!/usr/bin/env bash
# Thin wrapper so macOS/Linux users have a single double-clickable/executable
# entry point. All real logic lives in setup.py (kept in one place so it's
# easy to maintain and reuse, e.g. for the notebook/Voila flow later).
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "[FAIL] Python 3 not found on PATH. Install it from https://www.python.org/ and re-run setup.sh."
    exit 1
fi

exec "$PY" setup.py "$@"
