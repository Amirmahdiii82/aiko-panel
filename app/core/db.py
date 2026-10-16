"""SQLite storage: one database file per module, plus `core.db` for identity and the activity feed.

Why one file per module:
* each module owns its data and can be backed up, restored or wiped on its own;
* SQLite allows one writer per file, so the price crawler's bursts never queue behind a sale;
* nothing outside a module can JOIN into its tables — modules talk through Python APIs and events.

The single exception is identity: every module connection ATTACHes `core.db` read-only as `core`,
so queries can show a user's name (`JOIN core.users`). Writes to core go through `app.core` only.
Note: in WAL mode a transaction is atomic per file, never across files; cross-module side effects
(activity rows, notifications) therefore run *after* the owning transaction commits.

Schema changes are versioned migrations in `<module>/migrations/NNNN_name.sql` (or `.py` with
`def up(con)`), tracked with `PRAGMA user_version`.
"""
import importlib.util
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger("aiko.db")
TZ = ZoneInfo(config.TIMEZONE)
_MIGRATION = re.compile(r"^(\d{4})_[\w-]+\.(sql|py)$")


def now() -> str:
    """Local (Tehran) timestamp with seconds, the format all modules store."""
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return datetime.now(TZ).date().isoformat()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def one(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None


class Conn(sqlite3.Connection):
    """A connection that runs callbacks once its transaction has committed (live updates, activity)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.after_commit: list[Callable[[], None]] = []


class Database:
    def __init__(self, name: str, *, migrations: Path | None = None, attach_core: bool = True,
                 on_connect: Callable[[Conn], None] | None = None):
        self.name = name
        self.migrations = migrations
        self.attach_core = attach_core and name != "core"
        self.on_connect = on_connect

    @property
    def path(self) -> Path:
        return config.DATA_DIR / f"{self.name}.db"

    # ------------------------------------------------------------------ connections
    def connect(self, *, check_same_thread: bool = True) -> Conn:
        con = sqlite3.connect(self.path.as_uri(), uri=True, timeout=30, isolation_level=None, factory=Conn,
                              check_same_thread=check_same_thread)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 30000")
        con.execute("PRAGMA synchronous = NORMAL")   # safe with WAL; a power cut loses at most the last commit
        if self.attach_core:
            con.execute("ATTACH DATABASE ? AS core", (CORE_PATH().as_uri() + "?mode=ro",))
        if self.on_connect:
            self.on_connect(con)
        return con

    @contextmanager
    def read(self):
        con = self.connect()
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def tx(self):
        """A write transaction. BEGIN IMMEDIATE serialises writers so counts never race."""
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        for callback in con.after_commit:
            try:
                callback()
            except Exception:  # a failed side effect must never undo or hide the committed write
                log.exception("after-commit callback failed (%s)", self.name)

    # ------------------------------------------------------------------ schema
    def version(self) -> int:
        with self.read() as con:
            return con.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> list[str]:
        """Apply pending migrations in order. Returns the names applied."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, isolation_level=None)
        try:
            con.execute("PRAGMA journal_mode = WAL")
            current = con.execute("PRAGMA user_version").fetchone()[0]
        finally:
            con.close()
        applied = []
        for number, path in self._migration_files():
            if number <= current:
                continue
            con = self.connect()
            try:
                if path.suffix == ".sql":
                    con.executescript(f"BEGIN IMMEDIATE;\n{path.read_text(encoding='utf-8')}\n"
                                      f";PRAGMA user_version = {number};\nCOMMIT;")
                else:
                    spec = importlib.util.spec_from_file_location(f"_mig_{self.name}_{number}", path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    con.execute("BEGIN IMMEDIATE")
                    mod.up(con)
                    con.execute(f"PRAGMA user_version = {number}")
                    con.execute("COMMIT")
            except BaseException:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                log.error("migration %s/%s failed", self.name, path.name)
                raise
            finally:
                con.close()
            applied.append(path.name)
            log.info("migrated %s → %s", self.name, path.name)
        return applied

    def _migration_files(self) -> list[tuple[int, Path]]:
        if not self.migrations or not self.migrations.is_dir():
            return []
        found = []
        for p in self.migrations.iterdir():
            m = _MIGRATION.match(p.name)
            if m:
                found.append((int(m.group(1)), p))
        found.sort()
        numbers = [n for n, _ in found]
        if len(numbers) != len(set(numbers)):
            raise RuntimeError(f"duplicate migration numbers in {self.migrations}")
        return found

    # ------------------------------------------------------------------ backup
    def backup_to(self, dest: Path) -> Path:
        """Consistent online copy (safe while the app is writing)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.path)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return dest

    def check(self) -> None:
        with self.read() as con:
            con.execute("SELECT 1").fetchone()

    # ------------------------------------------------------------------ key/value settings (every module db has a `settings` table)
    def get_setting(self, key: str, default=None, con: sqlite3.Connection | None = None):
        own = con is None
        con = con or self.connect()
        try:
            row = con.execute("SELECT value FROM main.settings WHERE key = ?", (key,)).fetchone()
            if not row or row[0] is None:
                return default
            try:
                return json.loads(row[0])
            except ValueError:
                return row[0]
        finally:
            if own:
                con.close()

    def set_setting(self, key: str, value, con: sqlite3.Connection | None = None) -> None:
        own = con is None
        con = con or self.connect()
        try:
            con.execute("INSERT INTO main.settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))
        finally:
            if own:
                con.close()


def CORE_PATH() -> Path:  # noqa: N802 - evaluated lazily so tests can point DATA_DIR elsewhere
    return config.DATA_DIR / "core.db"


core = Database("core", migrations=Path(__file__).resolve().parent / "migrations")

# every Database the app knows about, for backups and health checks (modules register theirs)
registry: dict[str, Database] = {"core": core}


def register(database: Database) -> Database:
    registry[database.name] = database
    return database
