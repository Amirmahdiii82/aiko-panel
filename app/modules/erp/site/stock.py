"""Stock: the panel is the one place stock is kept (one system of record); the site always shows the panel's number.

* Every stock change here reaches the site within seconds: the site is set to exactly the panel's number.
* Website orders come here as sales, so the panel's number already includes them.
* Product details live on the site: a new product or color, a name, image or price change made there comes here.
* Stock typed by hand in the WordPress admin is set back to the panel's number every few minutes, and reported.
* A full hand count (counts/stock_count_*.json) is applied once, at the first full comparison after it ships; nothing is
  sent to the site before a full comparison has run since the app started, so old numbers never go out first.
* Items the site sells without counting are left alone until their stock is set here (a stock adjustment or a hand
  count); a product linked as a whole to a site product with colors is not sent until it is split.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import db, ledger, notify
from . import client, matching, orders

log = logging.getLogger("aiko.erp.site.stock")


FULL_EVERY = 30 * 60          # compare every product this often (the safety net)


GONE = "این محصول در سایت پیدا نشد (حذف شده؟)"


_loop: asyncio.AbstractEventLoop | None = None


_wake: asyncio.Event | None = None


_touched: set[int] = set()     # site products to read again soon (a webhook, a new link)


_timers = {"check": 0.0, "full": 0.0, "pause": 0.0}


_compared = False      # a full comparison (and any hand count) has run since the app started: sending is safe


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


def _details(con, p: dict, e: dict) -> None:
    """Name, link, image, the site's in-stock flag, the price (a price change on the site updates the price here) and
    the code: a SKU set on the site becomes the product's code here too, so both show the same code."""
    sku = (e.get("sku") or "").strip()
    if sku and sku != p["sku"] and not con.execute("SELECT 1 FROM products WHERE sku = ? AND id != ?", (sku, p["id"])).fetchone():
        con.execute("UPDATE products SET sku = ? WHERE id = ?", (sku, p["id"]))
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
    linked product) with the site. New site products get a product here; products gone from the site are marked; a
    site number that differs from the panel's is queued to be set back."""
    report = {"checked": 0, "corrected": [], "created": 0, "gone": 0, "count": None}
    by_key = {(e["woo_id"], e["variation_id"]): e for e in entries}
    read = {e["woo_id"] for e in entries} | {int(x) for x in parents or ()}
    if entries:
        report["created"] = matching.create_missing(con, {"items": entries})
        matching.settle_openings(con, entries)
    if full:                                    # a hand count first: it is what the site is compared with
        report["count"] = apply_count(con, entries)
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
            site, state = None, "pending" if p["woo_counted"] else "nocount"
        elif site == max(0, p["stock"]):
            state = "ok"                            # already the same: nothing to send
        elif p["woo_state"] == "pending":
            state = "pending"                       # a change here (or the hand count) about to be sent
        else:
            state = "pending"
            report["corrected"].append(f"{p['name']} (سایت {ledger.fa(site)} ← پنل {ledger.fa(max(0, p['stock']))})")
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


# ---------------------------------------------------------------- a hand count shipped with the panel

# Not in a folder named "data": deploys keep the server's data/ folder out of the release, at any depth in old scripts
COUNT_FILES = sorted((Path(__file__).resolve().parents[1] / "counts").glob("stock_count_*.json"))


def _plans() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in COUNT_FILES]


def apply_count(con, entries: list[dict]) -> dict | None:
    """A full hand count of the shop (counts/stock_count_*.json: site product/color ids → counted number and, optionally,
    unit cost; plus items only kept here; with "tidy", products not on the site are merged or retired first —
    see matching.tidy), applied once: the panel takes the counted numbers and, being the one place stock is kept, sends
    them to the site. Only on the shop it was made for — most of its site ids must be in this catalogue — so a test or
    an empty database never gets it. A product linked as a whole to one with colors is split into its colors first."""
    result = None
    for plan in _plans():
        done = db.get_setting("stock_counts_applied", [], con) or []
        keys = {(e["woo_id"], e["variation_id"]) for e in entries}
        wanted = [(i["woo_id"], i["variation_id"]) for i in plan["items"]]
        if plan["label"] in done or not wanted or sum(k in keys for k in wanted) < 0.8 * len(wanted):
            continue
        by_key = {(e["woo_id"], e["variation_id"]): e for e in entries}
        system = {"id": None, "name": plan["label"]}
        split = changed = same = costed = 0
        tidied = matching.tidy(con, plan["label"]) if plan.get("tidy") else {"merged": [], "retired": []}
        for parent in sorted({i["woo_id"] for i in plan["items"] if i["variation_id"]}):
            whole = db.one(con.execute("""SELECT id FROM products WHERE active = 1 AND woo_id = ?
                                          AND woo_variation_id IS NULL""", (parent,)))
            colors = [i for i in plan["items"] if i["woo_id"] == parent and i["variation_id"]
                      and (parent, i["variation_id"]) in by_key]
            if whole and colors:
                ledger.split_product(con, whole["id"], [{
                    "name": by_key[(parent, i["variation_id"])]["name"], "woo_variation_id": i["variation_id"],
                    "woo_name": by_key[(parent, i["variation_id"])]["name"], "image": by_key[(parent, i["variation_id"])].get("image"),
                    "price": by_key[(parent, i["variation_id"])].get("price"), "qty": i["qty"]} for i in colors], system)
                split += 1
        missing = []
        for it in plan["items"]:
            p = db.one(con.execute("""SELECT * FROM products WHERE active = 1 AND woo_id = ?
                                      AND IFNULL(woo_variation_id, 0) = ?""", (it["woo_id"], it["variation_id"] or 0)))
            if not p:
                missing.append(it["name"])
                continue
            delta = it["qty"] - p["stock"]
            if delta:
                changed += 1
                ledger.add_move(con, p["id"], delta, "adjust", unit_cost=p["avg_cost"] if delta > 0 else None,
                                note=plan["label"], quiet=True)
            else:
                same += 1
            if it.get("cost") is not None and it["cost"] != p["avg_cost"]:
                ledger.update_product(con, p["id"], {"avg_cost": it["cost"]})      # also fills sale lines without a cost
                costed += 1
            con.execute("UPDATE products SET woo_counted = 1, woo_state = 'pending' WHERE id = ?", (p["id"],))
        for it in plan.get("panel_only") or []:
            name = matching.normalize(it["name"])
            p = next((r for r in db.rows(con.execute("SELECT * FROM products WHERE active = 1 AND woo_id IS NULL"))
                      if matching.normalize(r["name"]) == name), None)
            if p and p["stock"] != it["qty"]:
                ledger.add_move(con, p["id"], it["qty"] - p["stock"], "adjust", note=plan["label"], quiet=True)
            elif not p:
                ledger.create_product(con, {"name": it["name"].strip(), "stock": it["qty"]}, None, quiet=True)
            changed += 1
        db.set_setting("stock_counts_applied", [*done, plan["label"]], con)
        panel_only = len(plan.get("panel_only") or [])
        notify.activity(con, "stock_count", f"📋 {plan['label']} ثبت شد",
                        f"{ledger.fa(len(plan['items']))} کالای سایت"
                        + (f" و {ledger.fa(panel_only)} کالای انبار" if panel_only else "") + ": "
                        f"{ledger.fa(changed)} عدد عوض شد، {ledger.fa(same)} همان بود"
                        + (f"، قیمت خرید {ledger.fa(costed)} کالا به‌روز شد" if costed else "")
                        + (f"، {ledger.fa(split)} محصول به رنگ‌ها تفکیک شد" if split else "")
                        + (f"، {ledger.fa(len(tidied['merged']))} محصول تکراری با محصول سایت ادغام شد" if tidied["merged"] else "")
                        + (f"، {ledger.fa(len(tidied['retired']))} محصول قدیمی که در سایت نیست بایگانی شد (فروش‌هایش در گزارش‌ها می‌ماند)"
                           if tidied["retired"] else "")
                        + ". سایت هم همین اعداد را می‌گیرد."
                        + (f" پیدا نشد: {'، '.join(missing[:5])}" if missing else ""),
                        level="success" if not missing else "warning", link="#/erp/site", notify=True)
        result = {"label": plan["label"], "changed": changed, "same": same, "costed": costed, "split": split,
                  "missing": missing, **tidied}
    return result


def count_status(con) -> list[dict]:
    """The shipped hand counts and whether each has been applied; one still waiting says how much of it the last
    catalogue read recognised (it applies at the next full comparison once 80% of its site ids are there)."""
    applied = set(db.get_setting("stock_counts_applied", [], con) or [])
    plans = _plans()
    keys = set()
    if any(p["label"] not in applied for p in plans):          # the catalogue is only needed for a waiting count
        keys = {(e["woo_id"], e["variation_id"]) for e in (db.get_setting("woo_catalog", {}, con) or {}).get("items") or []}
    return [{"label": p["label"], "applied": p["label"] in applied, "products": len(p.get("items") or []),
             "units": sum(int(i.get("qty") or 0) for i in p.get("items") or []),
             "recognised": sum((i["woo_id"], i["variation_id"]) in keys for i in p.get("items") or [])} for p in plans]


async def refresh(*, full: bool = False, parents=None, changed_since: str | None = None) -> dict:
    """Read the site (all products, the given ones, or those changed since a moment) and compare. Website orders are
    read just before and just after, so a sale made meanwhile is already here when numbers are compared.
    The caller holds client.sync_lock()."""
    global _compared
    started_at = datetime.now(timezone.utc).replace(microsecond=0)
    await orders.pull_orders()
    async with client.Woo() as site:
        if full:
            entries = await client.read_site(site)
        elif parents:
            entries = await client.read_site(site, parents=sorted(parents))
        else:
            entries = await client.read_site(site, modified_after=changed_since)
    await orders.pull_orders()
    if full and not entries:
        raise client.WooError("سایت هیچ محصولی برنگرداند؛ بررسی موجودی انجام نشد")
    if entries:
        client.store_catalog(entries, full=full)

    def apply():
        with db.tx() as con:
            return reconcile(con, entries, parents=parents, full=full)
    report = await asyncio.to_thread(apply)
    if full:
        _compared = True
    client._save_woo({"stock_checked_at": started_at.isoformat()})
    if report["corrected"] or report["created"] or report["gone"]:
        client.wlog("stock_check", True, f"{ledger.fa(report['checked'])} محصول بررسی شد؛ {ledger.fa(len(report['corrected']))} "
                 f"عدد دستی سایت اصلاح شد، {ledger.fa(report['created'])} محصول تازه، {ledger.fa(report['gone'])} حذف‌شده در سایت")
    return report


async def push_pending() -> dict:
    """Set the site to the panel's number for every product waiting to be sent."""
    s = client.settings()
    if not client.configured(s) or not _compared:
        return {"pushed": 0, "errors": 0}
    with db.read() as con:
        if not con.execute("""SELECT 1 FROM products WHERE active = 1 AND woo_id IS NOT NULL
                              AND woo_state = 'pending' LIMIT 1""").fetchone():
            return {"pushed": 0, "errors": 0}
    await orders.pull_orders()                 # a website order already on the site must be counted here first
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
    async with client.Woo(s) as woo:
        for path, items in groups.items():
            for chunk in (items[i:i + 100] for i in range(0, len(items), 100)):
                payload = {"update": [{"id": p["woo_variation_id"] or p["woo_id"], "manage_stock": True,
                                       "stock_quantity": max(0, p["stock"])} for p in chunk]}
                try:
                    data, _ = await woo.request("POST", path, json=payload)
                    results = {r.get("id"): r for r in (data.get("update") or [])}
                except client.WooError as exc:
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
    client.wlog("push_stock", errors == 0, f"{ledger.fa(pushed)} موفق، {ledger.fa(errors)} ناموفق: {names}")
    if errors:
        with db.tx() as con:
            notify.activity(con, "sync_error", "⚠️ به‌روزرسانی موجودی سایت ناموفق بود",
                            f"{ledger.fa(errors)} محصول ارسال نشد. صفحه «اتصال سایت» را ببینید.", level="danger",
                            link="#/erp/site", notify=True, bot="on_sync_error")
    return {"pushed": pushed, "errors": errors}


async def _webhooks(url: str | None) -> None:
    """Instant orders and product edits; optional, the periodic check keeps everything in step anyway."""
    if url and not client.settings().get("webhooks_at"):
        try:
            await client.ensure_webhooks(url)
        except client.WooError as exc:
            client.wlog("webhooks", False, str(exc))


async def sync_now(webhook_url: str | None = None) -> dict:
    """Everything at once, on request: orders, every product, and what is waiting to be sent."""
    async with client.sync_lock():
        report = await refresh(full=True)
        now = time.monotonic()
        _timers.update(check=now, full=now)
        pushed = await push_pending()
    await _webhooks(webhook_url)
    return {"checked": report["checked"], "corrected": len(report["corrected"]), "created": report["created"],
            "gone": report["gone"], **pushed}


# ---------------------------------------------------------------- product codes (SKU) on the site

def missing_codes() -> list[dict]:
    """Linked products whose site product/color has no SKU: the panel's code can be written there."""
    items = {(e["woo_id"], e["variation_id"]): e for e in (db.get_setting("woo_catalog", {}) or {}).get("items") or []}
    with db.read() as con:
        rows = db.rows(con.execute("""SELECT id, sku, name, woo_id, woo_variation_id FROM products
                                      WHERE active = 1 AND woo_id IS NOT NULL AND sku IS NOT NULL AND sku != ''
                                      AND IFNULL(woo_state, '') != 'gone'"""))
    return [r for r in rows if (r["woo_id"], r["woo_variation_id"]) in items
            and not (items[(r["woo_id"], r["woo_variation_id"])].get("sku") or "").strip()]


async def write_codes() -> dict:
    """Give every site product/color that has no SKU the panel's code (WooCommerce keeps SKUs unique)."""
    todo = missing_codes()
    if not todo:
        return {"written": 0, "errors": []}
    groups: dict[str, list[dict]] = {}
    for p in todo:
        groups.setdefault(f"products/{p['woo_id']}/variations/batch" if p["woo_variation_id"] else "products/batch", []).append(p)
    written, errors = [], []
    async with client.Woo() as site:
        for path, items in groups.items():
            for chunk in (items[i:i + 100] for i in range(0, len(items), 100)):
                data, _ = await site.request("POST", path, json={"update": [
                    {"id": p["woo_variation_id"] or p["woo_id"], "sku": p["sku"]} for p in chunk]})
                results = {r.get("id"): r for r in (data.get("update") or [])}
                for p in chunk:
                    r = results.get(p["woo_variation_id"] or p["woo_id"]) or {}
                    if r.get("error") or not r:
                        errors.append(f"{p['name']}: {(r.get('error') or {}).get('message') or 'پاسخی نیامد'}")
                    else:
                        written.append(p)
    if written:          # the stored catalogue knows the new codes right away
        done = {(p["woo_id"], p["woo_variation_id"]): p["sku"] for p in written}
        with db.tx() as con:
            catalog = db.get_setting("woo_catalog", {}, con) or {}
            for e in catalog.get("items") or []:
                if (e["woo_id"], e["variation_id"]) in done:
                    e["sku"] = done[(e["woo_id"], e["variation_id"])]
            db.set_setting("woo_catalog", catalog, con)
    client.wlog("write_sku", not errors, f"{ledger.fa(len(written))} کد در سایت نوشته شد"
                + (f"، {ledger.fa(len(errors))} نشد: {'؛ '.join(errors[:3])}" if errors else ""))
    return {"written": len(written), "errors": errors}


async def start_codes() -> dict:
    """From now on every product on the site gets the panel's code (new products too, at each full check)."""
    client._save_woo({"write_sku": True})
    async with client.sync_lock():
        return await write_codes()


async def _tick(s: dict) -> None:
    now = time.monotonic()
    if now < _timers["pause"]:
        return
    if now - _timers["full"] >= FULL_EVERY:
        _timers.update(full=now, check=now)
        await refresh(full=True)
        if s.get("write_sku"):
            await write_codes()
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
        s = client.settings()
        if not client.configured(s) or client.sync_lock().locked():
            continue                  # a full sync is importing history; it compares stock itself when done
        try:
            async with client.sync_lock():
                await _tick(s)
        except client.WooError as exc:
            client.wlog("worker", False, str(exc))
            now = time.monotonic()           # the site is unreachable or refused: try again in two minutes
            _timers.update(pause=now + 120, full=min(_timers["full"], now - FULL_EVERY + 300))
        except Exception:   # never let the worker die
            log.exception("stock sync worker error")
            await asyncio.sleep(10)
