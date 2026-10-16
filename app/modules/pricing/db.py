"""Price checker storage (data/pricing.db) with the small API the crawler code always used.

The crawler issues many tiny queries from the event loop, so this module keeps one shared connection
guarded by a lock (as the standalone app did) instead of opening a connection per query.
Timestamps here are UTC ISO strings (the UI converts them).
"""
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from ...core import db as core_db
from ...core.db import utcnow as now_iso  # noqa: F401 — re-exported for crawler code

database = core_db.Database("pricing", migrations=Path(__file__).resolve().parent / "migrations", attach_core=False)
_lock = threading.RLock()
_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = database.connect(check_same_thread=False)
    return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


@contextmanager
def tx():
    """Serialized write transaction."""
    with _lock:
        c = conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise


def q(sql: str, params=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


def q1(sql: str, params=()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def get_setting(key: str, default=None):
    row = q1("SELECT value FROM settings WHERE key=?", (key,))
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return row["value"]


def set_setting(key: str, value) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
