"""Torob (price aggregator). Search API gives the lowest price and how many shops sell it.
Torob is strict about bots, so requests are kept low and the adapter backs off on captcha."""
import json
import re

from .. import config
from .. import textnorm as tn
from ..matching import Candidate
from .base import Source

API = "https://api.torob.com/v4/base-product"


class TorobSource(Source):
    key, name, homepage = "torob", "ترب", "https://torob.com"
    marketplace = True
    concurrency = 1
    delay = 6.0
    max_queries = 1
    cooldown_hours = 23   # after a block, skip the next scheduled run instead of hitting the wall again

    def _from_search(self, p: dict) -> Candidate:
        shop_text = p.get("shop_text") or ""
        m = re.search(r"(\d+)\s*فروشگاه", tn.normalize(shop_text))
        price = p.get("price") or None
        return Candidate(
            site=self.key,
            external_id=p.get("random_key") or "",
            title=f"{p.get('name1') or ''} {p.get('name2') or ''}".strip(),
            url=self.homepage + (p.get("web_client_absolute_url") or ""),
            price=int(price) if price else None,
            regular_price=int(price) if price else None,
            in_stock=bool(price) and "ناموجود" not in (p.get("stock_status") or ""),
            seller=None if m else shop_text.replace("در ", "", 1).strip() or None,
            image=p.get("image_url"),
            extra={"shops": int(m.group(1)) if m else 1, "price_text": p.get("price_text")},
        )

    async def search(self, query: str) -> list[Candidate]:
        data = await self.get(
            f"{API}/search/",
            params={"q": query, "page": 0, "size": 24, "source": "next_desktop"},
            expect_json=True,
        )
        return [self._from_search(p) for p in ((data or {}).get("results") or [])[:20] if p.get("random_key")]

    async def enrich(self, cand: Candidate) -> Candidate:
        """Best effort: read every shop's offer from the product page. Off unless TOROB_SELLERS=1,
        because it doubles the requests to Torob and is what usually triggers its captcha."""
        if not config.TOROB_SELLERS or (cand.extra or {}).get("shops", 1) <= 1:
            return cand
        try:
            page = await self.get(cand.url, retries=1)
        except Exception:
            return cand
        if not page:
            return cand
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        if not m:
            return cand
        try:
            data = json.loads(m.group(1))
        except ValueError:
            return cand
        offers = _find_offers(data)
        own = tn.normalize(config.OWN_SITE_NAME)
        sellers = []
        for o in offers:
            price = o.get("price")
            if not price:
                continue
            name = o.get("shop_name") or o.get("shop_name2") or ""
            sellers.append({
                "seller": name,
                "price": int(price),
                "in_stock": o.get("availability", True) is not False,
                "is_me": bool(own) and own in tn.normalize(name),
                "url": o.get("page_url"),
            })
        if sellers:
            sellers.sort(key=lambda s: s["price"])
            cand.extra["sellers"] = sellers[:60]
            others = [s for s in sellers if not s["is_me"] and s["in_stock"]]
            if others:
                cand.price = cand.regular_price = others[0]["price"]
                cand.seller = others[0]["seller"]
        return cand


def _find_offers(node, depth=0):
    """Walk Torob's page data for the list of shop offers (structure changes over time)."""
    if depth > 8:
        return []
    if isinstance(node, dict):
        for key in ("products_info", "products"):
            val = node.get(key)
            if isinstance(val, dict) and isinstance(val.get("result"), list):
                return val["result"]
        for v in node.values():
            found = _find_offers(v, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        if node and isinstance(node[0], dict) and "shop_name" in node[0] and "price" in node[0]:
            return node
        for v in node[:50]:
            found = _find_offers(v, depth + 1)
            if found:
                return found
    return []
