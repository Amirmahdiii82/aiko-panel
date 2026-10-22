"""Stock sync with the website. The panel is the one place stock is kept (one system of record, the way WooCommerce's
own POS integrations work); the site always shows the panel's number.

* Every stock change here — a sale in person or on Instagram, a purchase, a count, a return — reaches the site within
  seconds: the site is set to exactly the panel's number.
* Website orders come here as sales (instantly with webhooks, and every few minutes as a safety net), so the panel's
  number already includes them.
* Product details live on the site: a new product or color, a name, image or price change made there comes here.
* Stock typed by hand in the WordPress admin is not kept: every few minutes the site is compared with the panel and a
  different number is set back to the panel's, and reported. Stock is changed in one place only.
* Getting started, once: someone says which numbers are right today — the site's (the panel takes them) or the
  panel's (the site takes them). Nothing is sent to the site before that.
* Items the site sells without counting (stock management off) are left alone until they are counted here.
* A product linked as a whole to a site product with colors cannot be sent (which color?) until it is split.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from . import db, ledger, notify, sitesync, woo

log = logging.getLogger("aiko.erp.stock")

FULL_EVERY = 30 * 60          # compare every product this often (the safety net)
GONE = "این محصول در سایت پیدا نشد (حذف شده؟)"

_loop: asyncio.AbstractEventLoop | None = None
_wake: asyncio.Event | None = None
_touched: set[int] = set()     # site products to read again soon (a webhook, a new link)
_timers = {"check": 0.0, "full": 0.0, "pause": 0.0}


def started(s: dict | None = None) -> bool:
    return bool((s or woo.settings()).get("stock_start"))


def wake() -> None:
    if _loop and _wake:
        _loop.call_soon_threadsafe(_wake.set)


def touch(woo_ids) -> None:
    """Read these site products again within seconds."""
    _touched.update(int(i) for i in woo_ids if i)
    wake()


def after_full_sync() -> None:
    _timers["full"] = _timers["check"] = time.monotonic()
    wake()


def _counts(e: dict) -> bool:
    return bool(e.get("manage_stock")) and isinstance(e.get("stock"), int)


def _whole_with_colors(p: dict, e: dict) -> bool:
    return p["woo_variation_id"] is None and e.get("type") == "variable" and not _counts(e)


# ---------------------------------------------------------------- compare with what the site has

def _details(con, p: dict, e: dict) -> None:
    """Name, link, image, the site's in-stock flag, and the price: a price change on the site updates the price here."""
    price = e.get("price") or 0
    new_price = p["price"]
    if price and price != p["woo_price"] and (p["woo_price"] is not None or not p["price"]):
        new_price = price
    con.execute("""UPDATE products SET woo_name = ?, woo_url = ?, image = COALESCE(image, ?), woo_in_stock = ?,
                   woo_manage = ?, woo_checked_at = ?, woo_price = ?, price = ? WHERE id = ?""",
                (e["name"], e.get("url"), e.get("image"), 1 if e.get("in_stock") else 0, 1 if _counts(e) else 0,
                 db.now(), price or p["woo_price"], new_price, p["id"]))


def reconcile(con, entries: list[dict], *, parents=None, full: bool = False) -> dict:
    """Compare linked products whose site product is in `entries` (or was asked for in `parents`; with `full`, every
    linked product) with the site. New site products get a product here; products gone from the site are marked.
    Once sync has started, a site number that differs from the panel's is queued to be set back."""
    report = {"checked": 0, "corrected": [], "created": 0, "gone": 0, "differ": 0}
    live = started()
    by_key = {(e["woo_id"], e["variation_id"]): e for e in entries}
    read = {e["woo_id"] for e in entries} | {int(x) for x in parents or ()}
    if entries:
        report["created"] = sitesync.create_missing(con, {"items": entries})
        sitesync.settle_openings(con, entries)
    for p in db.rows(con.execute("SELECT * FROM products WHERE active = 1 AND woo_id IS NOT NULL ORDER BY id")):
        if not full and p["woo_id"] not in read:
            continue
        e = by_key.get((p["woo_id"], p["woo_variation_id"]))
        if e is None:
            con.execute("UPDATE products SET woo_state = 'gone', woo_error = ? WHERE id = ?", (GONE, p["id"]))
            report["gone"] += 1
            continue
        report["checked"] += 1
        _details(con, p, e)
        state, site = "ok", e.get("stock")
        if _whole_with_colors(p, e):
            colors = [x for x in entries if x["woo_id"] == p["woo_id"] and x["variation_id"]]
            site = sum(x["stock"] for x in colors) if colors and all(_counts(x) for x in colors) else None
            state = "whole"
        elif not _counts(e):
            site, state = None, "pending" if live and p["woo_counted"] else "nocount"
        elif live and p["woo_state"] == "pending":
            state = "pending"                       # about to be sent anyway
        elif site != max(0, p["stock"]):
            if live:
                state = "pending"
                report["corrected"].append(f"{p['name']} (سایت {ledger.fa(site)} ← پنل {ledger.fa(max(0, p['stock']))})")
            else:
                state = "differ"
                report["differ"] += 1
        con.execute("UPDATE products SET woo_state = ?, woo_stock = ?, woo_error = NULL WHERE id = ?", (state, site, p["id"]))
    if report["corrected"]:
        names = "، ".join(report["corrected"][:5]) + ("…" if len(report["corrected"]) > 5 else "")
        notify.activity(con, "site_stock", f"موجودی {ledger.fa(len(report['corrected']))} محصول در سایت دستی عوض شده بود",
                        f"به عدد پنل برگشت: {names}. موجودی را فقط در پنل تغییر دهید (فروش، خرید کالا یا اصلاح موجودی).",
                        level="warning", link="#/erp/site")
    if report["created"]:
        notify.activity(con, "site_products", f"🆕 {ledger.fa(report['created'])} محصول تازه از سایت به انبار اضافه شد",
                        "موجودی‌شان همان موجودی سایت است. قیمت خریدشان را وارد کنید تا سود درست حساب شود.",
                        level="warning", link="#/erp/products?f=nocost", notify=True)
    notify.publish_after(con, {"type": "refresh", "scope": "products"})
    return report


async def refresh(*, full: bool = False, parents=None, changed_since: str | None = None) -> dict:
    """Read the site (all products, the given ones, or those changed since a moment) and compare. Website orders are
    read just before and just after, so a sale made meanwhile is already here when numbers are compared.
    The caller holds woo.sync_lock()."""
    started_at = datetime.now(timezone.utc).replace(microsecond=0)
    await woo.pull_orders()
    async with woo.Woo() as client:
        if full:
            entries = await woo.read_site(client)
        elif parents:
            entries = await woo.read_site(client, parents=sorted(parents))
        else:
            entries = await woo.read_site(client, modified_after=changed_since)
    await woo.pull_orders()
    if full and not entries:
        raise woo.WooError("سایت هیچ محصولی برنگرداند؛ بررسی موجودی انجام نشد")
    if entries:
        woo.store_catalog(entries, full=full)

    def apply():
        with db.tx() as con:
            return reconcile(con, entries, parents=parents, full=full)
    report = await asyncio.to_thread(apply)
    woo._save_woo({"stock_checked_at": started_at.isoformat()})
    if report["corrected"] or report["created"] or report["gone"]:
        woo.wlog("stock_check", True, f"{ledger.fa(report['checked'])} محصول بررسی شد؛ {ledger.fa(len(report['corrected']))} "
                 f"عدد دستی سایت اصلاح شد، {ledger.fa(report['created'])} محصول تازه، {ledger.fa(report['gone'])} حذف‌شده در سایت")
    return report


async def push_pending() -> dict:
    """Set the site to the panel's number for every product waiting to be sent."""
    s = woo.settings()
    if not woo.configured(s) or not started(s):
        return {"pushed": 0, "errors": 0}
    with db.read() as con:
        if not con.execute("""SELECT 1 FROM products WHERE active = 1 AND woo_id IS NOT NULL
                              AND woo_state = 'pending' LIMIT 1""").fetchone():
            return {"pushed": 0, "errors": 0}
    await woo.pull_orders()                 # a website order already on the site must be counted here first
    with db.read() as con:
        todo = db.rows(con.execute("""SELECT * FROM products WHERE active = 1 AND woo_id IS NOT NULL
                                      AND woo_state = 'pending' ORDER BY id LIMIT 300"""))
    send = [p for p in todo if p["woo_manage"] or p["woo_counted"]]
    # never read, or not counted on the site (or a product with colors): read it again, which gives its real state
    touch(p["woo_id"] for p in todo if p not in send)
    if not send:
        return {"pushed": 0, "errors": 0}
    pushed = errors = 0
    groups: dict[str, list[dict]] = {}
    for p in send:
        groups.setdefault(f"products/{p['woo_id']}/variations/batch" if p["woo_variation_id"] else "products/batch", []).append(p)
    async with woo.Woo(s) as client:
        for path, items in groups.items():
            for chunk in (items[i:i + 100] for i in range(0, len(items), 100)):
                payload = {"update": [{"id": p["woo_variation_id"] or p["woo_id"], "manage_stock": True,
                                       "stock_quantity": max(0, p["stock"])} for p in chunk]}
                try:
                    data, _ = await client.request("POST", path, json=payload)
                    results = {r.get("id"): r for r in (data.get("update") or [])}
                except woo.WooError as exc:
                    results = {p["woo_variation_id"] or p["woo_id"]: {"error": {"message": str(exc)}} for p in chunk}
                with db.tx() as con:
                    for p in chunk:
                        r = results.get(p["woo_variation_id"] or p["woo_id"]) or {"error": {"message": "پاسخی نیامد"}}
                        if r.get("error"):
                            errors += 1
                            con.execute("UPDATE products SET woo_state = 'error', woo_error = ? WHERE id = ?",
                                        (r["error"].get("message") or "خطا", p["id"]))
                            notify.publish_after(con, {"type": "product", "id": p["id"], "woo_state": "error"})
                            continue
                        pushed += 1
                        site = r.get("stock_quantity") if isinstance(r.get("stock_quantity"), int) else max(0, p["stock"])
                        # sold again while sending: stays pending for the next round
                        con.execute("""UPDATE products SET woo_stock = ?, woo_manage = 1, woo_counted = 0, woo_in_stock = ?,
                                       woo_synced_at = ?, woo_error = NULL,
                                       woo_state = CASE WHEN MAX(stock, 0) != ? THEN 'pending' ELSE 'ok' END WHERE id = ?""",
                                    (site, 1 if site > 0 else 0, db.now(), site, p["id"]))
                        notify.publish_after(con, {"type": "product", "id": p["id"], "woo_state": "ok", "woo_stock": site})
    names = "، ".join(p["name"] for p in send[:4]) + ("…" if len(send) > 4 else "")
    woo.wlog("push_stock", errors == 0, f"{ledger.fa(pushed)} موفق، {ledger.fa(errors)} ناموفق: {names}")
    if errors:
        with db.tx() as con:
            notify.activity(con, "sync_error", "⚠️ به‌روزرسانی موجودی سایت ناموفق بود",
                            f"{ledger.fa(errors)} محصول ارسال نشد. صفحه «اتصال سایت» را ببینید.", level="danger",
                            link="#/erp/site", notify=True, bot="on_sync_error")
    return {"pushed": pushed, "errors": errors}


# ---------------------------------------------------------------- what a person does

async def _webhooks(url: str | None) -> None:
    """Instant orders and product edits; optional, the periodic check keeps everything in step anyway."""
    if url and started() and not woo.settings().get("webhooks_at"):
        try:
            await woo.ensure_webhooks(url)
        except woo.WooError as exc:
            woo.wlog("webhooks", False, str(exc))


async def start(side: str, user: dict, webhook_url: str | None = None) -> dict:
    """The one-time start: "site" — today's site numbers are right, the panel takes them; "panel" — the panel's numbers
    are right, the site takes them. Products the site does not count are left as they are."""
    if side not in ("site", "panel"):
        raise ledger.LedgerError("کدام عدد درست است؟")
    async with woo.sync_lock():
        await refresh(full=True)
        changed = 0
        with db.tx() as con:
            for p in db.rows(con.execute("""SELECT * FROM products WHERE active = 1 AND woo_id IS NOT NULL
                                            AND woo_state IN ('ok', 'differ')""")):
                if p["woo_stock"] == max(0, p["stock"]):
                    continue
                changed += 1
                if side == "site":
                    ledger.add_move(con, p["id"], p["woo_stock"] - p["stock"], "site_sync", ref_type="site", quiet=True,
                                    note="شروع همگام‌سازی: عدد سایت", user_id=user["id"])
                    con.execute("UPDATE products SET woo_state = 'ok' WHERE id = ?", (p["id"],))
                else:
                    con.execute("UPDATE products SET woo_state = 'pending' WHERE id = ?", (p["id"],))
            s = db.get_setting("woo", {}, con) or {}
            s.update(stock_start=side, stock_started_at=db.now(), stock_started_by=user["name"])
            db.set_setting("woo", s, con)
            notify.activity(con, "site_stock", "همگام‌سازی موجودی با سایت شروع شد",
                            f"{'عدد سایت' if side == 'site' else 'عدد پنل'} درست بود؛ {ledger.fa(changed)} محصول هماهنگ شد. "
                            f"از این به بعد موجودی را فقط در پنل تغییر دهید. — {user['name']}",
                            user_id=user["id"], level="success", link="#/erp/site")
            notify.publish_after(con, {"type": "refresh", "scope": "products"})
        pushed = await push_pending()
    await _webhooks(webhook_url)
    return {"changed": changed, **pushed}


def count(product_id: int, qty: int, user: dict) -> None:
    """An item the site sells without counting was counted here: the panel and the site both get this number."""
    with db.tx() as con:
        p = ledger.get_product(con, product_id)
        if not p["woo_id"]:
            raise ledger.LedgerError("این محصول به سایت وصل نیست")
        if p["woo_state"] == "whole":
            raise ledger.LedgerError("این محصول در سایت رنگ‌بندی دارد؛ اول آن را به رنگ‌ها تفکیک کنید")
        ledger.adjust_stock(con, product_id, set_to=qty, reason="شمارش برای سایت", user=user)
        con.execute("UPDATE products SET woo_counted = 1, woo_state = 'pending' WHERE id = ?", (product_id,))
    wake()


async def sync_now(webhook_url: str | None = None) -> dict:
    """Everything at once, on request: orders, every product, and what is waiting to be sent."""
    async with woo.sync_lock():
        report = await refresh(full=True)
        now = time.monotonic()
        _timers.update(check=now, full=now)
        pushed = await push_pending()
    await _webhooks(webhook_url)
    return {"checked": report["checked"], "corrected": len(report["corrected"]), "created": report["created"],
            "gone": report["gone"], **pushed}


# ---------------------------------------------------------------- background worker

async def _tick(s: dict) -> None:
    now = time.monotonic()
    if now < _timers["pause"]:
        return
    if now - _timers["full"] >= FULL_EVERY:
        _timers.update(full=now, check=now)
        await refresh(full=True)
    elif now - _timers["check"] >= max(1, int(s.get("pull_minutes") or 3)) * 60:
        _timers["check"] = now
        since = s.get("stock_checked_at")
        if since:
            since = (datetime.fromisoformat(since) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S")
        await refresh(changed_since=since, full=not since)
    if _touched:
        parents = set(_touched)
        _touched.clear()
        await refresh(parents=parents)
    await push_pending()


async def worker() -> None:
    global _loop, _wake
    _loop = asyncio.get_running_loop()
    _wake = asyncio.Event()
    ledger.sync_wake = wake
    while True:
        try:
            await asyncio.wait_for(_wake.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
        _wake.clear()
        await asyncio.sleep(1.2)   # gather a burst of changes into one request
        s = woo.settings()
        if not woo.configured(s) or woo.sync_lock().locked():
            continue                  # a full sync is importing history; it compares stock itself when done
        try:
            async with woo.sync_lock():
                await _tick(s)
        except woo.WooError as exc:
            woo.wlog("worker", False, str(exc))
            now = time.monotonic()           # the site is unreachable or refused: try again in two minutes
            _timers.update(pause=now + 120, full=min(_timers["full"], now - FULL_EVERY + 300))
        except Exception:   # never let the worker die
            log.exception("stock sync worker error")
            await asyncio.sleep(10)
