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
        sent.append(backup.channel_settings()["chat_id"])
        return {"ok": True, "error": "", "size": 1000}
    monkeypatch.setattr(backup, "send_to_channel", fake_send)
    api = FakeApi()
    _run(api, _msg("سلام", forward_origin={"type": "channel", "chat": {"id": -100777, "type": "channel", "title": "Aiko Backup"}}))
    t = backup.channel_settings()
    assert t["chat_id"] == "-100777" and t["enabled"] and sent == ["-100777"]
    assert "Aiko Backup" in api.sent[-1][1]
    # the channels the bot saw are what the panel's "find" button shows
    assert any(c["id"] == "-100777" for c in owner.get("/api/backup/channel/chats").json())


def test_channel_where_the_bot_cannot_post_is_refused(owner):
    _setup(owner)
    api = FakeApi(member_status="member")
    _run(api, _msg("x", forward_origin={"type": "channel", "chat": {"id": -100888, "type": "channel", "title": "C"}}))
    assert backup.channel_settings()["chat_id"] == "" and "Post Messages" in api.sent[-1][1]


def test_made_admin_of_a_channel_becomes_the_backup_channel(owner, monkeypatch):
    _setup(owner)

    async def fake_send(manual=False):
        return {"ok": True, "error": "", "size": 1}
    monkeypatch.setattr(backup, "send_to_channel", fake_send)
    def added_by(uid, cid):
        return {"update_id": 2, "my_chat_member": {"chat": {"id": cid, "type": "channel", "title": "B"}, "from": {"id": uid},
                                                   "new_chat_member": {"status": "administrator"}}}
    _run(FakeApi(), added_by(123456, -100555))          # a stranger adds the bot to THEIR channel: never adopted
    assert backup.channel_settings()["chat_id"] == ""
    _run(FakeApi(), added_by(OWNER, -100999))           # an owner adds it: that is the backup channel
    assert backup.channel_settings()["chat_id"] == "-100999"
    assert db.core.get_setting("bot_seen_chats")[0]["id"] == "-100999"


def _cb(data, chat_id=OWNER):
    return {"update_id": 3, "callback_query": {"id": "q", "data": data, "message": {"chat": {"id": chat_id, "type": "private"}}}}


def _owner_id():
    with db.core.read() as con:
        return con.execute("SELECT id FROM users WHERE username = 'amir'").fetchone()[0]


def test_record_a_sale_from_the_bot(owner):
    _setup(owner)
    pid = owner.post("/api/erp/products", json={"name": "ریمل اسنس", "price": 550_000, "stock": 5}, headers=H).json()["id"]
    api = FakeApi()
    _run(api, _msg("🛍 ثبت فروش"))
    assert "کدام مدیر" in api.sent[-1][1]                        # asked once who this chat is
    _run(api, _cb(f"who:{_owner_id()}"))
    _run(api, _msg("ریمل"))                                       # one match: goes straight to quantity
    assert "چند عدد" in api.sent[-1][1]
    _run(api, _cb("q:2"))
    _run(api, _msg("۵۰۰ هزار"))                                   # a different price, typed the way people type it
    _run(api, _cb("next"))
    _run(api, _cb("ch:instagram"))
    _run(api, _msg("مریم"))
    assert "بررسی" in api.sent[-1][1] and "۱٬۰۰۰٬۰۰۰" in api.sent[-1][1]
    _run(api, _cb("save"))
    assert "ثبت شد" in api.sent[-1][1] and "مانده ۳" in api.sent[-1][1]
    from app.modules.erp import db as erp_db
    with erp_db.read() as con:
        sale = erp_db.one(con.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 1"))
        assert con.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()[0] == 3
    assert sale["total"] == 1_000_000 and sale["channel"] == "instagram" and sale["customer_name"] == "مریم"
    assert sale["created_by"] == _owner_id()


def test_record_an_expense_and_cancel_a_flow(owner):
    _setup(owner)
    from app.core import bot as b
    db.core.set_setting(b.USERS_KEY, {str(OWNER): _owner_id()})
    api = FakeApi()
    _run(api, _msg("🛍 ثبت فروش"))
    _run(api, _cb("x"))
    assert "لغو" in api.sent[-1][1] and b._state(OWNER) is None
    _run(api, _msg("💸 ثبت هزینه"))
    _run(api, _msg("250 هزار"))
    _run(api, _cb("c:0"))
    _run(api, _cb("skip"))
    acc = api.sent[-1][2]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    _run(api, _cb(acc))
    _run(api, _cb("save"))
    assert "هزینه" in api.sent[-1][1] and "ثبت شد" in api.sent[-1][1]
    from app.modules.erp import db as erp_db
    with erp_db.read() as con:
        assert con.execute("SELECT amount FROM expenses ORDER BY id DESC LIMIT 1").fetchone()[0] == 250_000


def test_amounts_typed_the_iranian_way():
    from app.core.botkit import parse_amount
    assert parse_amount("540.000") == 540_000 and parse_amount("۱.۲۵۰.۰۰۰") == 1_250_000
    assert parse_amount("۵۴۰ هزار") == 540_000 and parse_amount("1.5 میلیون") == 1_500_000
    assert parse_amount("۵۴۰٬۰۰۰ تومان") == 540_000 and parse_amount("abc") is None
    # a decimal with a unit is never read as thousands (1.5 million, not 1.5 billion)
    assert parse_amount("1.500 میلیون") == 1_500_000 and parse_amount("۱٫۲۵۰ میلیون") == 1_250_000
    assert parse_amount("۲٫۵ هزار") == 2_500 and parse_amount("0") == 0


def test_demoted_owner_loses_the_bot_and_stale_who_buttons_do_nothing(owner):
    _setup(owner)
    from app.core import bot as b
    db.core.set_setting(b.USERS_KEY, {str(OWNER): _owner_id()})
    owner.post("/api/erp/products", json={"name": "کرم", "price": 100_000, "stock": 3}, headers=H)
    api = FakeApi()
    _run(api, _msg("🛍 ثبت فروش"))
    _run(api, _msg("کرم"))
    _run(api, _cb("q:1"))
    _run(api, _cb(f"who:{_owner_id()}"))                 # an old button from earlier: ignored, cart untouched
    assert b._state(OWNER)["st"]["step"] == "price"
    with db.core.tx() as con:                           # this owner is demoted mid-sale
        con.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (_owner_id(),))
    _run(api, _cb("pr:default"))
    assert "کدام مدیر" in api.sent[-1][1]               # asked again; nothing recorded under the demoted user
    from app.modules.erp import db as erp_db
    with erp_db.read() as con:
        assert con.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0


def test_an_error_keeps_the_cart_and_typing_a_name_adds_another_item(owner):
    _setup(owner)
    from app.core import bot as b
    db.core.set_setting(b.USERS_KEY, {str(OWNER): _owner_id()})
    for name in ("رژ لب", "ریمل"):
        owner.post("/api/erp/products", json={"name": name, "price": 200_000, "stock": 5}, headers=H)
    api = FakeApi()
    _run(api, _msg("🛍 ثبت فروش"))
    _run(api, _msg("رژ"))
    _run(api, _cb("q:1"))
    _run(api, _cb("pr:default"))
    _run(api, _msg("ریمل"))                              # typed instead of tapping ➕: added, not skipped
    _run(api, _cb("q:1"))
    _run(api, _cb("pr:default"))
    assert len(b._state(OWNER)["st"]["items"]) == 2
    _run(api, _cb("next"))
    _run(api, _cb("ch:in_person"))
    _run(api, _cb("skip"))
    _run(api, _cb("discount"))
    _run(api, _msg("۹۰۰ هزار"))                          # more than the sale: refused right at this step
    assert "بیشتر است" in api.sent[-1][1] and b._state(OWNER)["st"]["step"] == "discount"
    _run(api, _msg("۵۰ هزار"))
    _run(api, _cb("save"))
    from app.modules.erp import db as erp_db
    with erp_db.read() as con:
        assert con.execute("SELECT total FROM sales").fetchone()[0] == 350_000
