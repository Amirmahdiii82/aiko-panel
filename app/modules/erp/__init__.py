"""ERP module: inventory, quick sale, sales from every channel, purchases, expenses, partner accounts, WooCommerce sync."""
import json
import sys
from pathlib import Path

from ...core import db as core_db
from ...core import events, jobs
from ...core.modules import Module
from . import botflows, botreports, db, ledger, notify, reports, sitesync, woo
from .router import ledger_profile, router

DEFAULT_COLORS = ["#5B4B87", "#D27C6D", "#4D6F54", "#8D6324"]


def bootstrap() -> None:
    """Empty ERP database: one partner per owner (equal shares) with a personal card account,
    plus the shop's own accounts and default channel → account mapping."""
    with core_db.core.read() as con:
        owners = core_db.rows(con.execute("SELECT id, name FROM users WHERE is_admin = 1 AND active = 1 ORDER BY id"))
    with db.tx() as con:
        if not con.execute("SELECT COUNT(*) FROM partners").fetchone()[0] and owners:
            share = round(100 / len(owners), 4)
            for i, o in enumerate(owners):
                pid = con.execute("INSERT INTO partners (name, share, color) VALUES (?, ?, ?)",
                                  (o["name"], share, DEFAULT_COLORS[i % len(DEFAULT_COLORS)])).lastrowid
                aid = con.execute("INSERT INTO accounts (name, kind, partner_id, note, sort) VALUES (?, 'partner', ?, ?, ?)",
                                  (f"کارت {o['name']}", pid, f"کارت شخصی {o['name']} که برای خرید و هزینه‌های فروشگاه استفاده می‌شود",
                                   i + 1)).lastrowid
                con.execute("INSERT OR IGNORE INTO staff (user_id, partner_id, account_id) VALUES (?, ?, ?)", (o["id"], pid, aid))
        if not con.execute("SELECT COUNT(*) FROM accounts WHERE kind = 'shop'").fetchone()[0]:
            ids = {}
            for key, name, note, sort in (("website", "حساب درگاه سایت", "پولی که مشتری‌ها در سایت پرداخت می‌کنند", 10),
                                          ("bank", "حساب بانکی فروشگاه", "حساب مشترک / سرمایه فروشگاه", 11),
                                          ("cash", "صندوق نقدی", "پول نقد فروش حضوری", 12)):
                ids[key] = con.execute("INSERT INTO accounts (name, kind, note, sort) VALUES (?, 'shop', ?, ?)",
                                       (name, note, sort)).lastrowid
            if not db.get_setting("channel_accounts", {}, con):
                db.set_setting("channel_accounts", {"website": ids["website"], "instagram": ids["bank"],
                                                    "in_person": ids["cash"], "other": ids["bank"]}, con)


def on_user_saved(user: dict, profile: dict, created: bool) -> None:
    """Team page granted/changed someone: keep their ERP profile in step (sellers get a cash-held account)."""
    role = user["access"].get("erp")
    if not role:
        return
    with db.tx() as con:
        ledger_profile(con, user["id"], user["name"], role, profile.get("erp") or {})


def _nightly_site_sync() -> None:
    """New site products and anything a webhook missed are picked up every night."""
    if woo.configured() and not sitesync.running():
        try:
            sitesync.start(None)
        except woo.WooError:
            pass


def tag_sources() -> None:
    """Sales copied in by a one-time import after the schema change still say "manual"; name where they came from."""
    with db.tx() as con:
        con.execute("UPDATE sales SET source = 'site' WHERE source = 'manual' AND woo_order_id IS NOT NULL")
        con.execute("""UPDATE sales SET source = 'sheet' WHERE source = 'manual' AND woo_order_id IS NULL
                       AND note LIKE '%از فایل اکسل%'""")


async def startup() -> None:
    db.seed_settings()
    tag_sources()
    woo.adopt_legacy_keys()
    woo.ensure_webhook_secret()
    bootstrap()
    events.on("user.saved", on_user_saved)
    events.on("integrations.saved", lambda keys: woo.wake())
    if sitesync.state().get("running"):                 # the app restarted mid-sync
        sitesync._set_state(running=False, step="", error="همگام‌سازی با ری‌استارت برنامه نیمه‌کاره ماند؛ دوباره بزنید")
    jobs.supervise("erp.woo", woo.worker)
    jobs.daily("erp.site_sync", "04:30", _nightly_site_sync)


def summary(user: dict) -> dict:
    with db.read() as con:
        if user["role"] != "admin":
            from .router import seller_home
            from .deps import _with_profile
            return seller_home(con, _with_profile(user))
        today = db.today()
        ms, me, label = reports.period_bounds("month")
        month = reports._sales_totals(con, ms, me)
        t = con.execute("SELECT COUNT(*), IFNULL(SUM(total), 0) FROM sales WHERE status = 'done' AND date = ?",
                        (today,)).fetchone()
        inv = con.execute("""SELECT SUM(CASE WHEN stock <= 0 THEN 1 ELSE 0 END),
                                    SUM(CASE WHEN stock > 0 AND stock <= low_stock THEN 1 ELSE 0 END),
                                    IFNULL(SUM(CASE WHEN stock > 0 THEN stock * avg_cost END), 0)
                             FROM products WHERE active = 1""").fetchone()
        sync_errors = con.execute("SELECT COUNT(*) FROM products WHERE active = 1 AND woo_state = 'error'").fetchone()[0]
    return {"today": {"orders": t[0], "revenue": int(t[1])}, "month": month, "month_label": label,
            "out_count": inv[0] or 0, "low_count": inv[1] or 0, "stock_value": int(inv[2] or 0), "sync_errors": sync_errors}


def _cli_import_excel(args: list[str]) -> None:
    if not args:
        print("usage: python -m app erp import-excel FILE.xlsx")
        sys.exit(1)
    db.seed_settings()
    bootstrap()
    from . import importer
    print(json.dumps(importer.run(args[0]), ensure_ascii=False, indent=2))


module = Module(
    id="erp",
    name="فروشگاه و حسابداری",
    icon="store",
    description="انبار، فروش از همه کانال‌ها، خرید، هزینه‌ها و حساب شرکا",
    roles={"admin": "مدیر", "seller": "فروشنده"},
    router=router,
    web_dir=Path(__file__).resolve().parent / "web",
    databases=[db.database],
    startup=startup,
    notify=notify.BOT_KINDS,
    summary=summary,
    event_filter=notify.visible_to,
    cli={"import-excel": _cli_import_excel},
    bot={**botflows.FLOWS, **botreports.COMMANDS},
    exception_handlers={ledger.LedgerError: 400, woo.WooError: 502},
)
