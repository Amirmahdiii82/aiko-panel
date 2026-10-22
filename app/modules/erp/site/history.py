"""Importing the site's history: every order since the shop opened, merged with what only the panel / the old sheet
knows (in-person and Instagram sales, purchases, expenses, costs). Run once by hand; every night only the last two
weeks of orders are read again, to catch anything both the webhook and the polling missed.

Steps (each safe to repeat; running twice changes nothing the second time):
1. Read the whole catalogue. 2. Link panel products to site products when it is certain (SKU, same name).
3. A website sale typed by hand or from the sheet is matched to its site order (same days, same amount); the products
   on both sides then link exactly. 4. Create a panel product for every site product/color that has none.
5. Record every order with the site's exact figures, replacing hand-typed copies (keeping the sheet's purchase cost).
6. Products created from the site start with the site's stock. 7. Sold lines get their cost once it is known.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ....core import backup, config, jobs
from .. import db, ledger, notify
from . import client, matching, orders, stock

log = logging.getLogger("aiko.erp.site.history")


STATE_KEY = "woo_full_sync"


def state() -> dict:
    return db.get_setting(STATE_KEY, {}) or {}


def _set_state(**changes) -> None:
    with db.tx() as con:
        s = db.get_setting(STATE_KEY, {}, con) or {}
        s.update(changes)
        db.set_setting(STATE_KEY, s, con)
        notify.publish_after(con, {"type": "site_sync", "state": s})


def running() -> bool:
    return client.sync_lock().locked()


def start(user: dict | None = None, *, recent_days: int | None = None) -> None:
    """Run in the background (the whole history can take a few minutes). `recent_days`: only orders changed in the
    last days (the nightly check), no snapshot needed."""
    if running():
        raise client.WooError("همگام‌سازی همین الان در حال اجراست")
    if not client.configured():
        raise client.WooError("اول در «تنظیمات ← اتصال‌ها» کلیدهای ووکامرس را وارد کنید")
    if not recent_days:
        _set_state(running=True, step="catalog", started_at=db.now(), error="", by=(user or {}).get("name") or "خودکار")
    jobs.spawn(run(user, recent_days=recent_days), name="erp.site_history")


async def run(user: dict | None = None, *, recent_days: int | None = None) -> dict:
    full = not recent_days
    async with client.sync_lock():
        try:
            if full:
                _set_state(running=True, step="catalog")
                # a snapshot first: this replaces hand-typed website sales, so the previous state stays restorable
                stamp = datetime.now(db.TZ).strftime("%Y%m%d-%H%M%S")
                await asyncio.to_thread(backup.snapshot, config.BACKUP_DIR / f"presync-{stamp}", files=False)
            catalog = await client.fetch_catalog()
            if full:
                _set_state(step="orders")
            started = datetime.now(timezone.utc).replace(microsecond=0)
            params = {"status": "any", "orderby": "date", "order": "asc"}
            if not full:
                params.update(modified_after=(started - timedelta(days=recent_days)).strftime("%Y-%m-%dT%H:%M:%S"),
                              dates_are_gmt="true")
            async with client.Woo() as woo:
                site_orders = await woo.paged("orders", params, limit_pages=2000)
            site_orders.sort(key=lambda o: (o.get("date_created") or "", o.get("id") or 0))
            if full:
                _set_state(step="apply", orders=len(site_orders))
            report = await asyncio.to_thread(apply, catalog, site_orders, user, full)
            if full:
                client._save_woo({"last_order_sync": started.isoformat()})
        except Exception as exc:
            log.exception("site history sync failed")
            msg = str(exc) if isinstance(exc, (client.WooError, ledger.LedgerError)) else f"خطای داخلی: {exc.__class__.__name__}"
            client.wlog("full_sync" if full else "nightly_check", False, msg)
            if full:
                _set_state(running=False, step="", error=msg, finished_at=db.now())
            return {"error": msg}
    if full:
        _set_state(running=False, step="", error="", finished_at=db.now(), report=report)
    client.wlog("full_sync" if full else "nightly_check", True, summary_text(report))
    stock.after_full_sync()
    return report


def summary_text(r: dict) -> str:
    return (f"{ledger.fa(r['orders'])} سفارش بررسی شد: {ledger.fa(r['sales_created'])} فروش سایت ثبت شد، "
            f"{ledger.fa(r['sales_replaced'])} فروش دستی/اکسل با سفارش دقیق سایت جایگزین شد، "
            f"{ledger.fa(r['products_created'])} محصول از سایت ساخته شد، {ledger.fa(r['linked'])} محصول وصل شد")


def apply(catalog: dict, site_orders: list[dict], user: dict | None = None, full: bool = True) -> dict:
    entries = catalog.get("items") or []
    report = {"orders": len(site_orders), "linked": 0, "products_created": 0, "sales_created": 0, "sales_replaced": 0,
              "sales_updated": 0, "sales_voided": 0, "openings": 0, "costs_filled": 0}
    with db.tx() as con:
        report["linked"] += matching.link_certain(con, catalog)
    with db.tx() as con:
        report["linked"] += link_from_orders(con, site_orders, catalog)
    with db.tx() as con:
        report["products_created"] += matching.create_missing(con, catalog)
    for order in site_orders:
        result = orders.process_order(order, quiet=True, catalog=catalog)
        key = {"created": "sales_created", "replaced": "sales_replaced", "updated": "sales_updated",
               "voided": "sales_voided"}.get(result)
        if key:
            report[key] += 1
    with db.tx() as con:
        report["openings"] = matching.settle_openings(con, entries)
        report["costs_filled"] = ledger.fill_missing_costs(con)
    with db.tx() as con:
        compared = stock.reconcile(con, entries, full=True)
    report["stock_corrected"] = len(compared["corrected"])
    with db.read() as con:
        report.update(review(con))
    if full or report["sales_created"] or report["sales_replaced"]:
        with db.tx() as con:
            title = "🔄 تاریخچه سفارش‌های سایت وارد شد" if full else "🔄 بررسی شبانه سفارش‌های سایت"
            notify.activity(con, "full_sync", title, summary_text(report), user_id=(user or {}).get("id"),
                            level="success", link="#/erp/site", notify=full)
            notify.publish_after(con, {"type": "refresh", "scope": "sales"})
            notify.publish_after(con, {"type": "refresh", "scope": "products"})
    return report


def _pair_lines(sheet_items: list[dict], lines: list[dict]) -> list[tuple[int, tuple]]:
    """Match the products of a hand-typed/sheet sale to the lines of its site order: same price and quantity
    first, then the closest name among what is left."""
    def price_ok(a: int, b: int) -> bool:
        return abs(a - b) <= max(1000, b * 0.02)

    pairs, left, unpaired = [], list(lines), []
    for it in sorted(sheet_items, key=lambda i: -i["unit_price"]):
        same = [l for l in left if l["qty"] == it["qty"] and price_ok(l["unit_price"], it["unit_price"])]
        pool = same or (left if len(left) == 1 and len(sheet_items) == 1 else [])
        best = max(pool, key=lambda l: matching.score(it["name"], l["name"])) if pool else None
        if not best or (len(pool) > 1 and matching.score(it["name"], best["name"]) < 0.3):
            unpaired.append(it)
            continue
        pairs.append((it["product_id"], (best["woo_id"], best["variation_id"])))
        left.remove(best)
    # "2× lipstick" in the sheet, one red + one pink on the site: compare with each site product as a whole
    groups: dict[int, list[dict]] = defaultdict(list)
    for l in left:
        groups[l["woo_id"]].append(l)
    for it in unpaired:
        for woo_id, ls in list(groups.items()):
            if sum(l["qty"] for l in ls) == it["qty"] and all(price_ok(l["unit_price"], it["unit_price"]) for l in ls):
                pairs.extend((it["product_id"], (l["woo_id"], l["variation_id"])) for l in ls)
                del groups[woo_id]
                break
    return pairs


def link_from_orders(con, site_orders: list[dict], catalog: dict) -> int:
    """Link panel products by real transactions: a website sale typed in by hand / from the sheet and its
    site order contain the same goods, so their lines tell exactly which site product each panel product is."""
    evidence: dict[int, set] = defaultdict(set)
    used: set[int] = set()
    for order in site_orders:
        if order.get("status") not in orders.COUNTED:
            continue
        if con.execute("SELECT 1 FROM sales WHERE woo_order_id = ?", (order.get("id"),)).fetchone():
            continue
        fig = orders.order_figures(order)
        lines = [l for l in fig["lines"] if l["woo_id"] and not orders._map_line(con, l["woo_id"], l["variation_id"])]
        if not lines:
            continue
        mapped = {m["id"] for l in fig["lines"] if l["woo_id"] for m in [orders._map_line(con, l["woo_id"], l["variation_id"])] if m}
        amount = sum(l["line_total"] - l["discount"] for l in fig["lines"])
        twin = matching.find_twin(con, (order.get("date_created") or db.today())[:10], mapped, amount, exclude=used)
        if not twin:
            continue
        used.add(twin["id"])
        items = db.rows(con.execute(
            """SELECT i.product_id, i.qty, i.unit_price, IFNULL(p.name, i.name) AS name FROM sale_items i
               JOIN products p ON p.id = i.product_id WHERE i.sale_id = ? AND p.woo_id IS NULL AND p.active = 1""",
            (twin["id"],)))
        for pid, key in _pair_lines(items, lines):
            evidence[pid].add(key)
    done = 0
    for pid, keys in evidence.items():
        parents = {w for w, _ in keys}
        if len(parents) != 1:
            continue                                  # contradicting evidence: leave it for a person
        woo_id = parents.pop()
        variation = next(iter(keys))[1] if len(keys) == 1 else None   # sold in several colors → the whole product
        linked, whole = matching._linked_keys(con)
        if (woo_id, variation) in linked or (variation and woo_id in whole):
            continue
        if variation is None and any(w == woo_id for w, v in linked):
            continue                                  # some colors already have their own products
        try:
            matching.link_product(con, pid, woo_id, variation, catalog)
            done += 1
        except ledger.LedgerError:
            continue
    return done


def review(con) -> dict:
    manual_web = db.rows(con.execute(
        """SELECT id, code, date, total, source FROM sales WHERE status = 'done' AND channel = 'website'
           AND woo_order_id IS NULL ORDER BY date DESC LIMIT 50"""))
    return {"unmatched_web_sales": manual_web, "duplicates": matching.duplicates(con),
            "missing_cost": ledger.missing_costs(con)}
