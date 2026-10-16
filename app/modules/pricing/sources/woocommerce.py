"""WooCommerce stores: uses the public Store API, falls back to the HTML search page."""
import html as htmllib
import re
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from .. import textnorm as tn
from ..matching import Candidate
from .base import Source, strip_tags


def woo_price(prices: dict | None, field: str = "price") -> int | None:
    """Store API prices are strings in minor units; convert to Toman."""
    if not prices or prices.get(field) in (None, ""):
        return None
    value = int(prices[field]) / (10 ** int(prices.get("currency_minor_unit") or 0))
    if (prices.get("currency_code") or "").upper() == "IRR":
        value /= 10
    return int(round(value)) or None


def woo_brand(p: dict) -> str | None:
    if p.get("brands"):
        return htmllib.unescape(p["brands"][0].get("name") or "") or None
    for attr in p.get("attributes") or []:
        if tn.normalize(attr.get("name")) in ("برند", "brand", "نام برند", "سازنده"):
            terms = attr.get("terms") or []
            if terms:
                return htmllib.unescape(terms[0].get("name") or "")
    return tn.detect_brand(p.get("name") or "")


class WooCommerceSource(Source):
    supports_refresh = True

    def __init__(self, key: str, name: str, homepage: str):
        super().__init__()
        self.key, self.name, self.homepage = key, name, homepage.rstrip("/")
        self._use_html = False

    def _to_candidate(self, p: dict) -> Candidate:
        prices = p.get("prices") or {}
        price = woo_price(prices, "price")
        regular = woo_price(prices, "regular_price") or price
        extra = {}
        if prices.get("price_range"):
            rng = {"currency_minor_unit": prices.get("currency_minor_unit"), "currency_code": prices.get("currency_code")}
            extra["price_range"] = [
                woo_price({**rng, "price": prices["price_range"].get("min_amount")}),
                woo_price({**rng, "price": prices["price_range"].get("max_amount")}),
            ]
        if p.get("variations"):
            extra["variants"] = len(p["variations"])
        return Candidate(
            site=self.key,
            external_id=str(p["id"]),
            title=htmllib.unescape(p.get("name") or ""),
            url=p.get("permalink") or "",
            price=price,
            regular_price=regular,
            in_stock=bool(p.get("is_in_stock")) and bool(price),
            image=(p.get("images") or [{}])[0].get("thumbnail") if p.get("images") else None,
            brand=woo_brand(p),
            barcode=p.get("sku") or None,
            extra=extra,
        )

    async def search(self, query: str) -> list[Candidate]:
        if not self._use_html:
            data = await self.get(
                f"{self.homepage}/wp-json/wc/store/v1/products",
                params={"search": query, "per_page": 20},
                expect_json=True,
            )
            if isinstance(data, list):
                return [self._to_candidate(p) for p in data]
            self._use_html = True  # Store API disabled on this site
        return await self._search_html(query)

    async def _search_html(self, query: str) -> list[Candidate]:
        page = await self.get(self.homepage + "/", params={"s": query, "post_type": "product"})
        if not page:
            return []
        soup = BeautifulSoup(page, "lxml")
        out = []
        for li in soup.select("li.product, div.product-grid-item, div.product.type-product, .products .product"):
            a = li.select_one("a.woocommerce-LoopProduct-link, .woocommerce-loop-product__title a, h2 a, h3 a, a[href*='/product']")
            title_el = li.select_one(".woocommerce-loop-product__title, .wd-entities-title, .product-title, h2, h3")
            if not a or not title_el:
                continue
            ins = li.select_one(".price ins .woocommerce-Price-amount") or li.select_one(".price .woocommerce-Price-amount")
            dele = li.select_one(".price del .woocommerce-Price-amount")
            price = tn.parse_price(ins.get_text()) if ins else None
            cur = (li.select_one(".woocommerce-Price-currencySymbol") or soup.new_tag("x")).get_text()
            if price and "ریال" in cur:
                price //= 10
            regular = tn.parse_price(dele.get_text()) if dele else price
            if regular and "ریال" in cur and dele:
                regular //= 10
            pid = None
            m = re.search(r"post-(\d+)", " ".join(li.get("class", [])))
            if m:
                pid = m.group(1)
            href = a.get("href") or ""
            out.append(Candidate(
                site=self.key, external_id=pid or unquote(urlparse(href).path).strip("/"),
                title=strip_tags(title_el.get_text()), url=href, price=price, regular_price=regular,
                in_stock="outofstock" not in " ".join(li.get("class", [])) and bool(price),
                image=(li.select_one("img") or {}).get("src") if li.select_one("img") else None,
            ))
        # de-duplicate by id
        seen, uniq = set(), []
        for c in out:
            if c.external_id not in seen:
                seen.add(c.external_id)
                uniq.append(c)
        return uniq

    async def refresh(self, external_id: str, url: str) -> Candidate | None:
        if external_id.isdigit() and not self._use_html:
            data = await self.get(f"{self.homepage}/wp-json/wc/store/v1/products/{external_id}", expect_json=True)
            if isinstance(data, dict) and data.get("id"):
                return self._to_candidate(data)
        return None

    async def from_url(self, url: str) -> Candidate | None:
        path = unquote(urlparse(url).path).strip("/")
        if not path:
            return None
        slug = path.split("/")[-1]
        data = await self.get(f"{self.homepage}/wp-json/wc/store/v1/products", params={"slug": slug}, expect_json=True)
        if isinstance(data, list) and data:
            return self._to_candidate(data[0])
        return None

    # ---- own catalog -------------------------------------------------------------------
    async def all_products(self, limit: int = 0) -> list[dict]:
        """Every published product of a WooCommerce store, as raw Store API dicts."""
        products, page = [], 1
        while True:
            data = await self.get(
                f"{self.homepage}/wp-json/wc/store/v1/products",
                params={"per_page": 100, "page": page, "orderby": "id", "order": "asc"},
                expect_json=True,
            )
            if not isinstance(data, list) or not data:
                break
            products.extend(data)
            if len(data) < 100 or (limit and len(products) >= limit):
                break
            page += 1
        return products[:limit] if limit else products


def size_hint(p: dict) -> str | None:
    """'50 میل' from a single-valued size attribute, used when the title has no size."""
    for attr in p.get("attributes") or []:
        if tn.normalize(attr.get("name")) in ("حجم", "وزن", "مقدار", "size", "volume", "weight", "حجم محصول"):
            terms = attr.get("terms") or []
            if len(terms) == 1:
                return htmllib.unescape(terms[0].get("name") or "") or None
    return None


def own_product_row(p: dict) -> dict:
    prices = p.get("prices") or {}
    price = woo_price(prices, "price")
    return {
        "id": p["id"],
        "name": htmllib.unescape(p.get("name") or "").strip(),
        "slug": p.get("slug"),
        "sku": p.get("sku") or None,
        "permalink": p.get("permalink"),
        "image": (p.get("images") or [{}])[0].get("thumbnail") if p.get("images") else None,
        "brand": woo_brand(p),
        "size_hint": size_hint(p),
        "categories": [htmllib.unescape(c.get("name") or "") for c in p.get("categories") or []],
        "price": price,
        "regular_price": woo_price(prices, "regular_price") or price,
        "in_stock": 1 if (p.get("is_in_stock") and price) else 0,
    }
