"""Celery entry point + async-driver helper.

The previous version of every task did ``asyncio.run(_run())``
inline. That worked but the boilerplate (and the lack of a single
place to swap out the driver) made it easy to miss in a new task.

This module exposes:

* ``celery_app`` — the Celery application instance, with
  ``include=[...]`` so all ``app.tasks.*`` modules are registered.
* ``async_run(coro_factory)`` — the canonical "drive an async
  coroutine from a sync worker" helper. Today it uses
  ``asyncio.run``; if/when you switch the worker to
  ``--pool=asyncio`` (celery-pool-asyncio), replace the body with
  ``await coro_factory()`` and the worker will manage the loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable

from celery import Celery

from app.core.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        # Every module that defines @celery_app.task — keep this list
        # in sync with the actual files in app/tasks/. A missing entry
        # means the task lands in Redis but no worker picks it up.
        "app.tasks.automation",
        "app.tasks.messaging",
        "app.tasks.parsing",
        "app.tasks.commenting",
        "app.tasks.warmup",
    ],
)

celery_app.conf.task_routes = {
    "app.tasks.*": "main-queue",
}
# Re-queue safe defaults: don't drop the message if a worker dies
# mid-task, and run with a 10-minute soft limit so a stuck task
# doesn't hold a worker forever.
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.task_time_limit = 60 * 10
# ``task_always_eager`` makes ``.delay()`` execute synchronously in
# the same process — handy for dev / when Redis is unavailable. In
# production set ``CELERY_TASK_ALWAYS_EAGER=0`` (or unset) so a real
# worker pulls the queue.
_eager = os.getenv("CELERY_TASK_ALWAYS_EAGER", "1") == "1"
celery_app.conf.task_always_eager = _eager
celery_app.conf.task_eager_propagates = True


def async_run(
    coro_or_factory: Awaitable[Any] | Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Drive an async coroutine from a synchronous Celery task.

    Two call styles:

    1. ``async_run(my_async_func, *args, **kwargs)`` — preferred.
       ``my_async_func`` is a top-level ``async def`` (it must
       be importable by qualified name in the subprocess).
    2. ``async_run(coro_or_callable_returning_coro)`` — legacy
       single-argument form. The coroutine is introspected via
       ``cr_frame`` to find the underlying function (works only
       for top-level functions, not lambdas / closures).

    Three execution contexts are supported:

    1. **No event loop running** (a normal sync worker): the
       simplest path — ``asyncio.run(coro)``.
    2. **A loop is already running** (e.g. Celery ``task_always_eager``
       inside an ``asyncio`` web server like uvicorn, OR a unit
       test that calls the task from inside a pytest-asyncio
       fixture):
       we cannot use ``asyncio.run`` (``RuntimeError: This event
       loop is already running``) **and** we cannot use
       ``loop.run_until_complete`` on the live loop (Python 3.10+
       enforces that). A separate thread with its own loop fails
       because SQLAlchemy async sessions etc. are bound to the
       loop that created them. The only fully-isolated option is
       a **subprocess** that runs ``asyncio.run`` in a fresh loop.

    Pickle caveat: we cannot pickle a *coroutine* object directly
    (``TypeError: cannot pickle 'coroutine' object``). Instead we
    pickle the underlying async function by reference (qualified
    module path + name) plus the args/kwargs.
    """
    # Resolve the form. ``async_run(coro)`` → coroutine; ``async_run(func)``
    # where ``func()`` returns a coroutine is detected below.
    if args or kwargs:
        # Style 1: explicit (func, *args, **kwargs). The first
        # positional is the function; the rest is forwarded to
        # it in the subprocess.
        func = coro_or_factory
        func_args = args
        func_kwargs = kwargs
        coro = func(*func_args, **func_kwargs)
    else:
        # Style 2: legacy single-argument.
        if callable(coro_or_factory):
            coro = coro_or_factory()
        else:
            coro = coro_or_factory
        func = None
        func_args = ()
        func_kwargs = {}

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop: clean path.
        return asyncio.run(coro)

    # We're inside a running loop. Resolve the coroutine back to
    # the underlying function + args so it survives pickling.
    import os  # noqa: PLC0415
    import pickle  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    if func is None:
        # Style 2: introspect the coroutine frame to recover
        # the function reference. Only works for top-level
        # async defs.
        cr_frame = getattr(coro, "cr_frame", None)
        if cr_frame is None:
            raise RuntimeError(
                "async_run could not introspect the coroutine for "
                "subprocess delegation. Pass the async function "
                "directly: async_run(my_async_func, *args, **kwargs)."
            )
        func = cr_frame.f_globals.get(coro.__name__)
        qualname = getattr(func, "__qualname__", None) or coro.__name__
        module = getattr(func, "__module__", None)
    else:
        # Style 1: the function was given explicitly. Resolve its
        # qualified name + module from the function object so the
        # subprocess can re-import it.
        qualname = getattr(func, "__qualname__", None) or func.__name__
        module = getattr(func, "__module__", None)

    if not module or not qualname:
        raise RuntimeError(
            f"async_run: cannot resolve importable path for {func!r}"
        )

    payload = {
        "module": module,
        "qualname": qualname,
        "args": func_args,
        "kwargs": func_kwargs,
    }

    bootstrap_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "app", "core", "_async_subprocess.py",
    )
    backend_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )

    with tempfile.NamedTemporaryFile(
        "wb", suffix=".pkl", delete=False
    ) as dump:
        pickle.dump(payload, dump)
        dump_path = dump.name

    try:
        # We pass the parent's ``os.environ`` through so the
        # subprocess sees ``.env``-sourced variables like
        # ``SECRET_KEY``, ``POSTGRES_*`` etc. The subprocess
        # boots the same venv we run in, so venv-managed vars
        # (PATH, VIRTUAL_ENV) carry over automatically.
        proc = subprocess.run(  # noqa: S603
            [sys.executable, bootstrap_path, dump_path],
            cwd=backend_root,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
    finally:
        try:
            os.unlink(dump_path)
        except OSError:  # noqa: BLE001
            pass

    if proc.returncode != 0:
        logger.error(
            "async_run subprocess failed (rc=%s): stdout=%s stderr=%s",
            proc.returncode, proc.stdout, proc.stderr,
        )
        raise RuntimeError(
            f"async_run subprocess failed: {proc.stderr or proc.stdout}"
        )
    return proc.stdout.strip() if proc.stdout else None
