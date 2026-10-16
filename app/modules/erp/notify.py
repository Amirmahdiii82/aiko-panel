"""ERP's view of the core activity feed and live events (keeps the call style ERP code always used)."""
from ...core import activity as core_activity
from ...core import events

MODULE = "erp"

# kinds the owner can toggle for the Bale/Telegram bot (shown on the core notification settings page)
BOT_KINDS = {
    "sale": "فروش جدید (همه کانال‌ها)",
    "web_order": "سفارش جدید سایت",
    "stock_out": "تمام شدن موجودی",
    "low_stock": "رو به اتمام بودن موجودی",
    "sync_error": "خطای همگام‌سازی سایت",
}
# old per-flag names → kind
_FLAG = {"on_sale": "sale", "on_web_order": "web_order", "on_stock_out": "stock_out", "on_low_stock": "low_stock",
         "on_sync_error": "sync_error"}


def activity(con, kind: str, title: str, body: str = "", *, user_id: int | None = None, level: str = "info",
             link: str = "", notify: bool = False, bot: str | None = None) -> None:
    """Record an ERP event. `bot` names the notification toggle (a BOT_KINDS key or an old `on_*` flag);
    the owner decides in Settings → Notifications whether that kind reaches the bot."""
    core_activity.record(con, MODULE, kind, title, body, user_id=user_id, level=level, link=link, notify=notify,
                         bot=_FLAG.get(bot, bot) if bot else False)


def publish(event: dict) -> None:
    events.publish({"module": MODULE, **event})


def publish_after(con, event: dict) -> None:
    events.publish_after(con, {"module": MODULE, **event})


def visible_to(event: dict, user: dict) -> bool:
    """Sellers (friends who sell for you) only see stock changes and their own activity."""
    if user["role"] == "admin":
        return True
    if event.get("type") == "product":
        return True
    if event.get("type") == "activity":
        item = event.get("item") or {}
        return item.get("user_id") == user["id"] or item.get("kind") in ("stock_out", "low_stock")
    return event.get("type") == "refresh" and event.get("scope") in ("products", "sales")
