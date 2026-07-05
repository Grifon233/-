"""Run uvicorn in the foreground for ~25s while we capture the profile/refresh traceback.

We launch it with --no-access-log so the only output we get is the
real exceptions.
"""
import os, signal, subprocess, sys, time, threading, urllib.request, urllib.error, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "foreground.log"
LOG.write_text("", encoding="utf-8")

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"
env["PYTHONIOENCODING"] = "utf-8"
env["LOG_LEVEL"] = "DEBUG"

log_fh = open(LOG, "w", encoding="utf-8", buffering=1)
proc = subprocess.Popen(
    [str(ROOT / "venv" / "Scripts" / "python.exe"), "-m", "uvicorn",
     "app.main:app", "--host", "127.0.0.1", "--port", "8000",
     "--no-access-log"],
    cwd=str(ROOT), env=env, stdout=log_fh, stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)

# Wait for the listener
def wait_listener():
    for _ in range(60):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
    return False

if not wait_listener():
    print("Listener did not come up; see foreground.log")
    proc.terminate()
    sys.exit(1)
print("Listener up.")

# Now hit the failing endpoint
TOKEN = "YOUR_BEARER_TOKEN"
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/accounts/4/profile/refresh",
    method="POST", data=b"{}",
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"OK: {r.status}  {r.read()[:200]}")
except urllib.error.HTTPError as e:
    print(f"ERR {e.code}: {e.read()[:300]}")

time.sleep(1)
proc.terminate()
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()
log_fh.close()
print("--- foreground.log tail ---")
print("\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]))
