"""Shared HTTP plumbing for all site adapters: politeness, retries, block detection."""
import asyncio
import json
import random
import re

import httpx

from .. import config
from ..matching import Candidate


class SiteBlocked(Exception):
    """The site answered with a captcha / bot wall, or cannot be reached; stop hitting it for this run."""


class Source:
    key: str = ""
    name: str = ""
    homepage: str = ""
    # True if the site is a marketplace with many sellers (Torob, Basalam, Digikala)
    marketplace: bool = False
    supports_refresh: bool = False
    # Per-site politeness (None = global settings). Strict sites get fewer, slower requests.
    concurrency: int | None = None
    delay: float | None = None
    max_queries: int | None = None     # search queries per product (None = all fallbacks)
    cooldown_hours: float = 0          # after a block, skip this site for this long

    def __init__(self):
        self._sem = asyncio.Semaphore(self.concurrency or config.SITE_CONCURRENCY)
        self._client: httpx.AsyncClient | None = None
        self._blocked_hits = 0
        self._net_failures = 0

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
            },
            timeout=config.REQUEST_TIMEOUT,
            follow_redirects=True,
            proxy=config.HTTP_PROXY,
        )
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    async def get(self, url: str, *, params=None, headers=None, expect_json=False, retries=3):
        last_exc: Exception | None = None
        for attempt in range(retries):
            async with self._sem:
                await asyncio.sleep((self.delay or config.REQUEST_DELAY) * random.uniform(0.7, 1.4))
                try:
                    r = await self._client.get(url, params=params, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_exc = e
                    self._net_failures += 1
                    if self._net_failures >= 4:
                        raise SiteBlocked(
                            f"{self.name}: سایت در دسترس نیست ({type(e).__name__}). "
                            "شاید فقط از IP ایران باز می‌شود یا موقتاً قطع است."
                        ) from e
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
            self._net_failures = 0
            if r.status_code in (403, 429, 490) or "arcaptcha" in r.text[:3000] or "آیا شما یک ربات" in r.text[:3000]:
                self._blocked_hits += 1
                if self._blocked_hits >= 3:
                    raise SiteBlocked(f"{self.name}: HTTP {r.status_code} (captcha / rate limit)")
                await asyncio.sleep(8 * (attempt + 1))
                continue
            if r.status_code >= 500:
                last_exc = httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            self._blocked_hits = 0
            if expect_json:
                try:
                    return r.json()
                except json.JSONDecodeError:
                    return None
            return r.text
        if last_exc:
            raise last_exc
        return None

    # ---- adapter API -------------------------------------------------------------------
    async def search(self, query: str) -> list[Candidate]:
        raise NotImplementedError

    async def refresh(self, external_id: str, url: str) -> Candidate | None:
        """Re-read one known listing directly (used for confirmed matches missing from search)."""
        return None

    async def enrich(self, cand: Candidate) -> Candidate:
        """Add detail for a matched listing (e.g. every seller on a marketplace). Optional."""
        return cand

    async def from_url(self, url: str) -> Candidate | None:
        """Read a product from a pasted URL (manual match). Optional."""
        return None


def strip_tags(html: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()
