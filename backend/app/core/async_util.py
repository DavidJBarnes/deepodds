import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

# One event loop per OS thread. Celery forks worker processes, each process
# gets its own thread → loop mapping. This avoids asyncio.run() overhead
# (loop creation + teardown per call) and prevents RuntimeError when called
# from an environment that already has a running loop.
_loops: dict[int, asyncio.AbstractEventLoop] = {}
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    tid = threading.get_ident()
    with _lock:
        loop = _loops.get(tid)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            _loops[tid] = loop
        return loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from synchronous code.

    Uses a long-lived event loop per thread instead of asyncio.run(),
    which creates and destroys a loop on every call. Safe to call from
    Celery tasks, FastAPI request handlers, or scripts.

    Falls back to asyncio.run() if an event loop is already running
    on the current thread (e.g. inside a FastAPI endpoint handler).
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        # Already inside an async context — create a sub-loop.
        # This is the standard pattern for calling async from sync
        # code when there's already a running loop on this thread.
        return running.run_until_complete(coro)

    loop = _get_loop()
    return loop.run_until_complete(coro)
