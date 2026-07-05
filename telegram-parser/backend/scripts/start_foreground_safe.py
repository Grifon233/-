"""Foreground uvicorn that writes to a captured log file. Used when
start_backend_detached.py crashes before the listener can come up.
"""
import os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "foreground-start.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
LOG.write_text("", encoding="utf-8")

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

log_fh = open(LOG, "w", encoding="utf-8", buffering=1)
proc = subprocess.Popen(
    [str(ROOT / "venv" / "Scripts" / "python.exe"), "-m", "uvicorn",
     "app.main:app", "--host", "127.0.0.1", "--port", "8000",
     "--no-access-log"],
    cwd=str(ROOT), env=env, stdout=log_fh, stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
print(f"Started PID {proc.pid}; waiting for listener")

for _ in range(40):
    time.sleep(0.5)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as r:
            if r.status == 200:
                print("Listener up after ~", _, "*0.5s")
                # leave it running; exit the wrapper
                sys.exit(0)
    except Exception:
        pass

proc.terminate()
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()
log_fh.close()
print("Listener did NOT come up. Log tail:")
print("\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]))
sys.exit(1)
