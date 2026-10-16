"""Minimal OpenRouter client for video/image generation (key and proxy never reach the browser).

The key and the outbound proxy are shared connections (Settings → Connections, `app.core.integrations`):
OpenRouter is not reachable from an Iranian server, so every request goes through that proxy.
Only the monthly spending cap is the studio's own setting. httpx tunnels HTTPS through an HTTP CONNECT
(or SOCKS) proxy natively.
"""
import json
import logging
import time

import httpx

from ...core import config as core_config
from ...core import integrations
from . import db

log = logging.getLogger("aiko.media.openrouter")
ORIGIN = core_config.env("OPENROUTER_BASE_URL", "https://openrouter.ai").rstrip("/")  # override only for tests/mocks
JSON_LIMIT = 2 * 1024 * 1024
IMAGE_JSON_LIMIT = 64 * 1024 * 1024
_cache: dict[str, tuple[float, dict]] = {}


class UpstreamError(Exception):
    def __init__(self, status: int, message: str, code: str = "openrouter_error", retry_after: str | None = None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after


def settings() -> dict:
    s = db.database.get_setting("openrouter", {}) or {}
    return {"api_key": integrations.openrouter_key(), "proxy_url": integrations.proxy_url(),
            "monthly_limit_usd": float(s.get("monthly_limit_usd") or 0)}


def adopt_legacy() -> None:
    """The key and proxy used to be studio settings; hand them to the shared connections once."""
    s = db.database.get_setting("openrouter", {}) or {}
    integrations.adopt("openrouter", {"api_key": s.get("api_key") or core_config.env("OPENROUTER_API_KEY")})
    integrations.adopt("network", {"proxy_url": s.get("proxy_url") or core_config.env("OPENROUTER_PROXY_URL")})
    if s.get("api_key") or s.get("proxy_url"):
        db.database.set_setting("openrouter", {k: v for k, v in s.items() if k not in ("api_key", "proxy_url")})


def configured() -> bool:
    return bool(settings()["api_key"])


def _client(timeout: float) -> httpx.AsyncClient:
    s = settings()
    if not s["api_key"]:
        raise UpstreamError(503, "کلید OpenRouter تنظیم نشده است (تنظیمات ← اتصال‌ها).", "missing_api_key")
    return httpx.AsyncClient(base_url=ORIGIN, timeout=httpx.Timeout(timeout, connect=20), proxy=s["proxy_url"] or None,
                             headers={"Authorization": f"Bearer {s['api_key']}", "X-Title": "Aiko Panel"},  # header values must be ASCII
                             follow_redirects=True)


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return f"OpenRouter خطا داد ({resp.status_code})"
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return err.get("message") or json.dumps(err, ensure_ascii=False)[:300]
    if isinstance(err, str):
        return err
    return (data.get("message") if isinstance(data, dict) else None) or f"OpenRouter خطا داد ({resp.status_code})"


async def request_json(method: str, path: str, *, body: dict | None = None, timeout: float = 30,
                       limit: int = JSON_LIMIT) -> dict:
    try:
        async with _client(timeout) as client:
            resp = await client.request(method, path, json=body, headers={"Accept": "application/json"})
    except httpx.TimeoutException:
        raise UpstreamError(504, "OpenRouter به‌موقع جواب نداد.", "openrouter_timeout")
    except httpx.HTTPError as exc:
        log.warning("OpenRouter unreachable: %s", exc.__class__.__name__)   # never log the proxy URL or key
        raise UpstreamError(502, "سرور به OpenRouter وصل نشد (پروکسی/اینترنت را بررسی کنید).", "openrouter_unavailable")
    if len(resp.content) > limit:
        raise UpstreamError(502, "پاسخ OpenRouter بیش از حد بزرگ بود.", "invalid_upstream_response")
    if resp.status_code >= 400:
        raise UpstreamError(resp.status_code, _error_message(resp), retry_after=resp.headers.get("retry-after"))
    try:
        return resp.json()
    except ValueError:
        raise UpstreamError(502, "پاسخ OpenRouter قابل خواندن نبود.", "invalid_upstream_response")


async def cached(path: str, ttl: int = 600) -> dict:
    hit = _cache.get(path)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    data = await request_json("GET", path)
    _cache[path] = (time.monotonic(), data)
    return data


def clear_cache() -> None:
    _cache.clear()


async def download(path: str, dest, *, timeout: float = 600) -> tuple[str, int]:
    """Stream generated content to a file. Returns (content_type, bytes)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    size = 0
    try:
        async with _client(timeout) as client:
            async with client.stream("GET", path, headers={"Accept": "video/*, application/octet-stream;q=0.9"}) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise UpstreamError(resp.status_code, _error_message(resp))
                ctype = resp.headers.get("content-type", "application/octet-stream").split(";")[0]
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tmp.open("wb") as f:
                    async for chunk in resp.aiter_bytes(1024 * 256):
                        size += len(chunk)
                        f.write(chunk)
        tmp.replace(dest)
        return ctype, size
    except httpx.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise UpstreamError(502, f"دانلود از OpenRouter ناموفق بود ({exc.__class__.__name__})", "download_failed")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
