#!/usr/bin/env bash
# Thin wrapper so macOS/Linux users have a single double-clickable/executable
# entry point. All real logic lives in start.py.
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "[FAIL] Python 3 not found on PATH. Install it from https://www.python.org/ and re-run start.sh."
    exit 1
fi

exec "$PY" start.py "$@"
