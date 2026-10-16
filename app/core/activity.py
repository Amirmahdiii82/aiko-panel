"""One activity feed for every module, the notification bell, and Bale/Telegram bot messages.

Modules call `record(con, module, kind, title, ...)` inside their own transaction. The row is written
to core.db only after that transaction commits — so a rolled-back sale never shows up as "sold",
and the module's database file never takes part in a cross-file transaction.
"""
import logging
import sqlite3

import httpx

from . import db, events
from .modules import loaded as modules

log = logging.getLogger("aiko.activity")

BOT_BASE = {"bale": "https://tapi.bale.ai/bot{token}/", "telegram": "https://api.telegram.org/bot{token}/"}
DEFAULT_NOTIFY = {"bot": "bale", "token": "", "chat_ids": "", "kinds": {}}


def record(con: sqlite3.Connection | None, module: str, kind: str, title: str, body: str = "", *,
           user_id: int | None = None, level: str = "info", link: str = "", notify: bool = False,
           bot: bool | str = False) -> None:
    """Record something that happened. `notify` puts it in the bell; `bot` also sends it to the
    configured Bale/Telegram chats if the owner switched on `<module>.<kind>` in notification settings.
    Pass a string as `bot` when the toggle is a different kind (e.g. a website sale toggled as "web_order")."""
    def write():
        _write(module, kind, title, body, user_id=user_id, level=level, link=link, notify=notify, bot=bot)
    if con is None:
        write()
    else:
        con.after_commit.append(write)


def _write(module, kind, title, body, *, user_id, level, link, notify, bot) -> None:
    created = db.now()
    with db.core.tx() as con:
        cur = con.execute(
            "INSERT INTO activity (created_at, module, user_id, kind, level, title, body, link, notify) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (created, module, user_id, kind, level, title, body or "", link or "", 1 if notify else 0))
        item = {"id": cur.lastrowid, "created_at": created, "module": module, "user_id": user_id, "kind": kind,
                "level": level, "title": title, "body": body or "", "link": link or "", "notify": 1 if notify else 0}
        events.publish_after(con, {"type": "activity", "module": module, "item": item})
        if bot:
            settings = notify_settings(con)
            if _bot_wants(settings, module, bot if isinstance(bot, str) else kind):
                text = f"{title}\n{body}".strip()
                con.after_commit.append(lambda: events.run_soon(lambda: send_bot(text)))


def _bot_wants(settings: dict, module: str, kind: str) -> bool:
    if not settings.get("token") or not settings.get("chat_ids"):
        return False
    kinds = settings.get("kinds") or {}
    key = f"{module}.{kind}"
    if key in kinds:
        return bool(kinds[key])
    mod = modules.get(module)
    return bool(mod and kind in mod.notify)          # kinds a module declares are on until switched off


def notify_settings(con=None) -> dict:
    return {**DEFAULT_NOTIFY, **(db.core.get_setting("notify", {}, con) or {})}


def notify_kinds() -> list[dict]:
    """Every toggle the settings page shows, grouped by module."""
    settings = notify_settings()
    out = []
    for mod in modules.values():
        for kind, label in mod.notify.items():
            key = f"{mod.id}.{kind}"
            out.append({"key": key, "module": mod.id, "module_name": mod.name, "label": label,
                        "on": bool((settings.get("kinds") or {}).get(key, True))})
    return out


async def send_bot(text: str, settings: dict | None = None) -> tuple[bool, str]:
    settings = settings or notify_settings()
    token = (settings.get("token") or "").strip()
    chat_ids = [c.strip() for c in str(settings.get("chat_ids") or "").replace("،", ",").split(",") if c.strip()]
    base = BOT_BASE.get(settings.get("bot") or "bale")
    if not token or not chat_ids or not base:
        return False, "توکن ربات یا شناسه چت تنظیم نشده"
    url = base.format(token=token) + "sendMessage"
    errors = []
    async with httpx.AsyncClient(timeout=15) as client:
        for chat_id in chat_ids:
            try:
                r = await client.post(url, json={"chat_id": chat_id, "text": text})
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if r.status_code != 200 or not body.get("ok", False):
                    errors.append(f"{chat_id}: {body.get('description') or r.status_code}")
            except httpx.HTTPError as exc:
                errors.append(f"{chat_id}: {exc.__class__.__name__}")
    if errors:
        log.warning("bot send failed: %s", errors)
        return False, "؛ ".join(errors)
    return True, "ارسال شد"


async def bot_updates(settings: dict) -> list[dict]:
    """Recent chats that messaged the bot, so the owner can pick a chat id without guessing."""
    token = (settings.get("token") or "").strip()
    base = BOT_BASE.get(settings.get("bot") or "bale")
    if not token or not base:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(base.format(token=token) + "getUpdates")
        data = r.json()
    chats = {}
    for upd in data.get("result", []) if isinstance(data, dict) else []:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) \
                or chat.get("username") or ""
            chats[str(chat["id"])] = {"id": str(chat["id"]), "name": name, "text": (msg.get("text") or "")[:60]}
    return list(chats.values())
