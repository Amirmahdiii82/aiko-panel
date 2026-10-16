"""WooCommerce connection.

* Stock flows from here to the site: whenever stock of a linked product changes, a background worker
  sets that exact quantity on the site (WooCommerce marks it "out of stock" by itself at 0).
* Website orders flow from the site to here: a webhook delivers them instantly, and the worker also
  polls recent orders every few minutes in case a webhook was missed. Each order becomes one sale.
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import httpx

from . import db, ledger, notify

log = logging.getLogger("aiko.woo")

COUNTED = {"processing", "completed", "on-hold"}       # WooCommerce has already taken these out of stock
CANCELLED = {"cancelled", "refunded", "failed"}
CURRENCY_FACTOR = {"IRR": 0.1, "IRHR": 100, "IRT": 1, "IRHT": 1000}

_loop: asyncio.AbstractEventLoop | None = None
_wake: asyncio.Event | None = None
_pull_now = False


class WooError(Exception):
    pass


# Some Iranian hosts' firewalls drop requests with library user agents; look like a normal browser.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 AikoERP/1.0")


async def _get_json(client: httpx.AsyncClient, url: str, params: dict) -> tuple[list, httpx.Headers]:
    last = ""
    for attempt in range(3):
        try:
            r = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            last = f"ارتباط با سایت برقرار نشد ({exc.__class__.__name__})"
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if r.status_code >= 500:
            last = f"خطای سرور سایت ({r.status_code})"
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise WooError(f"فهرست محصولات سایت خوانده نشد ({r.status_code})")
        try:
            return r.json(), r.headers
        except ValueError:
            raise WooError("پاسخ سایت قابل خواندن نیست؛ شاید فایروال هاست درخواست را بسته است.")
    raise WooError(last or "ارتباط با سایت برقرار نشد")


def settings() -> dict:
    return db.get_setting("woo", {}) or {}


def configured(s: dict | None = None) -> bool:
    s = s or settings()
    return bool(s.get("url") and s.get("key") and s.get("secret"))


def to_toman(value, currency: str | None) -> int:
    try:
        return int(round(float(value or 0) * CURRENCY_FACTOR.get((currency or "IRT").upper(), 1)))
    except (TypeError, ValueError):
        return 0


def wlog(action: str, ok: bool, detail: str = "") -> None:
    with db.tx() as con:
        con.execute("INSERT INTO woo_log (created_at, action, ok, detail) VALUES (?, ?, ?, ?)",
                    (db.now(), action, 1 if ok else 0, detail[:2000]))
        con.execute("DELETE FROM woo_log WHERE id < (SELECT MAX(id) - 500 FROM woo_log)")


# ---------------------------------------------------------------- HTTP client

class Woo:
    def __init__(self, s: dict | None = None):
        s = s or settings()
        self.base = (s.get("url") or "").rstrip("/")
        self.key, self.secret = (s.get("key") or "").strip(), (s.get("secret") or "").strip()
        self.query_auth = bool(s.get("query_auth"))
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=True,
                                        headers={"User-Agent": UA})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()

    async def request(self, method: str, path: str, params: dict | None = None, json=None):
        if not (self.base and self.key and self.secret):
            raise WooError("کلیدهای ووکامرس وارد نشده")
        url = f"{self.base}/wp-json/wc/v3/{path.lstrip('/')}"
        params = dict(params or {})
        auth = None
        if self.query_auth:
            params.update(consumer_key=self.key, consumer_secret=self.secret)
        else:
            auth = (self.key, self.secret)
        last = None
        for attempt in range(3):
            try:
                r = await self.client.request(method, url, params=params, json=json, auth=auth)
            except httpx.HTTPError as exc:
                last = f"ارتباط با سایت برقرار نشد ({exc.__class__.__name__})"
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 500:
                last = f"خطای سرور سایت ({r.status_code})"
                await asyncio.sleep(2 * (attempt + 1))
                continue
            try:
                data = r.json()
            except ValueError:
                raise WooError(f"پاسخ سایت قابل خواندن نیست ({r.status_code}). شاید فایروال هاست درخواست را بسته است.")
            if r.status_code >= 400:
                msg = data.get("message") if isinstance(data, dict) else None
                if r.status_code in (401, 403):
                    hint = " — کلید را با دسترسی «خواندن/نوشتن» بسازید یا گزینه «ارسال کلید در آدرس» را روشن کنید."
                    raise WooError(f"سایت اجازه نداد: {msg or r.status_code}{hint}")
                raise WooError(f"خطای سایت: {msg or r.status_code}")
            return data, r.headers
        raise WooError(last or "ارتباط با سایت برقرار نشد")

    async def paged(self, path: str, params: dict | None = None, limit_pages: int = 50) -> list:
        out, page = [], 1
        while page <= limit_pages:
            data, headers = await self.request("GET", path, {**(params or {}), "per_page": 100, "page": page})
            out.extend(data)
            total_pages = int(headers.get("x-wp-totalpages") or 1)
            if page >= total_pages or not data:
                break
            page += 1
        return out


# ---------------------------------------------------------------- catalog (site products for linking)

async def fetch_catalog() -> dict:
    """All site products and their variations. Uses the authenticated API when keys exist (exact stock),
    otherwise the public Store API (no stock numbers, only in/out of stock)."""
    s = settings()
    entries = []
    if configured(s):
        async with Woo(s) as woo:
            currency = s.get("currency") or "IRT"
            products = await woo.paged("products", {"status": "any"})
            for p in products:
                image = (p.get("images") or [{}])[0].get("src") if p.get("images") else None
                entries.append({
                    "woo_id": p["id"], "variation_id": None, "type": p.get("type"), "name": _clean(p.get("name")),
                    "price": to_toman(p.get("price"), currency), "image": image, "url": p.get("permalink"),
                    "status": p.get("status"), "manage_stock": p.get("manage_stock") is True,
                    "stock": p.get("stock_quantity"), "in_stock": p.get("stock_status") == "instock",
                    "sku": p.get("sku") or "",
                })
                if p.get("type") == "variable":
                    for v in await woo.paged(f"products/{p['id']}/variations"):
                        label = " / ".join(a.get("option") or "" for a in v.get("attributes") or []) or f"#{v['id']}"
                        entries.append({
                            "woo_id": p["id"], "variation_id": v["id"], "type": "variation",
                            "name": f"{_clean(p.get('name'))} — {label}", "variation_label": label,
                            "price": to_toman(v.get("price"), currency),
                            "image": (v.get("image") or {}).get("src") or image, "url": p.get("permalink"),
                            "status": v.get("status"), "manage_stock": v.get("manage_stock") is True,
                            "stock": v.get("stock_quantity"), "in_stock": v.get("stock_status") == "instock",
                            "sku": v.get("sku") or "",
                        })
        source = "api"
    else:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=True,
                                     headers={"User-Agent": UA, "Accept": "application/json"}) as client:
            page = 1
            while page < 30:
                data, _ = await _get_json(client, f"{s.get('url')}/wp-json/wc/store/v1/products",
                                          {"per_page": 100, "page": page})
                entries.extend(store_entries(data))
                if len(data) < 100:
                    break
                page += 1
        source = "public"
    catalog = {"fetched_at": db.now(), "source": source, "items": entries}
    db.set_setting("woo_catalog", catalog)
    with db.tx() as con:
        _refresh_link_details(con, entries)
    return catalog


def store_entries(products: list) -> list[dict]:
    """Catalog entries from the public Store API product list (no stock numbers)."""
    entries = []
    for p in products:
        prices = p.get("prices") or {}
        factor_currency = prices.get("currency_code") or "IRT"
        minor = int(prices.get("currency_minor_unit") or 0)
        price = to_toman(int(prices.get("price") or 0) / (10 ** minor), factor_currency)
        image = (p.get("images") or [{}])[0].get("thumbnail") if p.get("images") else None
        entries.append({
            "woo_id": p["id"], "variation_id": None, "type": p.get("type"), "name": _clean(p.get("name")),
            "price": price, "image": image, "url": p.get("permalink"), "status": "publish",
            "manage_stock": p.get("low_stock_remaining") is not None,
            "stock": p.get("low_stock_remaining"), "in_stock": bool(p.get("is_in_stock")),
            "sku": p.get("sku") or "",
        })
        for v in p.get("variations") or []:
            label = " / ".join(str(a.get("value") or "") for a in v.get("attributes") or []
                               if a.get("value")) or f"#{v['id']}"
            entries.append({
                "woo_id": p["id"], "variation_id": v["id"], "type": "variation",
                "name": f"{_clean(p.get('name'))} — {label}", "variation_label": label, "price": price,
                "image": image, "url": p.get("permalink"), "status": "publish", "manage_stock": None,
                "stock": None, "in_stock": None, "sku": "",
            })
    return entries


def _clean(name: str | None) -> str:
    import html
    return html.unescape(name or "").strip()


def _refresh_link_details(con, entries: list[dict]) -> None:
    """Keep the site name/image/stock shown next to linked products up to date."""
    by_key = {(e["woo_id"], e["variation_id"]): e for e in entries}
    for p in con.execute("SELECT id, woo_id, woo_variation_id, image FROM products WHERE woo_id IS NOT NULL").fetchall():
        e = by_key.get((p["woo_id"], p["woo_variation_id"]))
        if not e:
            con.execute("UPDATE products SET woo_error = 'این محصول در سایت پیدا نشد (حذف شده؟)' WHERE id = ?", (p["id"],))
            continue
        con.execute("UPDATE products SET woo_name = ?, woo_url = ?, image = COALESCE(image, ?), woo_stock = ? WHERE id = ?",
                    (e["name"], e["url"], e["image"], e["stock"], p["id"]))


_AR = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "ۀ": "ه", "‌": " ", "‌": " ",
                     "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"})
_STOP = {"مدل", "شماره", "رنگ", "کد", "و", "با", "|", "-", "—", "–"}


def normalize(text: str) -> str:
    text = (text or "").translate(_AR).lower()
    text = re.sub(r"[()\[\]|،,:;/\\\-–—_+&#.!?\"']", " ", text)
    return " ".join(t for t in text.split() if t not in _STOP)


def score(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    ratio = SequenceMatcher(None, na, nb).ratio()
    return round(0.7 * overlap + 0.3 * ratio, 3)


def _price_factor(ours: int, theirs: int) -> float:
    if not ours or not theirs:
        return 0.0
    r = max(ours, theirs) / min(ours, theirs)
    return 0.05 if r <= 1.15 else (-0.1 if r >= 2 else 0.0)


def suggestions(con, catalog: dict) -> list[dict]:
    """For every unlinked product, up to 3 different site products whose names look most alike.
    Colors of one site product are not offered as separate rivals: the whole product is suggested,
    unless one color clearly matches better (its name is in our product name)."""
    items = catalog.get("items") or []
    linked = {(r[0], r[1]) for r in con.execute(
        "SELECT woo_id, woo_variation_id FROM products WHERE active = 1 AND woo_id IS NOT NULL")}
    whole_linked = {w for w, v in linked if v is None}
    out = []
    for p in con.execute("SELECT id, name, brand, stock, price FROM products WHERE active = 1 AND woo_id IS NULL"):
        name = f"{p['name']} {p['brand'] or ''}"
        best: dict[int, tuple[float, dict]] = {}
        for e in items:
            if (e["woo_id"], e["variation_id"]) in linked or (e["variation_id"] and e["woo_id"] in whole_linked):
                continue
            sc = score(name, e["name"]) + _price_factor(p["price"], e.get("price") or 0)
            if e["variation_id"]:
                sc -= 0.06          # prefer the whole product unless the color is clearly meant
            cur = best.get(e["woo_id"])
            if cur is None or sc > cur[0]:
                best[e["woo_id"]] = (sc, e)
        ranked = sorted(best.values(), key=lambda x: -x[0])[:3]
        out.append({"product": dict(p), "candidates": [{**e, "score": round(min(sc, 1.0), 3)} for sc, e in ranked if sc >= 0.3]})
    return out


def link_product(con, product_id: int, woo_id: int, variation_id: int | None, catalog: dict | None) -> None:
    clash = con.execute("""SELECT name FROM products WHERE active = 1 AND id != ? AND woo_id = ?
                           AND IFNULL(woo_variation_id, 0) = ?""", (product_id, woo_id, variation_id or 0)).fetchone()
    if clash:
        raise ledger.LedgerError(f"این محصول سایت قبلاً به «{clash[0]}» وصل شده")
    entry = next((e for e in (catalog or {}).get("items", [])
                  if e["woo_id"] == woo_id and e["variation_id"] == variation_id), {})
    con.execute("""UPDATE products SET woo_id = ?, woo_variation_id = ?, woo_name = ?, woo_url = ?,
                   image = COALESCE(?, image), woo_stock = ?, woo_state = NULL, woo_error = NULL, updated_at = ?
                   WHERE id = ?""",
                (woo_id, variation_id, entry.get("name"), entry.get("url"), entry.get("image"), entry.get("stock"),
                 db.now(), product_id))
    notify.publish_after(con, {"type": "refresh", "scope": "products"})


# ---------------------------------------------------------------- stock push

async def push_pending() -> dict:
    s = settings()
    if not configured(s):
        return {"pushed": 0, "errors": 0}
    with db.read() as con:
        todo = db.rows(con.execute(
            """SELECT id, name, stock, woo_id, woo_variation_id FROM products
               WHERE active = 1 AND woo_id IS NOT NULL AND woo_state = 'pending' ORDER BY id LIMIT 300"""))
    if not todo:
        return {"pushed": 0, "errors": 0}
    groups: dict[str, list[dict]] = {}
    for p in todo:
        path = f"products/{p['woo_id']}/variations/batch" if p["woo_variation_id"] else "products/batch"
        groups.setdefault(path, []).append(p)
    pushed = errors = 0
    async with Woo(s) as woo:
        for path, items in groups.items():
            for chunk in (items[i:i + 100] for i in range(0, len(items), 100)):
                payload = {"update": [{"id": p["woo_variation_id"] or p["woo_id"], "manage_stock": True,
                                       "stock_quantity": max(0, p["stock"])} for p in chunk]}
                try:
                    data, _ = await woo.request("POST", path, json=payload)
                    results = {r.get("id"): r for r in (data.get("update") or [])}
                except WooError as exc:
                    results = {}
                    for p in chunk:
                        results[p["woo_variation_id"] or p["woo_id"]] = {"error": {"message": str(exc)}}
                with db.tx() as con:
                    for p in chunk:
                        r = results.get(p["woo_variation_id"] or p["woo_id"]) or {"error": {"message": "پاسخی نیامد"}}
                        if r.get("error"):
                            errors += 1
                            msg = r["error"].get("message") or "خطا"
                            con.execute("UPDATE products SET woo_state = 'error', woo_error = ? WHERE id = ?", (msg, p["id"]))
                            notify.publish_after(con, {"type": "product", "id": p["id"], "woo_state": "error"})
                        else:
                            pushed += 1
                            # if stock changed again while we were sending, leave it pending for the next round
                            con.execute("""UPDATE products SET woo_state = CASE WHEN stock = ? THEN 'ok' ELSE 'pending' END,
                                           woo_error = NULL, woo_synced_at = ?, woo_stock = ? WHERE id = ?""",
                                        (p["stock"], db.now(), r.get("stock_quantity"), p["id"]))
                            notify.publish_after(con, {"type": "product", "id": p["id"], "woo_state": "ok",
                                                       "woo_stock": r.get("stock_quantity")})
    names = "، ".join(p["name"] for p in todo[:4]) + ("…" if len(todo) > 4 else "")
    wlog("push_stock", errors == 0, f"{pushed} موفق، {errors} ناموفق: {names}")
    if errors:
        with db.tx() as con:
            notify.activity(con, "sync_error", "⚠️ به‌روزرسانی موجودی سایت ناموفق بود",
                            f"{ledger.fa(errors)} محصول ارسال نشد. صفحه «سایت» را ببینید.", level="danger",
                            link="#/erp/site", notify=True, bot="on_sync_error")
    return {"pushed": pushed, "errors": errors}


# ---------------------------------------------------------------- orders

def _map_line(con, product_id: int, variation_id: int | None) -> dict | None:
    if variation_id:
        row = db.one(con.execute("""SELECT id, avg_cost FROM products WHERE active = 1 AND woo_id = ?
                                    AND woo_variation_id = ?""", (product_id, variation_id)))
        if row:
            return row
    return db.one(con.execute("""SELECT id, avg_cost FROM products WHERE active = 1 AND woo_id = ?
                                 AND woo_variation_id IS NULL""", (product_id,)))


def process_order(order: dict) -> str:
    """Create, update or void the sale that mirrors one WooCommerce order. Returns what happened."""
    oid, status = order.get("id"), order.get("status")
    if not oid or not status:
        return "ignored"
    currency = order.get("currency") or "IRT"
    with db.tx() as con:
        existing = db.one(con.execute("SELECT * FROM sales WHERE woo_order_id = ?", (oid,)))
        if status in COUNTED and not existing:
            items, unmapped = [], []
            for li in order.get("line_items") or []:
                qty = int(li.get("quantity") or 0)
                if qty <= 0:
                    continue
                mapped = _map_line(con, li.get("product_id"), li.get("variation_id") or None)
                unit_price = to_toman(float(li.get("subtotal") or 0) / qty, currency)
                if mapped:
                    items.append({"product_id": mapped["id"], "qty": qty, "unit_price": unit_price})
                else:
                    unmapped.append(li.get("name") or "")
                    items.append({"name": f"{li.get('name')} (به انبار وصل نیست)", "qty": qty, "unit_price": unit_price})
            if not items:
                return "empty"
            billing = order.get("billing") or {}
            created = (order.get("date_created") or db.today())[:10]
            account = (db.get_setting("channel_accounts", {}, con) or {}).get("website")
            number = order.get("number") or oid
            sale_id = ledger.create_sale(con, {
                "code": f"WEB-{number}", "date": created, "channel": "website",
                "customer_name": " ".join(filter(None, [billing.get("first_name"), billing.get("last_name")])),
                "customer_phone": billing.get("phone"), "items": items,
                "discount": to_toman(order.get("discount_total"), currency),
                "shipping": to_toman(order.get("shipping_total"), currency),
                "total": to_toman(order.get("total"), currency),
                "paid": status != "on-hold", "account_id": account, "woo_order_id": oid, "woo_status": status,
                "note": f"سفارش سایت #{number} — {order.get('payment_method_title') or ''}".strip(" —"),
            }, None)
            if unmapped:
                notify.activity(con, "sync_warning", "سفارش سایت محصولی دارد که به انبار وصل نیست",
                                "، ".join(unmapped) + " — موجودی این‌ها کم نشد. از صفحه «سایت» وصلشان کنید.",
                                level="warning", link=f"#/erp/sales/{sale_id}", notify=True)
            return "created"
        if not existing:
            return "ignored"
        if status in CANCELLED and existing["status"] == "done":
            ledger.void_sale(con, existing["id"], None, f"سفارش در سایت «{status}» شد")
            con.execute("UPDATE sales SET woo_status = ? WHERE id = ?", (status, existing["id"]))
            return "voided"
        if status in COUNTED and existing["status"] == "void":
            notify.activity(con, "sync_warning", f"سفارش لغوشده {existing['code']} در سایت دوباره فعال شد",
                            "موجودی خودکار کم نشد؛ لطفاً بررسی کنید و در صورت نیاز فروش را دوباره ثبت کنید.",
                            level="warning", link=f"#/erp/sales/{existing['id']}", notify=True)
        paid = 1 if status in ("processing", "completed") else existing["paid"]
        con.execute("UPDATE sales SET woo_status = ?, paid = ?, updated_at = ? WHERE id = ?",
                    (status, paid, db.now(), existing["id"]))
        notify.publish_after(con, {"type": "refresh", "scope": "sales"})
        return "updated"


async def pull_orders(since_iso: str | None = None) -> dict:
    s = settings()
    if not configured(s):
        return {"created": 0}
    since = since_iso or s.get("last_order_sync")
    if not since:
        since = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        _save_woo({"last_order_sync": since})
        return {"created": 0, "note": "از این لحظه به بعد سفارش‌ها خوانده می‌شوند"}
    started = datetime.now(timezone.utc).replace(microsecond=0)
    # a small overlap so an order modified during the previous request is never missed
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) - timedelta(minutes=2)
    counts: dict[str, int] = {}
    async with Woo(s) as woo:
        orders = await woo.paged("orders", {"modified_after": since_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                                            "dates_are_gmt": "true", "orderby": "date", "order": "asc"}, limit_pages=10)
    for order in orders:
        result = await asyncio.to_thread(process_order, order)
        counts[result] = counts.get(result, 0) + 1
    _save_woo({"last_order_sync": started.isoformat()})
    if orders:
        wlog("pull_orders", True, f"{len(orders)} سفارش بررسی شد: {counts}")
    return counts


def _save_woo(changes: dict) -> None:
    with db.tx() as con:
        s = db.get_setting("woo", {}, con) or {}
        s.update(changes)
        db.set_setting("woo", s, con)


def verify_webhook(body: bytes, signature: str | None) -> bool:
    secret = (settings().get("webhook_secret") or "").encode()
    if not secret or not signature:
        return False
    expected = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, signature.strip())


async def test_connection(s: dict) -> dict:
    async with Woo(s) as woo:
        data, headers = await woo.request("GET", "products", {"per_page": 1})
        total = headers.get("x-wp-total")
        currency = None
        try:
            cur, _ = await woo.request("GET", "settings/general/woocommerce_currency")
            currency = cur.get("value")
        except WooError:
            pass
    return {"ok": True, "products": int(total) if total else len(data), "currency": currency}


# ---------------------------------------------------------------- background worker

def wake() -> None:
    if _loop and _wake:
        _loop.call_soon_threadsafe(_wake.set)


def request_pull() -> None:
    global _pull_now
    _pull_now = True
    wake()


async def worker() -> None:
    global _loop, _wake, _pull_now
    _loop = asyncio.get_running_loop()
    _wake = asyncio.Event()
    ledger.sync_wake = wake
    last_pull = 0.0
    while True:
        try:
            await asyncio.wait_for(_wake.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass
        _wake.clear()
        await asyncio.sleep(1.2)   # gather a burst of changes into one request
        s = settings()
        if not configured(s):
            continue
        try:
            if s.get("auto_push"):
                await push_pending()
            minutes = max(1, int(s.get("pull_minutes") or 3))
            if _pull_now or time.monotonic() - last_pull >= minutes * 60:
                _pull_now = False
                last_pull = time.monotonic()
                await pull_orders()
        except WooError as exc:
            wlog("worker", False, str(exc))
            last_pull = time.monotonic()
        except Exception:   # never let the worker die
            log.exception("woo worker error")
            await asyncio.sleep(10)
