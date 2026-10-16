"""Background work for every module: one scheduler for clock-based jobs and supervised long-running loops.

The app runs as ONE process with ONE worker on purpose: with SQLite, the in-process event bus and
this scheduler, a second worker would run every job twice. (Throughput is not the constraint here;
a single uvicorn worker comfortably serves a shop's team.)
"""
import asyncio
import logging
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, events

log = logging.getLogger("aiko.jobs")

scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
_loops: dict[str, asyncio.Task] = {}
_tasks: set[asyncio.Task] = set()


def daily(job_id: str, hhmm: str, fn: Callable, *args) -> None:
    """Run `fn(*args)` every day at HH:MM (Tehran time). Missed runs within an hour still fire once.
    Coroutine functions run on the event loop; plain functions run in a worker thread (fine for blocking I/O)."""
    hh, mm = hhmm.split(":")
    scheduler.add_job(fn, CronTrigger(hour=int(hh), minute=int(mm)), args=list(args), id=job_id,
                      replace_existing=True, misfire_grace_time=3600, coalesce=True)


def every(job_id: str, seconds: int, fn: Callable, *args) -> None:
    scheduler.add_job(fn, "interval", seconds=seconds, args=list(args), id=job_id, replace_existing=True,
                      coalesce=True, max_instances=1)


def next_runs(prefix: str) -> list:
    return sorted(j.next_run_time for j in scheduler.get_jobs() if j.id.startswith(prefix) and j.next_run_time)


def supervise(name: str, factory: Callable[[], Awaitable[None]], *, restart_after: float = 10) -> None:
    """Keep a long-running coroutine alive: if it crashes it is logged and restarted."""
    async def runner():
        while True:
            try:
                await factory()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("background loop %s crashed; restarting in %ss", name, restart_after)
                await asyncio.sleep(restart_after)
    _loops[name] = asyncio.create_task(runner(), name=name)


def spawn(coro: Awaitable, name: str | None = None):
    """Fire-and-forget task that is kept referenced until it finishes, with errors logged.
    Safe to call from request handlers running in the thread pool."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = events.loop()
        if loop is None:
            raise RuntimeError("the app event loop is not running")
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        fut.add_done_callback(lambda f: f.cancelled() or not f.exception() or
                              log.error("task %s failed", name, exc_info=f.exception()))
        return fut
    task = asyncio.ensure_future(coro)
    if name:
        task.set_name(name)
    _tasks.add(task)

    def done(t: asyncio.Task):
        _tasks.discard(t)
        if not t.cancelled() and t.exception():
            log.error("task %s failed", t.get_name(), exc_info=t.exception())
    task.add_done_callback(done)
    return task


def reset() -> None:
    """Fresh scheduler for a new app start (an APScheduler instance stays bound to the loop it first ran on)."""
    global scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)


def start() -> None:
    if not scheduler.running:
        scheduler.start()


async def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
    for task in [*_loops.values(), *_tasks]:
        task.cancel()
    await asyncio.gather(*_loops.values(), *_tasks, return_exceptions=True)
    _loops.clear()
    _tasks.clear()
