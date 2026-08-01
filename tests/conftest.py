"""Shared pytest setup: make ra_core (repo root) and app (backend/) importable
regardless of which directory pytest is invoked from.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"

for _p in (REPO_ROOT, BACKEND_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
