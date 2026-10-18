"""The owners' bot (the same Bale/Telegram bot that sends notifications), now interactive.

* /start shows a keyboard: record a sale or an expense (step-by-step flows), today's sales, this month, low stock,
  competitor prices (all from the modules), backup now, system status, and setting up the backup channel.
* Only chats listed in Settings → notification bot may use it; anyone else gets their chat id to hand to an owner.
* Backup channel without knowing its id: forward any message from the channel to the bot, or add the bot to a
  channel as admin — the bot checks it may post there, saves it, and sends the first backup.

One long-polling loop (Telegram through the outbound proxy, Bale directly). Because the loop takes every update,
the settings page's "find" buttons read the chats the loop has seen instead of calling getUpdates themselves.
"""
import asyncio
import logging

import httpx

from . import activity, backup, db, integrations
from .botkit import Reply
from .modules import loaded as modules

log = logging.getLogger("aiko.bot")
SEEN_KEY = "bot_seen_chats"
STATE_KEY = "bot_state"          # chat id → {"flow": "erp:sale", "st": {...}}: a flow in progress
USERS_KEY = "bot_users"          # chat id → panel user id (who records sales from this chat)
CANCEL = ("❌ انصراف", "x")
ALLOWED = ["message", "channel_post", "my_chat_member", "callback_query"]

CORE_BUTTONS = {
    "backup": "💾 پشتیبان همین الان",
    "status": "🩺 وضعیت سیستم",
    "channel": "📣 کانال پشتیبان",
    "help": "❓ راهنما",
}


# ---------------------------------------------------------------- what the bot has seen (for the "find" buttons)
def seen_chats() -> list[dict]:
    return db.core.get_setting(SEEN_KEY, []) or []


def _remember(chat: dict, text: str = "") -> None:
    if chat.get("id") is None:
        return
    name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) \
        or chat.get("username") or ""
    item = {"id": str(chat["id"]), "name": name, "type": chat.get("type") or "", "text": (text or "")[:60]}
    with db.core.tx() as con:
        items = [c for c in (db.core.get_setting(SEEN_KEY, [], con) or []) if c["id"] != item["id"]]
        db.core.set_setting(SEEN_KEY, [item, *items][:30], con)


# ---------------------------------------------------------------- commands
def _is_flow(entry) -> bool:
    return hasattr(entry, "start") and hasattr(entry, "handle")


def _label(entry) -> str:
    return entry.label if _is_flow(entry) else entry[0]


def _buttons() -> list[tuple[str, str]]:
    """(command, label) for every keyboard button: module flows (record a sale, ...), module reports, then core."""
    entries = [(f"{mid}:{cmd}", e) for mid, mod in modules.items() for cmd, e in mod.bot.items()]
    flows = [(c, _label(e)) for c, e in entries if _is_flow(e)]
    reports = [(c, _label(e)) for c, e in entries if not _is_flow(e)]
    return flows + reports + list(CORE_BUTTONS.items())


def _entry(cmd: str):
    mid, _, name = cmd.partition(":")
    mod = modules.get(mid)
    return mod.bot.get(name) if mod else None


def keyboard() -> dict:
    labels = [label for _, label in _buttons()]
    rows = [[{"text": t} for t in labels[i:i + 2]] for i in range(0, len(labels), 2)]
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def _command_for(text: str) -> str | None:
    text = (text or "").strip()
    if text.startswith("/"):
        word = text[1:].split()[0].split("@")[0].lower()
        aliases = {"start": "help", "menu": "help", "help": "help", "backup": "backup", "status": "status",
                   "channel": "channel"}
        if word in aliases:
            return aliases[word]
        return next((c for c, _ in _buttons() if c.split(":")[-1] == word), None)
    return next((c for c, label in _buttons() if label == text), None)


def _status_text() -> str:
    from .router import setup_status
    s = setup_status(user=None)
    mark = lambda ok: "✅" if ok else "⚪️"
    t = s["backup"]
    lines = ["🩺 وضعیت پنل آیکو",
             f"{mark(s['woo']['ok'])} سایت: {s['woo']['url'] if s['woo']['ok'] else 'وصل نیست'}",
             f"{mark(s['proxy']['ok'])} پروکسی خروجی: {'فعال' if s['proxy']['ok'] else 'تنظیم نشده'}",
             f"{mark(s['bot']['ok'])} ربات اعلان‌ها",
             f"{mark(s['backup']['ok'])} پشتیبان در کانال: "
             + (f"هر {t['hours']} ساعت، آخرین ارسال {t['last_at'][:16].replace('T', ' ')}" if t["chat_id"] and t["last_at"]
                else "کانال تنظیم نشده" if not t["chat_id"] else "هنوز ارسال نشده"),
             f"{mark(s['openrouter']['ok'])} OpenRouter (استودیو)"]
    if t["last_ok"] is False:
        lines.append(f"⚠️ خطای آخرین پشتیبان: {t['last_error']}")
    return "\n".join(lines)


HELP = ("سلام 👋 من ربات پنل آیکو هستم.\n"
        "با دکمه‌های پایین صفحه فروش و هزینه ثبت کنید یا گزارش بگیرید: فروش امروز، این ماه، موجودی کم، "
        "قیمت رقبا، پشتیبان و وضعیت. هر جا وسط کار پشیمان شدید «❌ انصراف» را بزنید.\n\n"
        "📣 برای پشتیبان خودکار در کانال: مرا در کانال «مدیر» کنید (اجازه ارسال پیام)، بعد یک پیام از همان کانال "
        "را برای من فوروارد کنید. بقیه‌اش با من.")


# ---------------------------------------------------------------- the loop
class _Api:
    def __init__(self, client: httpx.AsyncClient, base: str):
        self.client, self.base = client, base

    async def call(self, method: str, **params) -> dict:
        r = await self.client.post(self.base + method, json=params)
        try:
            return r.json()
        except ValueError:
            return {"ok": False, "description": f"HTTP {r.status_code}"}

    async def send(self, chat_id, text: str, **extra) -> dict:
        return await self.call("sendMessage", chat_id=chat_id, text=text[:4000], **extra)


def _state(chat_id) -> dict | None:
    return (db.core.get_setting(STATE_KEY, {}) or {}).get(str(chat_id))


def _save_state(chat_id, value: dict | None) -> None:
    with db.core.tx() as con:
        states = db.core.get_setting(STATE_KEY, {}, con) or {}
        if value is None:
            states.pop(str(chat_id), None)
        else:
            states[str(chat_id)] = value
        db.core.set_setting(STATE_KEY, states, con)


def _panel_user(chat_id) -> dict | None:
    uid = (db.core.get_setting(USERS_KEY, {}) or {}).get(str(chat_id))
    if not uid:
        return None
    with db.core.read() as con:
        return db.one(con.execute("SELECT id, name FROM users WHERE id = ? AND active = 1", (uid,)))


def _owners() -> list[dict]:
    with db.core.read() as con:
        return db.rows(con.execute("SELECT id, name FROM users WHERE is_admin = 1 AND active = 1 ORDER BY id"))


async def _send_reply(api: "_Api", chat_id, reply: Reply) -> None:
    if reply.done:
        await api.send(chat_id, reply.text, reply_markup=keyboard())
        return
    rows = [[{"text": label, "callback_data": data} for label, data in row] for row in reply.buttons]
    rows.append([{"text": CANCEL[0], "callback_data": CANCEL[1]}])
    await api.send(chat_id, reply.text, reply_markup={"inline_keyboard": rows})


async def _start_flow(api: "_Api", chat_id, cmd: str, user: dict) -> None:
    flow = _entry(cmd)
    st: dict = {}
    reply = await asyncio.to_thread(flow.start, user, st)
    _save_state(chat_id, None if reply.done else {"flow": cmd, "st": st})
    await _send_reply(api, chat_id, reply)


async def _continue_flow(api: "_Api", chat_id, state: dict, user: dict, *, text=None, data=None) -> None:
    flow = _entry(state["flow"])
    if not flow:
        _save_state(chat_id, None)
        return
    st = state["st"]
    try:
        reply = await asyncio.to_thread(flow.handle, user, st, text=text, data=data)
    except Exception as exc:      # a ledger validation error, a deleted product, ...
        log.exception("bot flow %s failed", state["flow"])
        msg = str(exc) if exc.__class__.__name__ == "LedgerError" else "خطایی پیش آمد"
        _save_state(chat_id, None)
        await api.send(chat_id, f"❌ {msg}. ثبت نشد؛ دوباره از دکمه‌ها شروع کنید.", reply_markup=keyboard())
        return
    _save_state(chat_id, None if reply.done else {"flow": state["flow"], "st": st})
    await _send_reply(api, chat_id, reply)


async def _ask_who(api: "_Api", chat_id) -> None:
    owners = _owners()
    await api.send(chat_id, "یک بار بگویید شما کدام کاربر پنل هستید (فروش‌ها و هزینه‌ها به نام شما ثبت می‌شوند):",
                   reply_markup={"inline_keyboard": [[{"text": o["name"], "callback_data": f"who:{o['id']}"}] for o in owners]})


def _allowed(chat_id) -> bool:
    ids = {c.strip() for c in str(activity.notify_settings().get("chat_ids") or "").replace("،", ",").split(",") if c.strip()}
    return str(chat_id) in ids


async def _set_channel(api: _Api, chat: dict, bot_id: int, reply_to=None) -> None:
    """Make `chat` the backup channel if the bot may post there, then send the first backup."""
    title = chat.get("title") or str(chat.get("id"))
    member = await api.call("getChatMember", chat_id=chat["id"], user_id=bot_id)
    res = member.get("result") or {}
    can_post = res.get("status") == "creator" or (res.get("status") == "administrator" and res.get("can_post_messages", True))
    if not can_post:
        if reply_to:
            await api.send(reply_to, f"⛔️ در کانال «{title}» اجازه ارسال پیام ندارم.\n"
                                     "کانال ← Administrators ← این ربات ← «Post Messages» را روشن کنید و دوباره پیامی فوروارد کنید.")
        return
    backup._save_telegram({"chat_id": str(chat["id"]), "enabled": True})
    activity.record(None, "core", "backup", f"کانال پشتیبان تنظیم شد: {title}", "از طریق ربات")
    await api.send(chat["id"], "✅ این کانال برای پشتیبان خودکار پنل آیکو تنظیم شد. هر ساعت یک فایل از همه داده‌ها اینجا می‌آید.")
    result = await backup.send_to_telegram(manual=True)
    if reply_to:
        await api.send(reply_to, f"✅ کانال «{title}» برای پشتیبان تنظیم شد و "
                                 + ("اولین پشتیبان فرستاده شد. از این به بعد هر ساعت خودکار." if result["ok"]
                                    else f"ولی ارسال اولین پشتیبان ناموفق بود: {result['error']}"))


async def _run_command(api: _Api, chat_id, cmd: str, bot_id: int) -> None:
    if cmd == "help":
        await api.send(chat_id, HELP, reply_markup=keyboard())
    elif cmd == "status":
        await api.send(chat_id, await asyncio.to_thread(_status_text), reply_markup=keyboard())
    elif cmd == "backup":
        t = backup.telegram_settings()
        if not t["chat_id"]:
            await api.send(chat_id, "کانال پشتیبان هنوز تنظیم نشده. «📣 کانال پشتیبان» را بزنید.")
            return
        await api.send(chat_id, "⏳ در حال گرفتن پشتیبان…")
        r = await backup.send_to_telegram(manual=True)
        await api.send(chat_id, f"✅ پشتیبان ({r['size'] / 1048576:.2f} MB) در کانال فرستاده شد." if r["ok"]
                       else f"❌ ناموفق: {r['error']}")
    elif cmd == "channel":
        t = backup.telegram_settings()
        now = f"کانال فعلی: {t['chat_id']}\n\n" if t["chat_id"] else ""
        await api.send(chat_id, now + "۱) مرا در کانال پشتیبان «مدیر» کنید (اجازه Post Messages).\n"
                                      "۲) یک پیام از همان کانال را برای من فوروارد کنید.\n"
                                      "خودم کانال را پیدا و تنظیم می‌کنم و اولین پشتیبان را می‌فرستم.")
    else:
        entry = _entry(cmd)
        if not entry:
            return
        if _is_flow(entry):
            user = _panel_user(chat_id)
            if not user:
                _save_state(chat_id, {"flow": None, "pending": cmd})
                await _ask_who(api, chat_id)
                return
            await _start_flow(api, chat_id, cmd, user)
            return
        try:
            text = await asyncio.to_thread(entry[1])
        except Exception:
            log.exception("bot report %s failed", cmd)
            text = "❌ گزارش آماده نشد؛ دوباره امتحان کنید."
        await api.send(chat_id, text, reply_markup=keyboard())


async def _callback(api: _Api, cq: dict, bot_id: int) -> None:
    """An inline button was tapped."""
    await api.call("answerCallbackQuery", callback_query_id=cq["id"])
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
    data = cq.get("data") or ""
    if chat_id is None or not _allowed(chat_id):
        return
    if data == CANCEL[1]:
        _save_state(chat_id, None)
        await api.send(chat_id, "لغو شد؛ چیزی ثبت نشد.", reply_markup=keyboard())
        return
    if data.startswith("who:"):
        uid = int(data[4:])
        if uid not in {o["id"] for o in _owners()}:
            return
        with db.core.tx() as con:
            users = db.core.get_setting(USERS_KEY, {}, con) or {}
            users[str(chat_id)] = uid
            db.core.set_setting(USERS_KEY, users, con)
        user = _panel_user(chat_id)
        pending = (_state(chat_id) or {}).get("pending")
        await api.send(chat_id, f"✅ ثبت شد: شما «{user['name']}» هستید.", reply_markup=keyboard())
        if pending:
            await _start_flow(api, chat_id, pending, user)
        else:
            _save_state(chat_id, None)
        return
    state = _state(chat_id)
    if not state or not state.get("flow"):
        await api.send(chat_id, "این دکمه قدیمی است؛ از دکمه‌های پایین دوباره شروع کنید.", reply_markup=keyboard())
        return
    await _continue_flow(api, chat_id, state, _panel_user(chat_id), data=data)


async def handle(api: _Api, upd: dict, bot_id: int) -> None:
    if "callback_query" in upd:
        await _callback(api, upd["callback_query"], bot_id)
        return
    if "my_chat_member" in upd:
        m = upd["my_chat_member"]
        chat = m.get("chat") or {}
        _remember(chat)
        new = (m.get("new_chat_member") or {}).get("status")
        # added as admin to a channel and no backup channel yet: that is the backup channel
        if chat.get("type") == "channel" and new == "administrator" and not backup.telegram_settings()["chat_id"]:
            await _set_channel(api, chat, bot_id)
        return
    if "channel_post" in upd:
        _remember(upd["channel_post"].get("chat") or {}, upd["channel_post"].get("text") or "")
        return
    msg = upd.get("message")
    if not msg:
        return
    chat = msg.get("chat") or {}
    _remember(chat, msg.get("text") or "")
    if chat.get("type") != "private":
        return
    if not _allowed(chat["id"]):
        await api.send(chat["id"], f"این ربات فقط برای مدیران پنل آیکو است.\nشناسه شما: {chat['id']}\n"
                                   "اگر مدیر هستید، این شناسه را در پنل ← تنظیمات ← ربات اعلان‌ها اضافه کنید.")
        return
    # a message forwarded from a channel: use that channel for backups
    origin = msg.get("forward_origin") or {}
    fchat = origin.get("chat") if origin.get("type") == "channel" else msg.get("forward_from_chat")
    if fchat and fchat.get("type") == "channel":
        _remember(fchat)
        await _set_channel(api, fchat, bot_id, reply_to=chat["id"])
        return
    cmd = _command_for(msg.get("text") or "")
    state = _state(chat["id"])
    if cmd:
        if state:
            _save_state(chat["id"], None)        # a main button in the middle of a flow: start over with that
        await _run_command(api, chat["id"], cmd, bot_id)
    elif state and state.get("flow"):
        await _continue_flow(api, chat["id"], state, _panel_user(chat["id"]), text=msg.get("text") or "")
    else:
        await api.send(chat["id"], "یکی از دکمه‌های پایین را بزنید 👇", reply_markup=keyboard())


async def loop() -> None:
    """Long-poll the notification bot forever (restarted by jobs.supervise if it ever crashes)."""
    bot_id, token_seen = None, None
    while True:
        s = activity.notify_settings()
        token, kind = (s.get("token") or "").strip(), s.get("bot") or "bale"
        base = activity.BOT_BASE.get(kind)
        if not token or not base:
            await asyncio.sleep(30)
            continue
        if token != token_seen:
            bot_id, token_seen = None, token
        try:
            async with activity.bot_client(kind, timeout=70) as client:
                api = _Api(client, base.format(token=token))
                if bot_id is None:
                    me = await api.call("getMe")
                    if not me.get("ok"):
                        log.warning("bot token rejected: %s", me.get("description"))
                        await asyncio.sleep(120)
                        continue
                    bot_id = me["result"]["id"]
                offset = db.core.get_setting("bot_offset", 0) or 0
                r = await api.call("getUpdates", offset=offset, timeout=50, allowed_updates=ALLOWED)
                updates = (r.get("result") or []) if r.get("ok") else []
                if not r.get("ok"):
                    log.warning("getUpdates failed: %s", r.get("description"))
                    await asyncio.sleep(15)
                for upd in updates:
                    db.core.set_setting("bot_offset", upd["update_id"] + 1)
                    try:
                        await handle(api, upd, bot_id)
                    except Exception:
                        log.exception("bot update failed")
                if not updates and kind == "bale":
                    await asyncio.sleep(2)          # in case the server ignores long polling
        except (httpx.HTTPError, ValueError) as exc:
            log.info("bot poll: %s (proxy=%s)", exc.__class__.__name__, bool(integrations.proxy_url()))
            await asyncio.sleep(15)


def chats_for(token: str, kind: str) -> list[dict] | None:
    """The chats the polling loop has seen, when it is the bot being asked about (else None = ask Telegram)."""
    s = activity.notify_settings()
    if (s.get("token") or "").strip() == token and (s.get("bot") or "bale") == kind:
        return seen_chats()
    return None
