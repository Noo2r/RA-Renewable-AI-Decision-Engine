#!/usr/bin/env python3
"""RA one-click setup.

Creates the backend virtual environment, installs backend Python deps, and
installs frontend npm deps. Safe to re-run — every step checks what's
already in place before doing work (idempotent).

Usage:
    python setup.py
"""
import shutil
import subprocess
import sys
import venv
from pathlib import Path

# Keep our prints and the child processes' inherited-stdout output in the
# same order even when stdout isn't a TTY (e.g. redirected to a log file).
sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
VENV_DIR = BACKEND_DIR / "venv"
IS_WINDOWS = sys.platform == "win32"


def ok(msg):
    print(f"[OK]   {msg}")


def info(msg):
    print(f"[INFO] {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def run(args, cwd=None) -> int:
    """Run a command, resolving .cmd/.bat launchers correctly on Windows."""
    args = [str(a) for a in args]
    if IS_WINDOWS and args[0].lower().endswith((".cmd", ".bat")):
        args = ["cmd.exe", "/c"] + args
    return subprocess.run(args, cwd=cwd).returncode


def check_node() -> bool:
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not npm or not node:
        fail("Node.js / npm not found on PATH.")
        print("        Install Node.js 18+ from https://nodejs.org/ and re-run setup.")
        return False
    try:
        result = subprocess.run(
            (["cmd.exe", "/c", npm, "--version"] if IS_WINDOWS else [npm, "--version"]),
            capture_output=True, text=True, check=True,
        )
        ok(f"npm {result.stdout.strip()} found")
        return True
    except Exception as e:  # noqa: BLE001 - report and continue
        fail(f"npm found but failed to run: {e}")
        return False


def setup_backend() -> bool:
    print("\n== Backend ==")
    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.is_file():
        fail(f"{req_file} not found — is this the right project directory?")
        return False

    if VENV_DIR.exists():
        info("Virtual environment already exists at backend/venv, reusing it")
    else:
        info("Creating virtual environment at backend/venv ...")
        try:
            venv.EnvBuilder(with_pip=True).create(VENV_DIR)
        except Exception as e:  # noqa: BLE001
            fail(f"Failed to create virtual environment: {e}")
            return False
        ok("Virtual environment created")

    py = venv_python()
    if not py.is_file():
        fail(f"Expected venv python at {py} but it's missing. Delete backend/venv and re-run setup.")
        return False

    info("Installing backend dependencies (this can take a minute)...")
    rc = run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    if rc != 0:
        info("Could not upgrade pip (non-fatal), continuing...")
    rc = run([py, "-m", "pip", "install", "-q", "-r", req_file])
    if rc != 0:
        fail("pip install failed — see output above.")
        return False
    ok("Backend dependencies installed")
    return True


def setup_frontend() -> bool:
    print("\n== Frontend ==")
    pkg_file = FRONTEND_DIR / "package.json"
    if not pkg_file.is_file():
        fail(f"{pkg_file} not found — is this the right project directory?")
        return False
    if not check_node():
        return False

    info("Installing frontend dependencies (npm install)...")
    npm = shutil.which("npm")
    rc = run([npm, "install"], cwd=FRONTEND_DIR)
    if rc != 0:
        fail("npm install failed — see output above.")
        return False
    ok("Frontend dependencies installed")
    return True


def main():
    print("RA setup")
    print("========")
    info(f"Using {sys.executable} (Python {sys.version.split()[0]})")

    backend_ok = setup_backend()
    frontend_ok = setup_frontend()

    print("\n== Summary ==")
    print(f"Backend:  {'OK' if backend_ok else 'FAILED'}")
    print(f"Frontend: {'OK' if frontend_ok else 'FAILED'}")

    if backend_ok and frontend_ok:
        print()
        ok("Setup complete. Run `start` (start.sh / start.bat) to launch RA.")
        sys.exit(0)
    else:
        print()
        fail("Setup incomplete — fix the issue(s) above and re-run setup.")
        sys.exit(1)


if __name__ == "__main__":
    main()
