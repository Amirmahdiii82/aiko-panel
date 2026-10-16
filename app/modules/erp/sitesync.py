"""Full sync with the website: every product and every order since the shop opened, exactly as the site has them,
merged with what only the panel / the old sheet knows (in-person and Instagram sales, purchases, expenses, costs).

Steps (each one is safe to repeat; running the sync twice changes nothing the second time):
1. Read the whole catalogue (every product and every color/variation, with exact stock) through the API.
2. Link panel products to site products when it is certain: same SKU or same name.
3. Read every order. A website sale that was typed in by hand or came from the sheet is matched to its site
   order (same days, same amount); the products on both sides then link exactly, by the real transaction —
   no similarity guessing. A sheet product sold in several colors links to the whole site product.
4. Create a panel product for every site product/color that still has none (no ticking colors one by one).
5. Record every order as a sale with the site's exact figures. A hand-typed/sheet copy is replaced by the site
   order, keeping the purchase cost the sheet knew.
6. Products created from the site get an opening stock so their stock equals the site's.
7. Sold lines without a cost get the product's cost once it is known; what is still missing is reported.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from ...core import backup, config, jobs
from . import db, ledger, notify, woo

log = logging.getLogger("aiko.erp.sitesync")

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
    return woo.sync_lock().locked()


def start(user: dict | None = None) -> None:
    """Run the full sync in the background (it can take a few minutes on a big shop)."""
    if running():
        raise woo.WooError("همگام‌سازی کامل همین الان در حال اجراست")
    if not woo.configured():
        raise woo.WooError("اول در «تنظیمات ← اتصال‌ها» کلیدهای ووکامرس را وارد کنید")
    _set_state(running=True, step="catalog", started_at=db.now(), error="", by=(user or {}).get("name") or "خودکار")
    jobs.spawn(run(user), name="erp.full_sync")


async def run(user: dict | None = None) -> dict:
    async with woo.sync_lock():
        try:
            _set_state(running=True, step="catalog")
            # a snapshot first: the sync replaces hand-typed website sales, so the previous state stays restorable
            stamp = datetime.now(db.TZ).strftime("%Y%m%d-%H%M%S")
            await asyncio.to_thread(backup.snapshot, config.BACKUP_DIR / f"presync-{stamp}", files=False)
            catalog = await woo.fetch_catalog()
            _set_state(step="orders")
            started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            async with woo.Woo() as client:
                orders = await client.paged("orders", {"status": "any", "orderby": "date", "order": "asc"},
                                            limit_pages=2000)
            orders.sort(key=lambda o: (o.get("date_created") or "", o.get("id") or 0))
            _set_state(step="apply", orders=len(orders))
            report = await asyncio.to_thread(apply, catalog, orders, user)
            woo._save_woo({"last_order_sync": started})
        except Exception as exc:
            log.exception("full site sync failed")
            msg = str(exc) if isinstance(exc, (woo.WooError, ledger.LedgerError)) else f"خطای داخلی: {exc.__class__.__name__}"
            woo.wlog("full_sync", False, msg)
            _set_state(running=False, step="", error=msg, finished_at=db.now())
            return {"error": msg}
    _set_state(running=False, step="", error="", finished_at=db.now(), report=report)
    woo.wlog("full_sync", True, summary_text(report))
    woo.wake()
    return report


def summary_text(r: dict) -> str:
    return (f"{ledger.fa(r['sales_created'])} فروش سایت ثبت شد، {ledger.fa(r['sales_replaced'])} فروش دستی/اکسل با سفارش دقیق "
            f"سایت جایگزین شد، {ledger.fa(r['products_created'])} محصول از سایت ساخته شد، "
            f"{ledger.fa(r['linked'])} محصول وصل شد")


def apply(catalog: dict, orders: list[dict], user: dict | None = None) -> dict:
    entries = catalog.get("items") or []
    report = {"orders": len(orders), "linked": 0, "products_created": 0, "sales_created": 0, "sales_replaced": 0,
              "sales_updated": 0, "sales_voided": 0, "openings": 0, "costs_filled": 0}
    with db.tx() as con:
        report["linked"] += link_certain(con, catalog)
    with db.tx() as con:
        report["linked"] += link_from_orders(con, orders, catalog)
    with db.tx() as con:
        report["products_created"] += create_missing(con, catalog)
    for order in orders:
        result = woo.process_order(order, quiet=True, catalog=catalog)
        key = {"created": "sales_created", "replaced": "sales_replaced", "updated": "sales_updated",
               "voided": "sales_voided"}.get(result)
        if key:
            report[key] += 1
    with db.tx() as con:
        report["openings"] = settle_openings(con, entries)
        report["costs_filled"] = ledger.fill_missing_costs(con)
        _settle_push_state(con)
    with db.read() as con:
        report.update(review(con))
    with db.tx() as con:
        notify.activity(con, "full_sync", "🔄 همگام‌سازی کامل با سایت انجام شد", summary_text(report),
                        user_id=(user or {}).get("id"), level="success", link="#/erp/site", notify=True)
        notify.publish_after(con, {"type": "refresh", "scope": "sales"})
        notify.publish_after(con, {"type": "refresh", "scope": "products"})
    return report


# ---------------------------------------------------------------- linking
def _linked_keys(con) -> tuple[set, set]:
    linked = {(r[0], r[1]) for r in con.execute(
        "SELECT woo_id, woo_variation_id FROM products WHERE active = 1 AND woo_id IS NOT NULL")}
    return linked, {w for w, v in linked if v is None}


def link_certain(con, catalog: dict) -> int:
    """Same SKU, or the same name once spacing/Arabic letters/punctuation are evened out."""
    entries = catalog.get("items") or []
    done = 0
    for p in db.rows(con.execute("SELECT id, sku, name FROM products WHERE active = 1 AND woo_id IS NULL")):
        linked, whole = _linked_keys(con)
        free = [e for e in entries if (e["woo_id"], e["variation_id"]) not in linked
                and not (e["variation_id"] and e["woo_id"] in whole)]
        hit = [e for e in free if p["sku"] and e.get("sku") and e["sku"].strip() == p["sku"].strip()]
        if not hit:
            name = woo.normalize(p["name"])
            hit = [e for e in free if name and woo.normalize(e["name"]) == name]
        if len(hit) == 1:
            woo.link_product(con, p["id"], hit[0]["woo_id"], hit[0]["variation_id"], catalog)
            done += 1
    return done


def _pair_lines(sheet_items: list[dict], lines: list[dict]) -> list[tuple[int, tuple]]:
    """Match the products of a hand-typed/sheet sale to the lines of its site order: same price and quantity
    first, then the closest name among what is left."""
    def price_ok(a: int, b: int) -> bool:
        return abs(a - b) <= max(1000, b * 0.02)

    pairs, left, unpaired = [], list(lines), []
    for it in sorted(sheet_items, key=lambda i: -i["unit_price"]):
        same = [l for l in left if l["qty"] == it["qty"] and price_ok(l["unit_price"], it["unit_price"])]
        pool = same or (left if len(left) == 1 and len(sheet_items) == 1 else [])
        best = max(pool, key=lambda l: woo.score(it["name"], l["name"])) if pool else None
        if not best or (len(pool) > 1 and woo.score(it["name"], best["name"]) < 0.3):
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


def link_from_orders(con, orders: list[dict], catalog: dict) -> int:
    """Link panel products by real transactions: a website sale typed in by hand / from the sheet and its
    site order contain the same goods, so their lines tell exactly which site product each panel product is."""
    evidence: dict[int, set] = defaultdict(set)
    used: set[int] = set()
    for order in orders:
        if order.get("status") not in woo.COUNTED:
            continue
        if con.execute("SELECT 1 FROM sales WHERE woo_order_id = ?", (order.get("id"),)).fetchone():
            continue
        fig = woo.order_figures(order)
        lines = [l for l in fig["lines"] if l["woo_id"] and not woo._map_line(con, l["woo_id"], l["variation_id"])]
        if not lines:
            continue
        mapped = {m["id"] for l in fig["lines"] if l["woo_id"] for m in [woo._map_line(con, l["woo_id"], l["variation_id"])] if m}
        amount = sum(l["line_total"] - l["discount"] for l in fig["lines"])
        twin = woo.find_twin(con, (order.get("date_created") or db.today())[:10], mapped, amount, exclude=used)
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
        linked, whole = _linked_keys(con)
        if (woo_id, variation) in linked or (variation and woo_id in whole):
            continue
        if variation is None and any(w == woo_id for w, v in linked):
            continue                                  # some colors already have their own products
        try:
            woo.link_product(con, pid, woo_id, variation, catalog)
            done += 1
        except ledger.LedgerError:
            continue
    return done


def create_missing(con, catalog: dict) -> int:
    """One panel product for every site product (simple products) or every color (variable products) that has none."""
    entries = catalog.get("items") or []
    has_variations = {e["woo_id"] for e in entries if e["variation_id"]}
    created = 0
    for e in entries:
        linked, whole = _linked_keys(con)
        key = (e["woo_id"], e["variation_id"])
        if key in linked:
            continue
        if e["variation_id"] is None and e["woo_id"] in has_variations:
            continue                                  # a variable product: its colors are the stock items
        if e["variation_id"] and (e["woo_id"] in whole):
            continue                                  # tracked as one product with all its colors
        if e.get("status") in ("trash",):
            continue
        woo.ensure_product(con, {"woo_id": e["woo_id"], "variation_id": e["variation_id"], "name": e["name"],
                                 "sku": e.get("sku") or "", "unit_price": e.get("price") or 0}, catalog)
        created += 1
    return created


def settle_openings(con, entries: list[dict]) -> int:
    """Products created from the site start with the site's stock (their past sales are already recorded,
    so the opening is site stock + what was sold). Without a stock number on the site, stock is set to 0."""
    by_key = {(e["woo_id"], e["variation_id"]): e for e in entries}
    n = 0
    for p in db.rows(con.execute("SELECT * FROM products WHERE active = 1 AND site_created = 1")):
        e = by_key.get((p["woo_id"], p["woo_variation_id"])) if p["woo_id"] else None
        site_stock = e.get("stock") if e and e.get("manage_stock") and isinstance(e.get("stock"), int) else None
        target = max(0, site_stock) if site_stock is not None else max(0, p["stock"])
        delta = target - p["stock"]
        if delta:
            ledger.add_move(con, p["id"], delta, "opening", note="موجودی اولیه (هماهنگ با سایت)" if site_stock is not None
                            else "موجودی اولیه (سایت عدد موجودی ندارد)", quiet=True)
            first = con.execute("""SELECT MIN(created_at) FROM stock_moves WHERE product_id = ? AND kind != 'opening'""",
                                (p["id"],)).fetchone()[0]
            if first:
                con.execute("""UPDATE stock_moves SET created_at = ? WHERE id = (SELECT MAX(id) FROM stock_moves
                               WHERE product_id = ? AND kind = 'opening')""", (first, p["id"]))
            n += 1
        con.execute("UPDATE products SET site_created = 0, woo_stock = ? WHERE id = ?",
                    (site_stock if site_stock is not None else p["woo_stock"], p["id"]))
    return n


def _settle_push_state(con) -> None:
    """Importing history marked linked products "to send"; nothing changed on the shelf, so only products whose
    stock really differs from the site stay flagged (as a mismatch to review, never pushed silently)."""
    con.execute("""UPDATE products SET woo_state = CASE WHEN woo_stock IS NOT NULL AND woo_stock = MAX(stock, 0)
                   THEN 'ok' ELSE NULL END WHERE active = 1 AND woo_id IS NOT NULL AND woo_state = 'pending'""")


# ---------------------------------------------------------------- what still needs a person
def review(con) -> dict:
    manual_web = db.rows(con.execute(
        """SELECT id, code, date, total, source FROM sales WHERE status = 'done' AND channel = 'website'
           AND woo_order_id IS NULL ORDER BY date DESC LIMIT 50"""))
    return {"unmatched_web_sales": manual_web, "duplicates": duplicates(con),
            "missing_cost": ledger.missing_costs(con)}


def duplicates(con, limit: int = 40) -> list[dict]:
    """Panel products that are not on the site next to a site product with a similar name: probably the same
    item recorded twice (e.g. once in the sheet, once on the site). Offered for merging, never merged alone."""
    loose = db.rows(con.execute(
        """SELECT p.id, p.sku, p.name, p.stock, p.image,
                  (SELECT COUNT(*) FROM sale_items i WHERE i.product_id = p.id) AS sales
           FROM products p WHERE p.active = 1 AND p.woo_id IS NULL"""))
    linked = db.rows(con.execute(
        "SELECT id, sku, name, stock, image, woo_name FROM products WHERE active = 1 AND woo_id IS NOT NULL"))
    out = []
    for p in loose:
        best, best_score = None, 0.0
        for q in linked:
            sc = max(woo.score(p["name"], q["name"]), woo.score(p["name"], q["woo_name"] or ""))
            if sc > best_score:
                best, best_score = q, sc
        if best and best_score >= 0.6:
            out.append({"product": p, "site_product": best, "strong": best_score >= 0.8})
    out.sort(key=lambda d: (not d["strong"], d["product"]["name"]))
    return out[:limit]
