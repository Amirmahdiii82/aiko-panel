"""The module contract. Every business area (ERP, pricing, media, later chat) is a package under
`app/modules/<id>/` that exposes `module = Module(...)` in its `__init__.py`.

The core mounts what a module declares and nothing else:
  router      → /api/<id>/...
  web_dir     → /m/<id>/...      (index.js is the module's frontend entry: nav + pages)
  databases   → migrated on start, included in backups and health checks
  startup     → async hook run once the app is up (start workers, register scheduled jobs)
  roles       → what can be granted to a non-admin user, highest first
  notify      → bot notification kinds the owner can toggle (kind → label)
  summary     → small dict for the unified home page, computed for one user
  event_filter→ which live events a user of this module may receive
  bot         → buttons for the owners' Telegram/Bale bot: {command: botkit.Report | botkit.Flow}
  exception_handlers → domain errors turned into JSON {"detail": message} with a status code

Modules never import each other's internals. If one needs another's data it calls that
module's `api.py` (a deliberately small public surface) or listens to an event.
"""
import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter

from .db import Database

log = logging.getLogger("aiko.modules")


@dataclass
class Module:
    id: str
    name: str
    icon: str
    description: str = ""
    roles: dict[str, str] = field(default_factory=dict)
    router: APIRouter | None = None
    web_dir: Path | None = None
    databases: list[Database] = field(default_factory=list)
    startup: Callable[[], Awaitable[None]] | None = None
    shutdown: Callable[[], Awaitable[None]] | None = None
    notify: dict[str, str] = field(default_factory=dict)
    summary: Callable[[dict], Any] | None = None
    event_filter: Callable[[dict, dict], bool] | None = None
    cli: dict[str, Callable[[list[str]], None]] = field(default_factory=dict)
    bot: dict[str, Any] = field(default_factory=dict)  # command → botkit.Report or botkit.Flow
    exception_handlers: dict[type, int] = field(default_factory=dict)  # exception class → HTTP status (message shown as-is)

    @property
    def top_role(self) -> str:
        return next(iter(self.roles), "user")

    def role_rank(self, role: str | None) -> int:
        """0 = highest. Unknown roles rank below every declared one."""
        names = list(self.roles)
        return names.index(role) if role in names else len(names)


loaded: dict[str, Module] = {}


def load(ids: list[str]) -> dict[str, Module]:
    loaded.clear()
    for mid in ids:
        pkg = importlib.import_module(f"app.modules.{mid}")
        mod: Module = getattr(pkg, "module")
        if mod.id != mid:
            raise RuntimeError(f"module package {mid!r} declares id {mod.id!r}")
        loaded[mid] = mod
        log.info("module loaded: %s", mid)
    return loaded


def get(mid: str) -> Module | None:
    return loaded.get(mid)
