"""Two kinds of events, both in-process (the app is one process by design):

1. Live events → every open browser over Server-Sent Events (`publish`, `publish_after`).
   Each carries `module` so the stream only delivers what a user may see.
2. Domain hooks → other modules in the same process (`on`, `emit`), e.g. ERP creates a seller's
   cash account when the team page grants someone the ERP "seller" role. This is how modules
   react to each other without importing each other.

If the app ever outgrows one process, only the transport changes (e.g. Redis pub/sub);
callers keep using these functions.
"""
import asyncio
import json
import logging
from typing import Callable

log = logging.getLogger("aiko.events")

_loop: asyncio.AbstractEventLoop | None = None
_clients: set[asyncio.Queue] = set()
_hooks: dict[str, list[Callable]] = {}


def attach_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def loop() -> asyncio.AbstractEventLoop | None:
    return _loop


# ---------------------------------------------------------------- live events (SSE)

def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=300)
    _clients.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _clients.discard(q)


def _deliver(event: dict) -> None:
    for q in list(_clients):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:   # a stalled browser just misses events; it refreshes on reconnect
            pass


def publish(event: dict) -> None:
    """Send an event to every open browser. Safe to call from any thread."""
    if _loop is None:
        return
    try:
        if asyncio.get_running_loop() is _loop:
            _deliver(event)
            return
    except RuntimeError:
        pass
    _loop.call_soon_threadsafe(_deliver, event)


def publish_after(con, event: dict) -> None:
    """Publish once the surrounding transaction commits (so browsers never see uncommitted data)."""
    con.after_commit.append(lambda: publish(event))


def encode(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False, default=str)


def run_soon(coro_factory: Callable) -> None:
    """Schedule a coroutine on the app loop from sync code (request handlers run in a thread pool)."""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(coro_factory(), _loop)


# ---------------------------------------------------------------- domain hooks

def on(name: str, fn: Callable) -> Callable:
    handlers = _hooks.setdefault(name, [])
    if fn not in handlers:
        handlers.append(fn)
    return fn


def emit(name: str, *, strict: bool = False, **payload) -> None:
    """Call every handler synchronously. By default a failing handler is logged and does not stop
    the others; with strict=True the first failure propagates to the caller (e.g. to show an error)."""
    for fn in _hooks.get(name, []):
        try:
            fn(**payload)
        except Exception:
            if strict:
                raise
            log.exception("hook %s failed in %s", name, getattr(fn, "__module__", fn))
