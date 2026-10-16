"""Connections every module shares, set once in Settings → Connections (stored in core.db):

* `woo`       the shop's WooCommerce site (address + REST API keys). The ERP syncs stock and orders with it,
              the price checker reads the shop's own catalogue from it.
* `network`   an outbound proxy for services that are filtered or unreachable from an Iranian server
              (Telegram, OpenRouter, ...). Domestic services (the shop site, Bale, competitor sites) never use it.
* `openrouter` the OpenRouter API key used by the media studio.

Secrets never leave the server: the public view only says whether a key is set.
Modules read these through the functions below; they never touch the core settings table themselves.
"""
import asyncio

import httpx

from . import config, db

PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 AikoPanel/1.0")


class IntegrationError(ValueError):
    """A user-facing configuration problem (message shown as-is)."""


def _get(key: str) -> dict:
    return db.core.get_setting(key, {}) or {}


def _merge(key: str, changes: dict) -> dict:
    with db.core.tx() as con:
        current = db.core.get_setting(key, {}, con) or {}
        current.update(changes)
        db.core.set_setting(key, current, con)
    return current


# ---------------------------------------------------------------- outbound proxy
def proxy_url() -> str:
    return (_get("network").get("proxy_url") or config.env("OUTBOUND_PROXY_URL")).strip()


def check_proxy(url: str) -> str:
    url = (url or "").strip()
    if url and url.split("://")[0].lower() not in PROXY_SCHEMES:
        raise IntegrationError("آدرس پروکسی باید با http:// یا socks5:// شروع شود")
    return url


def save_proxy(url: str) -> None:
    _merge("network", {"proxy_url": check_proxy(url)})


def abroad_client(**kwargs) -> httpx.AsyncClient:
    """HTTP client for a service outside Iran (Telegram, OpenRouter, ...): goes through the proxy when one is set."""
    kwargs.setdefault("timeout", httpx.Timeout(30, connect=20))
    return httpx.AsyncClient(proxy=proxy_url() or None, **kwargs)


# ---------------------------------------------------------------- WooCommerce
WOO_FIELDS = ("url", "key", "secret", "query_auth", "currency")


def woo() -> dict:
    s = _get("woo")
    url = (s.get("url") or config.env("WOO_URL") or config.env("OWN_SITE_URL") or "https://aikocosmetics.ir").rstrip("/")
    return {"url": url, "key": (s.get("key") or "").strip(), "secret": (s.get("secret") or "").strip(),
            "query_auth": bool(s.get("query_auth")), "currency": s.get("currency") or ""}


def woo_configured(s: dict | None = None) -> bool:
    s = s or woo()
    return bool(s["url"] and s["key"] and s["secret"])


def save_woo(changes: dict) -> dict:
    clean = {}
    for k in WOO_FIELDS:
        if k not in changes:
            continue
        v = changes[k]
        if k == "secret" and not v:
            continue                      # empty secret field = keep the saved one
        clean[k] = v.strip().rstrip("/") if isinstance(v, str) else v
    return _merge("woo", clean)


def woo_public() -> dict:
    s = woo()
    return {"url": s["url"], "key": s["key"], "secret_set": bool(s["secret"]), "query_auth": s["query_auth"],
            "currency": s["currency"], "configured": woo_configured(s)}


async def test_woo() -> dict:
    """Check the keys against the site (read access to products) and learn the store currency."""
    s = woo()
    if not woo_configured(s):
        raise IntegrationError("آدرس سایت، کلید و رمز ووکامرس را کامل وارد کنید")
    params = {"per_page": 1}
    auth = None
    if s["query_auth"]:
        params.update(consumer_key=s["key"], consumer_secret=s["secret"])
    else:
        auth = (s["key"], s["secret"])
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=True,
                                 headers={"User-Agent": UA}) as client:
        try:
            r = await client.get(f"{s['url']}/wp-json/wc/v3/products", params=params, auth=auth)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"ارتباط با سایت برقرار نشد ({exc.__class__.__name__})")
        if r.status_code in (401, 403):
            raise IntegrationError("سایت کلید را نپذیرفت — کلید را با دسترسی «خواندن/نوشتن» بسازید "
                                   "یا گزینه «ارسال کلید در آدرس» را روشن کنید.")
        if r.status_code != 200:
            raise IntegrationError(f"پاسخ نامعتبر از سایت ({r.status_code})")
        total = r.headers.get("x-wp-total")
        currency = None
        try:
            c = await client.get(f"{s['url']}/wp-json/wc/v3/settings/general/woocommerce_currency",
                                 params=params, auth=auth)
            if c.status_code == 200:
                currency = (c.json() or {}).get("value")
        except (httpx.HTTPError, ValueError):
            pass
    if currency:
        _merge("woo", {"currency": currency})
    return {"ok": True, "products": int(total) if total else None, "currency": currency or s["currency"] or None}


# ---------------------------------------------------------------- OpenRouter
def openrouter_key() -> str:
    return (_get("openrouter").get("api_key") or config.env("OPENROUTER_API_KEY")).strip()


def save_openrouter_key(key: str) -> None:
    _merge("openrouter", {"api_key": (key or "").strip()})


async def test_proxy() -> dict:
    """Reach Telegram and OpenRouter through the configured proxy (or directly when none is set)."""
    targets = {"telegram": "https://api.telegram.org/", "openrouter": "https://openrouter.ai/api/v1/models?limit=1"}

    async def probe(url: str) -> str:
        try:
            async with abroad_client(timeout=httpx.Timeout(20, connect=12)) as client:
                r = await client.get(url)
            return "ok" if r.status_code < 500 else f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            return exc.__class__.__name__
    results = await asyncio.gather(*(probe(u) for u in targets.values()))
    return {"proxy": bool(proxy_url()), **dict(zip(targets, results))}


# ---------------------------------------------------------------- one-time move of keys that modules used to keep
def adopt(key: str, values: dict) -> bool:
    """Called by a module at startup with credentials it stored before they moved here.
    Only fills fields that are still empty in core, so a value set in Settings always wins."""
    values = {k: v for k, v in values.items() if v not in (None, "")}
    if not values:
        return False
    current = _get(key)
    missing = {k: v for k, v in values.items() if not current.get(k)}
    if missing:
        _merge(key, missing)
    return bool(missing)
