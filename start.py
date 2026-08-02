#!/usr/bin/env python3
"""RA one-click "Run All".

Starts the FastAPI backend and the React (Vite) frontend together, waits
until both are actually responding (not just "some time has passed"), then
opens the default browser to the dashboard. Prints both URLs regardless, in
case the auto-open doesn't work. Ctrl+C cleanly stops both process trees.

Usage:
    python start.py
"""
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
VENV_DIR = BACKEND_DIR / "venv"
IS_WINDOWS = sys.platform == "win32"

HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173
BACKEND_URL = f"http://{HOST}:{BACKEND_PORT}"
FRONTEND_URL = f"http://{HOST}:{FRONTEND_PORT}"
READY_TIMEOUT_SECONDS = 60


def info(msg):
    print(f"[INFO] {msg}")


def ok(msg):
    print(f"[OK]   {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def resolve_launcher(args):
    """Resolve .cmd/.bat launchers correctly on Windows (npm, etc.)."""
    args = [str(a) for a in args]
    if IS_WINDOWS and args[0].lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c"] + args
    return args


def port_responds(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def spawn(args, cwd) -> subprocess.Popen:
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True  # own process group, for clean tree-kill
    return subprocess.Popen(resolve_launcher(args), cwd=str(cwd), **kwargs)


def kill_tree(proc: subprocess.Popen, name: str):
    if proc.poll() is not None:
        return  # already exited
    info(f"Stopping {name} (pid {proc.pid})...")
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    ok(f"{name} stopped")


def wait_until_ready(check_fn, timeout: float, label: str, proc: subprocess.Popen) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if proc.poll() is not None:
            fail(f"{label} process exited early (code {proc.returncode}) — see output above.")
            return False
        if check_fn():
            return True
        time.sleep(0.5)
    fail(f"{label} did not respond within {int(timeout)}s.")
    return False


def assistant_mode() -> str:
    """Never prints the key itself -- only whether the (opt-in, disabled by
    default) LLM rewrite pass is turned on. Mirrors
    backend/app/llm_adapter.py's own enabled-check exactly."""
    enabled = os.environ.get("RA_ASSISTANT_LLM_ENABLED", "").strip().lower() in ("1", "true", "yes")
    return "LLM rewrite enabled (falls back to offline deterministic on any failure)" if enabled else "offline deterministic"


def open_browser(url: str):
    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001
        opened = False
    if opened:
        ok(f"Opened {url} in your default browser")
    else:
        info(f"Could not auto-open a browser. Open this URL manually: {url}")


def main():
    print("RA — Run All")
    print("============")

    py = venv_python()
    if not py.is_file():
        fail(f"Backend virtual environment not found at {VENV_DIR}.")
        print("        Run `setup` (setup.sh / setup.bat) first.")
        sys.exit(1)

    npm = shutil.which("npm")
    if not npm:
        fail("npm not found on PATH.")
        print("        Install Node.js 18+ from https://nodejs.org/ and run `setup` again.")
        sys.exit(1)

    if not (FRONTEND_DIR / "node_modules").exists():
        fail("frontend/node_modules not found.")
        print("        Run `setup` (setup.sh / setup.bat) first.")
        sys.exit(1)

    procs = []

    try:
        # --- Backend -----------------------------------------------------
        if port_responds(f"{BACKEND_URL}/health", timeout=1.0):
            ok(f"Backend already running and healthy at {BACKEND_URL} — reusing it")
            backend_proc = None
        elif port_open(HOST, BACKEND_PORT):
            fail(f"Port {BACKEND_PORT} is already in use by something that isn't responding to /health.")
            print(f"        Free the port (stop whatever is using {BACKEND_PORT}) and try again.")
            sys.exit(1)
        else:
            info(f"Starting backend on {BACKEND_URL} ...")
            backend_proc = spawn(
                [py, "-m", "uvicorn", "app.main:app", "--reload", "--host", HOST, "--port", str(BACKEND_PORT)],
                cwd=BACKEND_DIR,
            )
            procs.append((backend_proc, "backend"))
            if not wait_until_ready(lambda: port_responds(f"{BACKEND_URL}/health"),
                                     READY_TIMEOUT_SECONDS, "Backend", backend_proc):
                raise SystemExit(1)
            ok(f"Backend ready at {BACKEND_URL}")

        # --- Frontend ------------------------------------------------------
        if port_responds(FRONTEND_URL, timeout=1.0):
            ok(f"Frontend already running at {FRONTEND_URL} — reusing it")
        elif port_open(HOST, FRONTEND_PORT):
            fail(f"Port {FRONTEND_PORT} is already in use by something that isn't responding as a web server.")
            print(f"        Free the port (stop whatever is using {FRONTEND_PORT}) and try again.")
            raise SystemExit(1)
        else:
            info(f"Starting frontend on {FRONTEND_URL} ...")
            frontend_proc = spawn(
                [npm, "run", "dev", "--", "--strictPort", "--host", HOST, "--port", str(FRONTEND_PORT)],
                cwd=FRONTEND_DIR,
            )
            procs.append((frontend_proc, "frontend"))
            if not wait_until_ready(lambda: port_responds(FRONTEND_URL),
                                     READY_TIMEOUT_SECONDS, "Frontend", frontend_proc):
                raise SystemExit(1)
            ok(f"Frontend ready at {FRONTEND_URL}")

        print()
        open_browser(FRONTEND_URL)

        # Display as "localhost" regardless of the literal bind HOST
        # (127.0.0.1) -- both resolve to the same place, and this matches
        # the URLs users actually type/click.
        display_backend_url = f"http://localhost:{BACKEND_PORT}"
        display_frontend_url = f"http://localhost:{FRONTEND_PORT}"
        print()
        print(f"RA backend ready: {display_backend_url}")
        print(f"RA API docs: {display_backend_url}/docs")
        print(f"RA dashboard ready: {display_frontend_url}")
        print(f"Assistant mode: {assistant_mode()}")
        print("Map mode: offline local GeoJSON")
        print()
        print("Press Ctrl+C to stop.")

        while True:
            time.sleep(1)
            for proc, name in procs:
                if proc.poll() is not None:
                    fail(f"{name} exited unexpectedly (code {proc.returncode}). Shutting down.")
                    raise SystemExit(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        for proc, name in reversed(procs):
            kill_tree(proc, name)


if __name__ == "__main__":
    main()
