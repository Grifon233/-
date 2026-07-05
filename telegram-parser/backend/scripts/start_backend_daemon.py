"""Daemonize uvicorn using Windows API + service-style detachment.

The trick: invoke ``python.exe -m uvicorn`` via
``ctypes.windll.shell32.ShellExecuteExW`` with the
``SEE_MASK_NOCLOSEPROCESS`` flag. This is the same path Windows
Explorer uses to launch ``.exe`` files: the new process gets its
own console (or runs hidden), and it is registered with the
parent's job object ONLY if the parent has a job. We don't.

After this script exits the uvicorn process keeps running because
the Win32 call returns a process handle that we close; the new
process is now owned by the system root (smss.exe) and will
outlive any parent.

Usage::

    venv\\Scripts\\python.exe scripts\\start_backend_daemon.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISABLED_FLAG = Path(__file__).resolve().parent / "backend_autostart.disabled"
PY = ROOT / "venv" / "Scripts" / "python.exe"
LOG_OUT = ROOT / "logs" / "uvicorn-daemon.out.log"
LOG_ERR = ROOT / "logs" / "uvicorn-daemon.err.log"

if DISABLED_FLAG.exists():
    print(f"Backend autostart is disabled via {DISABLED_FLAG}")
    sys.exit(0)

# Wipe old logs.
LOG_OUT.write_text("", encoding="utf-8")
LOG_ERR.write_text("", encoding="utf-8")


# --- ctypes setup -----------------------------------------------------------
SW_SHOW = 5  # SW_SHOWNORMAL but with NOCLOSEPROCESS semantics
SW_HIDE = 0
SE_ERR_NOASSOC = 1155

shell32 = ctypes.WinDLL("shell32", use_last_error=True)


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wt.HWND),
        ("lpVerb", wt.LPCWSTR),
        ("lpFile", wt.LPCWSTR),
        ("lpParameters", wt.LPCWSTR),
        ("lpDirectory", wt.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wt.LPCWSTR),
        ("hkeyClass", wt.HKEY),
        ("dwHotKey", wt.DWORD),
        ("hIconOrMonitor", wt.HANDLE),
        ("hProcess", wt.HANDLE),
    ]


SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NO_CONSOLE = 0x00008000

info = SHELLEXECUTEINFOW()
info.cbSize = ctypes.sizeof(info)
info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
info.hwnd = None
info.lpVerb = "open"
info.lpFile = str(PY)
info.lpParameters = "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
info.lpDirectory = str(ROOT)
info.nShow = SW_HIDE
info.hInstApp = None

print(f"Launching via ShellExecuteExW: {PY} -m uvicorn …")
if not shell32.ShellExecuteExW(ctypes.byref(info)):
    err = ctypes.get_last_error()
    raise OSError(f"ShellExecuteExW failed: win32 error {err}")
print("ShellExecuteExW returned a process handle; the new process is detached.")

# Wait for the listener to come up.
deadline = time.time() + 12
while time.time() < deadline:
    time.sleep(0.5)
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | "
             "Select-Object -First 1 -ExpandProperty LocalAddress"],
            timeout=3,
        )
        if out.strip():
            print(f"Listener up: {out.strip().decode()}:8000")
            sys.exit(0)
    except Exception:
        pass

print("Listener did not come up in 12s.")
print("--- stdout (last 20) ---")
print("\n".join(LOG_OUT.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]))
print("--- stderr (last 20) ---")
print("\n".join(LOG_ERR.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]))
sys.exit(1)
