"""The connection to WooCommerce: settings, the HTTP client, reading the catalogue, the sync log, webhooks.

The site address and API keys are the shared connection (Settings → Connections); the ERP keeps only its sync options
(polling interval, webhook secret, last sync, when stock sync started).
"""
import asyncio
import base64
import hashlib
import hmac
import logging

import httpx

from ....core import integrations
from .. import db

log = logging.getLogger("aiko.erp.site")


CURRENCY_FACTOR = {"IRR": 0.1, "IRHR": 100, "IRT": 1, "IRHT": 1000}


_sync_lock: asyncio.Lock | None = None      # one sync job at a time (worker vs. full sync)


def sync_lock() -> asyncio.Lock:
    global _sync_lock
    if _sync_lock is None:
        _sync_lock = asyncio.Lock()
    return _sync_lock


class WooError(Exception):
    pass


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 AikoERP/1.0")


def settings() -> dict:
    """ERP sync options + the shared connection (address, keys, currency) from core."""
    return {**(db.get_setting("woo", {}) or {}), **integrations.woo()}


def configured(s: dict | None = None) -> bool:
    s = s or settings()
    return bool(s.get("url") and s.get("key") and s.get("secret"))


def ensure_webhook_secret() -> None:
    import secrets
    with db.tx() as con:
        s = db.get_setting("woo", {}, con) or {}
        if not s.get("webhook_secret"):
            s["webhook_secret"] = secrets.token_urlsafe(24)
            db.set_setting("woo", s, con)


def adopt_legacy_keys() -> None:
    """Keys used to be saved on the ERP site page; hand them to the shared connection once."""
    s = db.get_setting("woo", {}) or {}
    integrations.adopt("woo", {k: s.get(k) for k in ("url", "key", "secret", "query_auth", "currency")
                               if k != "url" or s.get("key")})
    if s.get("key") or s.get("secret"):
        with db.tx() as con:
            db.set_setting("woo", {k: v for k, v in s.items() if k not in ("url", "key", "secret", "query_auth", "currency")}, con)


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


def _save_woo(changes: dict) -> None:
    with db.tx() as con:
        s = db.get_setting("woo", {}, con) or {}
        s.update(changes)
        db.set_setting("woo", s, con)


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


PRODUCT_FIELDS = ("id,name,type,price,images,permalink,status,manage_stock,stock_quantity,stock_status,sku,"
                  "categories,brands,attributes")


VARIATION_FIELDS = "id,attributes,price,image,status,manage_stock,stock_quantity,stock_status,sku"


def _entry(p: dict, currency: str) -> dict:
    image = (p.get("images") or [{}])[0].get("src") if p.get("images") else None
    return {
        "woo_id": p["id"], "variation_id": None, "type": p.get("type"), "name": _clean(p.get("name")),
        "price": to_toman(p.get("price"), currency), "image": image, "url": p.get("permalink"),
        "status": p.get("status"), "manage_stock": p.get("manage_stock") is True,
        "stock": p.get("stock_quantity"), "in_stock": p.get("stock_status") in ("instock", "onbackorder"),
        "sku": p.get("sku") or "", "categories": [_clean(c.get("name")) for c in p.get("categories") or []],
        "brand": next((_clean(b.get("name")) for b in p.get("brands") or []), "") or _attr(p, ("برند", "brand")),
    }


def _variation_entry(parent: dict, v: dict, currency: str) -> dict:
    label = " / ".join(a.get("option") or "" for a in v.get("attributes") or []) or f"#{v['id']}"
    return {**parent, "variation_id": v["id"], "type": "variation", "name": f"{parent['name']} — {label}",
            "variation_label": label, "price": to_toman(v.get("price"), currency),
            "image": (v.get("image") or {}).get("src") or parent["image"], "status": v.get("status"),
            # "parent": the color uses the product's shared stock; it has no count of its own
            "manage_stock": v.get("manage_stock") is True, "stock": v.get("stock_quantity"),
            "in_stock": v.get("stock_status") in ("instock", "onbackorder"), "sku": v.get("sku") or ""}


async def read_site(woo: "Woo", *, parents: list[int] | None = None, modified_after: str | None = None) -> list[dict]:
    """Site products and their colors with exact stock: all of them, the given products (`parents`), or the ones
    changed after `modified_after` (UTC ISO). A variable product always comes with all of its colors."""
    currency = settings().get("currency") or "IRT"
    base = {"status": "any", "_fields": PRODUCT_FIELDS}
    if modified_after:
        base.update(modified_after=modified_after[:19], dates_are_gmt="true")
    products = []
    if parents is None:
        products = await woo.paged("products", base, limit_pages=200)
    else:
        ids = sorted(set(parents))
        for i in range(0, len(ids), 100):
            products += await woo.paged("products", {**base, "include": ",".join(map(str, ids[i:i + 100]))})
    entries = []
    for p in products:
        parent = _entry(p, currency)
        entries.append(parent)
        if p.get("type") == "variable":
            for v in await woo.paged(f"products/{p['id']}/variations", {"_fields": VARIATION_FIELDS}):
                entries.append(_variation_entry(parent, v, currency))
    return entries


def store_catalog(entries: list[dict], *, full: bool) -> dict:
    """Keep the copy of the site catalogue used for linking and for products created from orders. A partial read
    replaces only the products it read."""
    with db.tx() as con:
        catalog = db.get_setting("woo_catalog", {}, con) or {}
        if full:
            items = entries
        else:
            read = {e["woo_id"] for e in entries}
            items = [e for e in catalog.get("items") or [] if e["woo_id"] not in read] + entries
        catalog = {"fetched_at": db.now() if full else catalog.get("fetched_at") or db.now(), "source": "api",
                   "items": items, "updated_at": db.now()}
        db.set_setting("woo_catalog", catalog, con)
    return catalog


async def fetch_catalog() -> dict:
    """Every site product and color (variation) with exact stock, through the API (keys required)."""
    s = settings()
    if not configured(s):
        raise WooError("اول در «تنظیمات ← سایت و اتصال‌ها» کلیدهای ووکامرس را وارد کنید")
    async with Woo(s) as woo:
        entries = await read_site(woo)
    return store_catalog(entries, full=True)


def _attr(p: dict, names: tuple) -> str:
    for a in p.get("attributes") or []:
        if (a.get("name") or "").strip().lower() in names and a.get("options"):
            return _clean(a["options"][0])
    return ""


def _clean(name: str | None) -> str:
    import html
    return html.unescape(name or "").strip()


def verify_webhook(body: bytes, signature: str | None) -> bool:
    secret = (settings().get("webhook_secret") or "").encode()
    if not secret or not signature:
        return False
    expected = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, signature.strip())


WEBHOOK_TOPICS = {"order.created": "سفارش ایجاد شد", "order.updated": "سفارش به‌روز شد",
                  "product.created": "محصول ایجاد شد", "product.updated": "محصول به‌روز شد",
                  "product.deleted": "محصول حذف شد"}


async def ensure_webhooks(delivery_url: str) -> dict:
    """Create (or re-activate) the site's webhooks to this panel, so orders and product edits arrive instantly.
    Needs a read/write API key. The periodic checks keep everything in step even without them."""
    s = settings()
    if not configured(s):
        raise WooError("اول کلیدهای ووکامرس را وارد کنید")
    secret = s.get("webhook_secret") or ""
    made, fixed = [], []
    async with Woo(s) as woo:
        existing = [w for w in await woo.paged("webhooks", {}, limit_pages=5)
                    if (w.get("delivery_url") or "").rstrip("/") == delivery_url.rstrip("/")]
        by_topic = {w.get("topic"): w for w in existing}
        for topic, label in WEBHOOK_TOPICS.items():
            body = {"name": f"پنل آیکو — {label}", "topic": topic, "delivery_url": delivery_url, "secret": secret,
                    "status": "active", "api_version": "wp_api_v3"}
            if topic in by_topic:
                await woo.request("PUT", f"webhooks/{by_topic[topic]['id']}", json=body)
                fixed.append(topic)
            else:
                await woo.request("POST", "webhooks", json=body)
                made.append(topic)
    _save_woo({"webhooks_at": db.now(), "webhooks_url": delivery_url})
    wlog("webhooks", True, f"{len(made)} وب‌هوک ساخته شد، {len(fixed)} وب‌هوک به‌روز شد")
    return {"created": made, "updated": fixed}
