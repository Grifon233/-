"""Subprocess bootstrap for :func:`app.core.celery_app.async_run`.

The parent Celery task pickles a small dict
``{"module": ..., "qualname": ..., "args": ..., "kwargs": ...}``,
then spawns this script with the pickle path. We import the
qualified async function, call it with the recorded args, and
``asyncio.run`` the resulting coroutine in a fresh event loop.

Why a subprocess and not a thread?
    The coroutine almost always touches SQLAlchemy async sessions,
    which are bound to the event loop that created them. Running
    the coroutine in a different loop raises
    ``RuntimeError: ... attached to a different loop``. A separate
    process guarantees complete isolation.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import pickle
import sys
import traceback
from pathlib import Path


def _bootstrap_path() -> None:
    """Make sure ``app.*`` is importable in the subprocess AND
    that ``.env`` is loaded before the Settings model is built.

    The subprocess may be launched from a different cwd (we set
    cwd to the backend root in the parent, but the venv's
    site-packages layout depends on whether Python was started
    with ``-m`` or directly). The safe bet is to push the
    backend's own root directory onto ``sys.path`` so the parent
    directory of ``app/`` is the import root.
    """
    here = Path(__file__).resolve()
    # ``_async_subprocess.py`` lives at
    # ``<backend>/app/core/_async_subprocess.py`` — the backend
    # root is therefore 3 levels up.
    backend_root = here.parent.parent.parent
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    # Load ``.env`` so pydantic-settings has the required vars
    # (``SECRET_KEY`` etc.) when ``Settings()`` is constructed
    # inside the subprocess. We do it *after* ``sys.path`` is
    # fixed so a hypothetical ``.env`` plugin module can be
    # picked up too.
    try:
        from dotenv import load_dotenv  # type: ignore

        env_path = backend_root / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except Exception:  # noqa: BLE001
        # ``python-dotenv`` is a hard dep of the backend, but
        # if the venv is somehow missing it we'd rather see
        # the underlying pydantic error than silently drop vars.
        pass


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: _async_subprocess.py <pickle-path>", file=sys.stderr)
        return 2
    pickle_path = Path(sys.argv[1])
    if not pickle_path.exists():
        print(f"pickle not found: {pickle_path}", file=sys.stderr)
        return 2
    _bootstrap_path()
    try:
        payload = pickle.loads(pickle_path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        print(f"failed to unpickle payload: {exc}", file=sys.stderr)
        return 3

    module_name = payload.get("module")
    qualname = payload.get("qualname")
    args = payload.get("args", ())
    kwargs = payload.get("kwargs", {})
    if not module_name or not qualname:
        print("payload missing module/qualname", file=sys.stderr)
        return 4

    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        print(f"import_module({module_name!r}) failed: {exc}", file=sys.stderr)
        return 5
    func = mod
    for part in qualname.split("."):
        func = getattr(func, part, None)
        if func is None:
            print(f"could not resolve {module_name}.{qualname}", file=sys.stderr)
            return 6
    if not callable(func):
        print(f"resolved {module_name}.{qualname} is not callable", file=sys.stderr)
        return 7

    try:
        coro = func(*args, **kwargs)
        result = asyncio.run(coro)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"coroutine raised: {exc!r}", file=sys.stderr)
        return 1
    if result is not None:
        print(repr(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
