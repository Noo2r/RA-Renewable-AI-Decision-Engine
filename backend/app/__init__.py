import os
import sys

# ra_core/ lives at the repo root (sibling of backend/ and frontend/), so it
# isn't on sys.path when uvicorn is launched from inside backend/. Add the
# repo root here, once, so `import ra_core` works regardless of cwd.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
