"""Truly detach a uvicorn backend so it survives the parent shell.

Windows quirks we have to work around:

* ``Start-Process -WorkingDirectory`` is a pwsh 6+ feature; the
  embedded PowerShell 5.1 here doesn't have it.
* ``start /B`` from ``cmd.exe`` does not honour output redirection
  when the path contains Cyrillic / spaces (which our workspace
  does).
* Subprocess + DETACHED_PROCESS gives us a real Win32 detached
  handle so the child outlives the parent Python process.

Usage::

    venv\\Scripts\\python.exe scripts\\start_backend_detached.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
DISABLED_FLAG = Path(__file__).resolve().parent / "backend_autostart.disabled"
# Use the venv python.exe (not pythonw) so the child has access to
# a real stdout/stderr for the log file.
PY = ROOT / "venv" / "Scripts" / "python.exe"
LOG_OUT = ROOT / "logs" / "uvicorn-detached.out.log"
LOG_ERR = ROOT / "logs" / "uvicorn-detached.err.log"


def backend_is_healthy() -> bool:
    try:
        with urlopen("http://127.0.0.1:8000/api/v1/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


if DISABLED_FLAG.exists():
    print(f"Backend autostart is disabled via {DISABLED_FLAG}")
    sys.exit(0)

if backend_is_healthy():
    print("Backend is already running at http://127.0.0.1:8000")
    sys.exit(0)

# Wipe old logs so we can see the new run.
LOG_OUT.write_text("", encoding="utf-8")
LOG_ERR.write_text("", encoding="utf-8")

# CREATE_NEW_PROCESS_GROUP = the child does not share a console
# with us. DETACHED_PROCESS = no console at all.
# CREATE_BREAKAWAY_FROM_JOB = the child is not in our job object,
# so killing the parent (or our console) does not cascade-kill it.
flags = (
    subprocess.CREATE_NEW_PROCESS_GROUP
    | subprocess.DETACHED_PROCESS
    | subprocess.CREATE_BREAKAWAY_FROM_JOB
)
log_out = open(LOG_OUT, "ab", buffering=0)
log_err = open(LOG_ERR, "ab", buffering=0)

print(f"Starting uvicorn in {ROOT}")
proc = subprocess.Popen(
    [str(PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
    cwd=str(ROOT),
    stdout=log_out,
    stderr=log_err,
    stdin=subprocess.DEVNULL,
    creationflags=flags,
    close_fds=True,
)
print(f"Started PID {proc.pid}")

# Wait up to 12s for the listener to come up.
deadline = time.time() + 12
while time.time() < deadline:
    if proc.poll() is not None:
        print("ERROR: uvicorn exited prematurely")
        print("--- stdout ---")
        print(LOG_OUT.read_text(encoding="utf-8", errors="replace"))
        print("--- stderr ---")
        print(LOG_ERR.read_text(encoding="utf-8", errors="replace"))
        sys.exit(1)
    time.sleep(0.5)
    # On Windows, ``python -m uvicorn`` can end up with a different
    # owning PID than the bootstrap process we launched, so use the
    # socket/HTTP readiness as the source of truth instead of exact PID
    # matching.
    try:
        if backend_is_healthy():
            print("Listener up: http://127.0.0.1:8000")
            sys.exit(0)
    except Exception:
        pass

print("Listener did not come up in 12s. Last log lines:")
print("--- stdout (last 20) ---")
print("\n".join(LOG_OUT.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]))
print("--- stderr (last 20) ---")
print("\n".join(LOG_ERR.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]))
sys.exit(1)
