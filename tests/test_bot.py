"""The owners' bot: only owners' chats get answers, module buttons work, and the backup channel is found from a
forwarded message or when the bot is made admin of a channel."""
import asyncio

from app.core import backup, bot, db

from .conftest import H

OWNER = 2047621589


class FakeApi:
    def __init__(self, member_status="administrator", can_post=True):
        self.sent, self.member = [], {"status": member_status, "can_post_messages": can_post}

    async def call(self, method, **params):
        if method == "getChatMember":
            return {"ok": True, "result": self.member}
        return {"ok": True, "result": {}}

    async def send(self, chat_id, text, **extra):
        self.sent.append((chat_id, text, extra))
        return {"ok": True}


def _msg(text=None, chat_id=OWNER, **extra):
    return {"update_id": 1, "message": {"chat": {"id": chat_id, "type": "private", "first_name": "Amir"}, "text": text, **extra}}


def _setup(owner):
    owner.put("/api/notify", json={"bot": "telegram", "token": "1:x", "chat_ids": str(OWNER)}, headers=H)


def _run(api, upd):
    asyncio.run(bot.handle(api, upd, bot_id=99))


def test_strangers_get_their_id_and_nothing_else(owner):
    _setup(owner)
    api = FakeApi()
    _run(api, _msg("/start", chat_id=555))
    assert len(api.sent) == 1 and "555" in api.sent[0][1] and "reply_markup" not in api.sent[0][2]


def test_start_shows_buttons_from_every_module_and_reports_answer(owner):
    _setup(owner)
    api = FakeApi()
    _run(api, _msg("/start"))
    labels = [b["text"] for row in api.sent[0][2]["reply_markup"]["keyboard"] for b in row]
    assert "📊 فروش امروز" in labels and "🏷 قیمت رقبا" in labels and "💾 پشتیبان همین الان" in labels
    owner.post("/api/erp/products", json={"name": "ریمل", "price": 300_000, "stock": 1, "low_stock": 2}, headers=H)
    _run(api, _msg("⚠️ موجودی کم"))
    assert "ریمل" in api.sent[-1][1]
    _run(api, _msg("📊 فروش امروز"))
    assert "امروز" in api.sent[-1][1]


def test_forwarding_a_channel_message_sets_the_backup_channel(owner, monkeypatch):
    _setup(owner)
    sent = []

    async def fake_send(manual=False):
        sent.append(backup.telegram_settings()["chat_id"])
        return {"ok": True, "error": "", "size": 1000}
    monkeypatch.setattr(backup, "send_to_telegram", fake_send)
    api = FakeApi()
    _run(api, _msg("سلام", forward_origin={"type": "channel", "chat": {"id": -100777, "type": "channel", "title": "Aiko Backup"}}))
    t = backup.telegram_settings()
    assert t["chat_id"] == "-100777" and t["enabled"] and sent == ["-100777"]
    assert "Aiko Backup" in api.sent[-1][1]
    # the channels the bot saw are what the panel's "find" button shows
    assert any(c["id"] == "-100777" for c in owner.get("/api/backup/telegram/chats").json())


def test_channel_where_the_bot_cannot_post_is_refused(owner):
    _setup(owner)
    api = FakeApi(member_status="member")
    _run(api, _msg("x", forward_origin={"type": "channel", "chat": {"id": -100888, "type": "channel", "title": "C"}}))
    assert backup.telegram_settings()["chat_id"] == "" and "Post Messages" in api.sent[-1][1]


def test_made_admin_of_a_channel_becomes_the_backup_channel(owner, monkeypatch):
    _setup(owner)

    async def fake_send(manual=False):
        return {"ok": True, "error": "", "size": 1}
    monkeypatch.setattr(backup, "send_to_telegram", fake_send)
    upd = {"update_id": 2, "my_chat_member": {"chat": {"id": -100999, "type": "channel", "title": "B"},
                                              "new_chat_member": {"status": "administrator"}}}
    _run(FakeApi(), upd)
    assert backup.telegram_settings()["chat_id"] == "-100999"
    assert db.core.get_setting("bot_seen_chats")[0]["id"] == "-100999"
