from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from config.settings import BACKEND_BASE_URL

STARTUP_TIMEOUT_SECONDS = 30


def _backend_alive() -> bool:
    try:
        return requests.get(f"{BACKEND_BASE_URL}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _backend_python() -> Path | None:
    """Locate the backend venv. CASEMIND_BACKEND_DIR wins; otherwise the
    repo layout (this file lives in desktop/casemind_desktop/)."""
    backend_dir = Path(
        os.getenv("CASEMIND_BACKEND_DIR")
        or Path(__file__).resolve().parents[2] / "backend"
    )
    python = backend_dir / ".venv" / "Scripts" / "python.exe"
    return python if python.exists() else None


def ensure_backend() -> bool:
    """Start the backend if it is not already running. Returns True when
    /health answers. The child outlives this process on purpose — next
    launches find it already up, and stopping it never loses data."""
    if _backend_alive():
        return True

    python = _backend_python()
    if python is None:
        return False

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(python.parents[2]),
        creationflags=creationflags,
    )

    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _backend_alive():
            return True
        time.sleep(0.5)
    return False
