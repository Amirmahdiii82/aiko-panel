"""Two-way stock sync with the website: changes made here and changes made on the site are both kept.

Stock changes in two places:
* here — in-person / Instagram sales, purchases, counts, returns;
* on the site — website orders (which also arrive here as sales), and edits in the WordPress admin.

Each linked product remembers the last point where both sides agreed: `woo_base_move` (the last stock move already
reflected on the site). From that point:
* L = what changed here that the site cannot know about: every stock move after the agreement except website sales
  and their returns (the site counted those itself) and moves that came from the site;
* S = the site's stock right now.
The true stock is S + L.
* When L ≠ 0, the site is set to S + L, with S read just before writing, so an edit made on the site is never
  overwritten.
* When the stock here is not S + L, the difference was made on the site (an edit in WordPress, a restock on a refund,
  a new product) and it is taken over here as a "site_sync" stock move — but only once it has been seen on two
  reads in a row: a website order that lands between reading the site and importing the order looks the same for a
  moment, and disappears on the next read.

A difference that was already there before both sides agreed (products linked before two-way sync, or a new link)
is never settled by guessing: the panel's in-person sales were never sent to the site, and edits on the site never
came here, so either number can be the right one. It is shown once ("conflict") and a person picks a side; changes
made after that keep flowing both ways.

Items the site does not count (stock management off: only "in stock / out of stock") cannot be compared. They are
shown as such; a count made here (a stock adjustment) turns counting on for them on the site.
A product linked as a whole to a site product with colors cannot be pushed (which color?); it is shown read-only
until it is split into colors.

The worker: website orders every few minutes, the products changed on the site every few minutes, every product
every half hour, and pushes within seconds of a change here. Webhooks (product.* and order.*) make both instant.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from . import db, ledger, notify, sitesync, woo

log = logging.getLogger("aiko.erp.stock")

FULL_EVERY = 30 * 60          # read every product this often (the safety net)
CONFIRM_AFTER = 40            # re-read a product whose stock changed on the site this long after seeing it
GONE = "این محصول در سایت پیدا نشد (حذف شده؟)"

# a stock move the site already knows about: website sales (also hand-typed ones) and their returns, moves from the site
SITE_ORIGIN = """(m.ref_type = 'site' OR (m.ref_type = 'sale' AND m.ref_id IN
                  (SELECT id FROM sales WHERE channel = 'website' OR woo_order_id IS NOT NULL)))"""

_loop: asyncio.AbstractEventLoop | None = None
_wake: asyncio.Event | None = None
_touched: set[int] = set()     # site products to re-read soon (a webhook, a change to confirm, a new link)
_touch_at = 0.0
_timers = {"pull": 0.0, "check": 0.0, "full": 0.0, "pause": 0.0}


def enabled(s: dict | None = None) -> bool:
    return bool((s or woo.settings()).get("stock_sync", True))


def wake() -> None:
    if _loop and _wake:
        _loop.call_soon_threadsafe(_wake.set)


def touch(woo_ids, delay: float = 0) -> None:
    """Re-read these site products soon (after `delay` seconds)."""
    global _touch_at
    ids = {int(i) for i in woo_ids if i}
    if not ids:
        return
    due = time.monotonic() + delay
    _touch_at = min(_touch_at, due) if _touched else due
    _touched.update(ids)
    wake()


def after_full_sync(drift_parents) -> None:
    _timers["full"] = _timers["check"] = time.monotonic()
    touch(drift_parents, CONFIRM_AFTER)
    wake()


# ---------------------------------------------------------------- the agreement point

def local_delta(con, product_id: int, base: int) -> tuple[int, int]:
    """(L, last move id): what changed here after move `base` that the site does not know about."""
    row = con.execute(f"""SELECT IFNULL(SUM(CASE WHEN {SITE_ORIGIN} THEN 0 ELSE m.qty END), 0), IFNULL(MAX(m.id), ?)
                          FROM stock_moves m WHERE m.product_id = ? AND m.id > ?""", (base, product_id, base)).fetchone()
    return int(row[0]), int(row[1])


def _last_move(con, product_id: int) -> int:
    return con.execute("SELECT IFNULL(MAX(id), 0) FROM stock_moves WHERE product_id = ?", (product_id,)).fetchone()[0]


def _initial_base(con, p: dict, catalog_at: str | None) -> int:
    """Products linked before two-way sync existed: the site's stock was last seen (or set) at some moment; changes
    made here after that moment are still to be sent, anything older is settled in favour of the site."""
    seen = max(filter(None, (p.get("woo_synced_at"), catalog_at)), default=None)
    if seen:
        first = con.execute(f"""SELECT MIN(m.id) FROM stock_moves m WHERE m.product_id = ? AND m.created_at > ?
                                AND NOT {SITE_ORIGIN}""", (p["id"], seen)).fetchone()[0]
        if first:
            return first - 1
    return _last_move(con, p["id"])


def init_bases() -> int:
    """Once, at startup and before the site is read again: give products linked before two-way sync existed their
    agreement point, while the time the site was last read is still known."""
    with db.tx() as con:
        catalog_at = (db.get_setting("woo_catalog", {}, con) or {}).get("fetched_at")
        rows = db.rows(con.execute("""SELECT * FROM products WHERE active = 1 AND woo_id IS NOT NULL
                                      AND woo_base_move IS NULL"""))
        for p in rows:
            con.execute("UPDATE products SET woo_base_move = ?, woo_review = 1 WHERE id = ?",
                        (_initial_base(con, p, catalog_at), p["id"]))
    return len(rows)


def _base(con, p: dict, catalog_at: str | None = None) -> int:
    if p["woo_base_move"] is not None:
        return p["woo_base_move"]
    if catalog_at is None:
        catalog_at = (db.get_setting("woo_catalog", {}, con) or {}).get("fetched_at")
    return _initial_base(con, p, catalog_at)


def _counted_here(con, product_id: int, base: int) -> bool:
    """A person counted this item here (stock adjustment) after the agreement: a real number for the site."""
    return con.execute("SELECT 1 FROM stock_moves WHERE product_id = ? AND id > ? AND kind = 'adjust' LIMIT 1",
                       (product_id, base)).fetchone() is not None


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


def _agree(con, p: dict, site: int, local: int, base: int, last: int, report: dict, *, confirm: bool) -> None:
    """The site has `site`; `local` changed here after move `base` (up to `last`)."""
    drift = site + local - p["stock"]
    review = p.get("woo_review") or 0
    if drift and review == 1:
        # an old difference: a person decides; changes made here meanwhile still go to the site
        report["conflicts"] += 1
        con.execute("""UPDATE products SET woo_state = ?, woo_stock = ?, woo_drift = ?, woo_base_move = ?, woo_error = NULL
                       WHERE id = ?""", ("pending" if local else "conflict", site, drift, base if local else last, p["id"]))
        if local:
            report["pending"] += 1
        return
    if review:
        con.execute("UPDATE products SET woo_review = 0 WHERE id = ?", (p["id"],))
    if drift and (confirm or review == 2 or p["woo_drift"] == drift):
        ledger.add_move(con, p["id"], drift, "site_sync", ref_type="site", quiet=True,
                        note=f"تغییر موجودی در سایت (سایت: {ledger.fa(site)})")
        report["adopted"].append(f"{p['name']} ({'+' if drift > 0 else '−'}{ledger.fa(abs(drift))})")
        drift = 0
    elif drift:
        report["drift"].add(p["woo_id"])
    if local:
        report["pending"] += 1
        con.execute("""UPDATE products SET woo_state = 'pending', woo_stock = ?, woo_drift = ?, woo_base_move = ?,
                       woo_error = NULL WHERE id = ?""", (site, drift or None, base, p["id"]))
    else:
        con.execute("""UPDATE products SET woo_state = ?, woo_stock = ?, woo_drift = ?, woo_base_move = ?,
                       woo_error = NULL WHERE id = ?""",
                    ("drift" if drift else "ok", site, drift or None, _last_move(con, p["id"]), p["id"]))
    notify.publish_after(con, {"type": "product", "id": p["id"], "woo_state": "pending" if local else "ok"})


def reconcile(con, entries: list[dict], *, parents=None, full: bool = False, confirm: bool = False) -> dict:
    """Compare every linked product whose site product is in `entries` (or was asked for in `parents`) with the site.
    New site products get a product here; products gone from the site are marked. With `full`, `entries` is the
    whole catalogue. Returns what happened: adopted (site changes taken over), drift (site products to re-read)."""
    report = {"checked": 0, "adopted": [], "drift": set(), "pending": 0, "gone": 0, "created": 0, "uncounted": 0,
              "conflicts": 0}
    by_key = {(e["woo_id"], e["variation_id"]): e for e in entries}
    read = {e["woo_id"] for e in entries} | {int(x) for x in parents or ()}
    if entries:
        report["created"] = sitesync.create_missing(con, {"items": entries})
        sitesync.settle_openings(con, entries)
    catalog_at = (db.get_setting("woo_catalog", {}, con) or {}).get("fetched_at")
    for p in db.rows(con.execute("SELECT * FROM products WHERE active = 1 AND woo_id IS NOT NULL ORDER BY id")):
        if not full and p["woo_id"] not in read:
            continue
        e = by_key.get((p["woo_id"], p["woo_variation_id"]))
        if e is None:
            if p["woo_state"] != "gone":
                con.execute("UPDATE products SET woo_state = 'gone', woo_error = ?, woo_drift = NULL WHERE id = ?",
                            (GONE, p["id"]))
            report["gone"] += 1
            continue
        report["checked"] += 1
        base = _base(con, p, catalog_at)
        _details(con, p, e)
        local, last = local_delta(con, p["id"], base)
        if _whole_with_colors(p, e):
            colors = [x for x in entries if x["woo_id"] == p["woo_id"] and x["variation_id"]]
            site = sum(x["stock"] for x in colors) if colors and all(_counts(x) for x in colors) else None
            con.execute("""UPDATE products SET woo_state = 'whole', woo_stock = ?, woo_base_move = ?, woo_drift = NULL,
                           woo_error = NULL WHERE id = ?""", (site, last, p["id"]))
            continue
        if not _counts(e):
            report["uncounted"] += 1
            if local and _counted_here(con, p["id"], base):
                con.execute("UPDATE products SET woo_state = 'pending', woo_stock = NULL, woo_base_move = ? WHERE id = ?",
                            (base, p["id"]))
                report["pending"] += 1
            else:
                con.execute("""UPDATE products SET woo_state = 'nocount', woo_stock = NULL, woo_base_move = ?,
                               woo_drift = NULL, woo_error = NULL WHERE id = ?""", (last, p["id"]))
            continue
        _agree(con, p, e["stock"], local, base, last, report, confirm=confirm)
    if report["adopted"]:
        names = "، ".join(report["adopted"][:6]) + ("…" if len(report["adopted"]) > 6 else "")
        notify.activity(con, "site_stock", f"🔄 موجودی {ledger.fa(len(report['adopted']))} محصول از سایت به‌روز شد",
                        f"این تغییرها در خود سایت انجام شده بود: {names}", link="#/erp/site")
    if report["created"]:
        notify.activity(con, "site_products", f"🆕 {ledger.fa(report['created'])} محصول تازه از سایت به انبار اضافه شد",
                        "موجودی‌شان همان موجودی سایت است. قیمت خریدشان را وارد کنید تا سود درست حساب شود.",
                        level="warning", link="#/erp/products?f=nocost", notify=True)
    if report["adopted"] or report["created"] or report["gone"]:
        notify.publish_after(con, {"type": "refresh", "scope": "products"})
    return report


# ---------------------------------------------------------------- reading the site, then comparing

async def refresh(*, full: bool = False, parents=None, changed_since: str | None = None) -> dict:
    """Read the site (all products, the given ones, or the ones changed since a moment) and compare. Website orders
    are read just before and just after, so a sale made meanwhile is already here when stock is compared.
    The caller holds woo.sync_lock()."""
    s = woo.settings()
    started = datetime.now(timezone.utc).replace(microsecond=0)
    await woo.pull_orders()
    async with woo.Woo(s) as client:
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
    woo._save_woo({"stock_checked_at": started.isoformat(), **({"stock_full_at": db.now()} if full else {})})
    touch(report["drift"], CONFIRM_AFTER)
    if report["adopted"] or report["created"] or report["gone"] or full:
        woo.wlog("stock_check", True, f"{'همه محصولات' if full else ledger.fa(report['checked']) + ' محصول'} بررسی شد؛ "
                 f"{ledger.fa(len(report['adopted']))} تغییر از سایت، {ledger.fa(report['created'])} محصول تازه، "
                 f"{ledger.fa(report['gone'])} حذف‌شده در سایت")
    return report


async def push_pending() -> dict:
    """Send changes made here: each pending product's site stock is read, then set to (site stock + change here).
    A product someone said "the number here is right" for (state 'force') is set to exactly that number."""
    s = woo.settings()
    if not woo.configured(s):
        return {"pushed": 0, "errors": 0}
    with db.read() as con:
        todo = db.rows(con.execute("""SELECT id, woo_id FROM products WHERE active = 1 AND woo_id IS NOT NULL
                                      AND woo_state IN ('pending', 'force') ORDER BY id LIMIT 300"""))
    if not todo:
        return {"pushed": 0, "errors": 0}
    await woo.pull_orders()                 # a website order already on the site must be here before comparing
    async with woo.Woo(s) as client:
        fresh = {(e["woo_id"], e["variation_id"]): e
                 for e in await woo.read_site(client, parents=sorted({p["woo_id"] for p in todo}))}
        writes, report = [], {"adopted": [], "drift": set(), "pending": 0, "conflicts": 0}
        with db.tx() as con:
            catalog_at = (db.get_setting("woo_catalog", {}, con) or {}).get("fetched_at")
            for row in todo:
                p = db.one(con.execute("SELECT * FROM products WHERE id = ?", (row["id"],)))
                if not p or p["woo_state"] not in ("pending", "force") or not p["woo_id"]:
                    continue
                e = fresh.get((p["woo_id"], p["woo_variation_id"]))
                if e is None:
                    con.execute("UPDATE products SET woo_state = 'gone', woo_error = ? WHERE id = ?", (GONE, p["id"]))
                    continue
                base = _base(con, p, catalog_at)
                _details(con, p, e)
                local, last = local_delta(con, p["id"], base)
                if _whole_with_colors(p, e):
                    con.execute("UPDATE products SET woo_state = 'whole', woo_base_move = ? WHERE id = ?", (last, p["id"]))
                    continue
                if p["woo_state"] == "force" or (not _counts(e) and _counted_here(con, p["id"], base)):
                    target = max(0, p["stock"])
                elif _counts(e):
                    target = max(0, e["stock"] + local)
                else:
                    con.execute("""UPDATE products SET woo_state = 'nocount', woo_stock = NULL, woo_base_move = ?
                                   WHERE id = ?""", (last, p["id"]))
                    continue
                if _counts(e) and target == e["stock"]:
                    # nothing to send; whatever still differs was changed on the site
                    _agree(con, p, e["stock"], 0, last, last, report, confirm=False)
                    continue
                writes.append({"p": p, "target": target, "last": last})
        touch(report["drift"], CONFIRM_AFTER)
        pushed = errors = 0
        groups: dict[str, list[dict]] = {}
        for w in writes:
            p = w["p"]
            groups.setdefault(f"products/{p['woo_id']}/variations/batch" if p["woo_variation_id"] else "products/batch",
                              []).append(w)
        for path, items in groups.items():
            for chunk in (items[i:i + 100] for i in range(0, len(items), 100)):
                payload = {"update": [{"id": w["p"]["woo_variation_id"] or w["p"]["woo_id"], "manage_stock": True,
                                       "stock_quantity": w["target"]} for w in chunk]}
                try:
                    data, _ = await client.request("POST", path, json=payload)
                    results = {r.get("id"): r for r in (data.get("update") or [])}
                except woo.WooError as exc:
                    results = {w["p"]["woo_variation_id"] or w["p"]["woo_id"]: {"error": {"message": str(exc)}} for w in chunk}
                with db.tx() as con:
                    for w in chunk:
                        p = w["p"]
                        r = results.get(p["woo_variation_id"] or p["woo_id"]) or {"error": {"message": "پاسخی نیامد"}}
                        if r.get("error"):
                            errors += 1
                            con.execute("UPDATE products SET woo_state = 'error', woo_error = ? WHERE id = ?",
                                        (r["error"].get("message") or "خطا", p["id"]))
                            notify.publish_after(con, {"type": "product", "id": p["id"], "woo_state": "error"})
                            continue
                        pushed += 1
                        site = r.get("stock_quantity")
                        site = site if isinstance(site, int) else w["target"]
                        # a change made here while sending stays pending for the next round
                        con.execute("""UPDATE products SET woo_base_move = ?, woo_stock = ?, woo_manage = 1, woo_in_stock = ?,
                                       woo_synced_at = ?, woo_error = NULL,
                                       woo_state = CASE WHEN (SELECT IFNULL(MAX(id), 0) FROM stock_moves WHERE product_id = ?) > ?
                                                   THEN 'pending' WHEN woo_review = 1 AND stock != ? THEN 'conflict' ELSE 'ok' END,
                                       woo_drift = CASE WHEN woo_review = 1 AND stock != ? THEN ? - stock END WHERE id = ?""",
                                    (w["last"], site, 1 if site > 0 else 0, db.now(), p["id"], w["last"], site, site, site, p["id"]))
                        notify.publish_after(con, {"type": "product", "id": p["id"], "woo_state": "ok", "woo_stock": site})
    if writes:
        names = "، ".join(w["p"]["name"] for w in writes[:4]) + ("…" if len(writes) > 4 else "")
        woo.wlog("push_stock", errors == 0, f"{ledger.fa(pushed)} موفق، {ledger.fa(errors)} ناموفق: {names}")
    if errors:
        with db.tx() as con:
            notify.activity(con, "sync_error", "⚠️ به‌روزرسانی موجودی سایت ناموفق بود",
                            f"{ledger.fa(errors)} محصول ارسال نشد. صفحه «اتصال سایت» را ببینید.", level="danger",
                            link="#/erp/site", notify=True, bot="on_sync_error")
    return {"pushed": pushed, "errors": errors}


async def sync_now() -> dict:
    """Everything at once, on request: orders, every product, then what is waiting to be sent."""
    async with woo.sync_lock():
        report = await refresh(full=True)
        now = time.monotonic()
        _timers.update(pull=now, check=now, full=now)
        pushed = await push_pending()
    return {"checked": report["checked"], "adopted": len(report["adopted"]), "created": report["created"],
            "gone": report["gone"], "drift": len(report["drift"]), **pushed}


def resolve(product_ids: list[int] | None, side: str, user: dict) -> int:
    """A person settles old differences: "site" — the site's number was right (taken over at the next read, within
    seconds); "here" — the number here was right (the site is set to it)."""
    if side not in ("site", "here"):
        raise ledger.LedgerError("کدام طرف درست است؟")
    with db.tx() as con:
        sql = "SELECT id, woo_id FROM products WHERE active = 1 AND woo_id IS NOT NULL AND woo_state = 'conflict'"
        rows = db.rows(con.execute(sql + (f" AND id IN ({','.join('?' * len(product_ids))})" if product_ids else ""),
                                   [int(i) for i in product_ids or []]))
        for r in rows:
            if side == "site":
                con.execute("UPDATE products SET woo_review = 2, woo_state = 'drift' WHERE id = ?", (r["id"],))
            else:
                con.execute("UPDATE products SET woo_review = 0, woo_state = 'force', woo_drift = NULL WHERE id = ?", (r["id"],))
        if rows:
            notify.activity(con, "site_stock", f"اختلاف موجودی {ledger.fa(len(rows))} محصول با سایت حل شد",
                            ("عدد سایت" if side == "site" else "عدد انبار") + f" درست بود — {user['name']}",
                            user_id=user["id"], link="#/erp/site")
            notify.publish_after(con, {"type": "refresh", "scope": "products"})
    if side == "site":
        touch([r["woo_id"] for r in rows])
    wake()
    return len(rows)


def _has_pending() -> bool:
    with db.read() as con:
        return con.execute("""SELECT 1 FROM products WHERE active = 1 AND woo_id IS NOT NULL
                              AND woo_state IN ('pending', 'force') LIMIT 1""").fetchone() is not None


# ---------------------------------------------------------------- background worker

async def _tick(s: dict) -> None:
    global _touch_at
    now = time.monotonic()
    if now < _timers["pause"]:
        return
    minutes = max(1, int(s.get("pull_minutes") or 3)) * 60
    if not enabled(s):
        if now - _timers["pull"] >= minutes:
            _timers["pull"] = now
            await woo.pull_orders()
        return
    if now - _timers["full"] >= FULL_EVERY:
        _timers.update(full=now, check=now, pull=now)
        await refresh(full=True)
    elif now - _timers["check"] >= minutes:
        _timers.update(check=now, pull=now)
        since = s.get("stock_checked_at")
        if since:
            since = (datetime.fromisoformat(since) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S")
        await refresh(changed_since=since or None, full=not since)
    if _touched and now >= _touch_at:
        parents = set(_touched)
        _touched.clear()
        _touch_at = 0.0
        await refresh(parents=parents)
    if _has_pending():
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
