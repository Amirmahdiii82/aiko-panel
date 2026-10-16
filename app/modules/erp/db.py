"""ERP storage (data/erp.db) — the same small API the ERP code always used, backed by the core Database.

ERP queries keep writing `JOIN users u ON ...`: every ERP connection gets a TEMP VIEW `users` that
projects core identity (read-only) together with the ERP staff profile and the user's ERP role.
"""
import json
from pathlib import Path

from ...core import db as core_db
from ...core.db import now, one, rows, today, TZ  # noqa: F401 — re-exported for ERP code
from . import config

_USERS_VIEW = """
CREATE TEMP VIEW IF NOT EXISTS users AS
SELECT u.id, u.username, u.name, u.active, u.created_at, u.notif_seen,
       CASE WHEN u.is_admin = 1 THEN 'admin' ELSE IFNULL(g.role, '') END AS role,
       s.partner_id, s.account_id, IFNULL(s.commission_pct, 0) AS commission_pct
FROM core.users u
LEFT JOIN core.user_modules g ON g.user_id = u.id AND g.module = 'erp'
LEFT JOIN main.staff s ON s.user_id = u.id
"""


def _on_connect(con) -> None:
    con.execute(_USERS_VIEW)


database = core_db.Database("erp", migrations=Path(__file__).resolve().parent / "migrations", on_connect=_on_connect)

DEFAULT_SETTINGS = {
    "shop": {"name": "آیکو کازمتیکس", "low_stock": 2},
    "product_categories": ["لب", "صورت", "چشم", "ابرو", "مو", "بدن", "ابزار و براش", "اکسسوری", "مراقبت پوست"],
    "expense_categories": [
        "بسته‌بندی", "ارسال و پست", "تبلیغات و بازاریابی", "سایت و دامنه", "نرم‌افزار و ابزار",
        "پیامک", "مالیات و مجوز", "حمل و رفت‌وآمد", "پذیرایی", "تجهیزات", "پورسانت فروش", "سایر",
    ],
    "channel_accounts": {},           # channel -> default account id for money received
    "woo": {
        "url": config.WOO_URL, "key": "", "secret": "", "webhook_secret": "", "query_auth": False,
        "auto_push": False, "pull_minutes": 3, "last_order_sync": "",
    },
}


def connect():
    return database.connect()


def read():
    return database.read()


def tx():
    return database.tx()


def get_setting(key: str, default=None, con=None):
    return database.get_setting(key, default, con)


def set_setting(key: str, value, con=None) -> None:
    database.set_setting(key, value, con)


def seed_settings() -> None:
    """Insert default settings; settings that gained keys in a later version keep their values and get the new defaults."""
    with tx() as con:
        for key, value in DEFAULT_SETTINGS.items():
            row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row is None:
                set_setting(key, value, con)
            elif isinstance(value, dict):
                saved = json.loads(row["value"]) if row["value"] else {}
                merged = {**value, **saved}
                if merged != saved:
                    set_setting(key, merged, con)
