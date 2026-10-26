"""When competitor prices are read automatically: a daily timetable (Tehran time), set in Settings → قیمت رقبا.
Until it is set there, CRAWL_TIMES from the server's .env is the default. Saving re-registers the daily jobs."""
import re

from ...core import jobs
from ...core.text import fold
from . import config, db
from .runner import start_crawl

KEY = "crawl_times"
PREFIX = "pricing.crawl."
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    pass


def times() -> list[str]:
    saved = db.get_setting(KEY)
    return list(saved) if isinstance(saved, list) else list(config.CRAWL_TIMES)


async def _scheduled() -> None:
    # async so APScheduler runs it on the event loop (sync jobs run in a worker thread with no loop)
    start_crawl("schedule")


def apply() -> None:
    """(Re)register one daily crawl per time in the timetable."""
    jobs.remove(PREFIX)
    for t in times():
        jobs.daily(PREFIX + t, t, _scheduled)


def next_run() -> str | None:
    runs = jobs.next_runs(PREFIX)
    return runs[0].isoformat() if runs else None


def save(raw: list) -> list[str]:
    clean = set()
    for t in raw or []:
        m = _HHMM.match(fold(str(t)).strip())
        if not m:
            raise ScheduleError(f"ساعت «{t}» درست نیست؛ مثل 09:00")
        clean.add(f"{int(m.group(1)):02d}:{m.group(2)}")
    if len(clean) > 6:
        raise ScheduleError("حداکثر ۶ بار در روز")
    db.set_setting(KEY, sorted(clean))
    apply()
    return sorted(clean)
