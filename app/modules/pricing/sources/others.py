"""Adapters for Basalam, Khanoumi, Rojashop and Elanza."""
import json
import re
import uuid
from urllib.parse import unquote

from bs4 import BeautifulSoup

from .. import textnorm as tn
from ..matching import Candidate
from .base import Source, strip_tags


class BasalamSource(Source):
    """Marketplace: every vendor's listing is its own offer. Prices in Rial."""
    key, name, homepage = "basalam", "باسلام", "https://basalam.com"
    marketplace = True

    async def search(self, query: str) -> list[Candidate]:
        data = await self.get(
            "https://search.basalam.com/ai-engine/api/v2.0/product/search",
            params={"q": query, "from": 0, "size": 24},
            expect_json=True,
        )
        out = []
        for p in (data or {}).get("products") or []:
            vendor = p.get("vendor") or {}
            price = int(p["price"]) // 10 if p.get("price") else None
            primary = int(p["primaryPrice"]) // 10 if p.get("primaryPrice") else price
            status = ((p.get("status") or {}).get("title")) or ""
            out.append(Candidate(
                site=self.key,
                external_id=str(p["id"]),
                title=p.get("name") or "",
                url=f"{self.homepage}/{vendor.get('identifier', 'p')}/product/{p['id']}",
                price=price,
                regular_price=max(primary or 0, price or 0) or None,
                in_stock=bool(price) and (p.get("stock") or 0) > 0 and "ناموجود" not in status,
                seller=vendor.get("name"),
                image=(p.get("photo") or {}).get("MEDIUM"),
                extra={"sales": p.get("sales_count"), "city": (vendor.get("owner") or {}).get("city")},
            ))
        return out


class KhanoumiSource(Source):
    """Khanoumi's own catalog API (Toman)."""
    key, name, homepage = "khanoumi", "خانومی", "https://www.khanoumi.com"
    supports_refresh = True
    API = "https://www.khanoumi.com/api/ntl/v1"

    def __init__(self):
        super().__init__()
        self._ut = str(uuid.uuid4())

    async def search(self, query: str) -> list[Candidate]:
        data = await self.get(
            f"{self.API}/products",
            params={"query": query, "page_size": 20, "ut": self._ut},
            headers={"Accept": "application/json"},
            expect_json=True,
        )
        items = ((((data or {}).get("data") or {}).get("products") or {}).get("items")) or []
        out = []
        for p in items:
            brand = p.get("brand") or {}
            price = p.get("effectivePrice") or p.get("basePrice")
            out.append(Candidate(
                site=self.key,
                external_id=p["slug"],
                title=f"{p.get('nameFa') or ''} {p.get('nameEn') or ''}".strip(),
                url=f"{self.homepage}/products/{p['slug']}",
                price=int(price) if price else None,
                regular_price=int(p.get("basePrice") or price or 0) or None,
                in_stock=bool(p.get("isSalable") and p.get("hasStock") and price),
                image=p.get("imageUrl"),
                brand=brand.get("nameFa") or brand.get("nameEn"),
            ))
        return out

    async def _detail(self, slug: str) -> Candidate | None:
        data = await self.get(f"{self.API}/products/slug/{slug}", headers={"Accept": "application/json"}, expect_json=True)
        p = (data or {}).get("data")
        if not p:
            return None
        brand = p.get("brand") or {}
        variants = []
        for v in p.get("variants") or []:
            if v.get("salesPrice"):
                variants.append({
                    "seller": v.get("vendorDisplayName") or "خانومی",
                    "variant": (v.get("color") or {}).get("nameFa") if isinstance(v.get("color"), dict) else v.get("color"),
                    "price": int(v["salesPrice"]),
                    "regular_price": int(v.get("basePrice") or v["salesPrice"]),
                    "in_stock": bool(v.get("isSalable")),
                })
        cand = Candidate(
            site=self.key, external_id=p["slug"],
            title=f"{p.get('nameFa') or ''} {p.get('nameEn') or ''}".strip(),
            url=f"{self.homepage}/products/{p['slug']}",
            price=int(p["salesPrice"]) if p.get("salesPrice") else None,
            regular_price=int(p.get("basePrice") or p.get("salesPrice") or 0) or None,
            in_stock=bool(p.get("isSalable")) and not p.get("isDiscontinued"),
            image=p.get("mainImageUrl"), brand=brand.get("nameFa") or brand.get("nameEn"),
        )
        if len(variants) > 1:
            cand.extra["sellers"] = sorted(variants, key=lambda v: v["price"])
        return cand

    async def refresh(self, external_id: str, url: str) -> Candidate | None:
        return await self._detail(external_id)

    async def from_url(self, url: str) -> Candidate | None:
        m = re.search(r"/products/([^/?#]+)", unquote(url))
        return await self._detail(m.group(1)) if m else None


class RojashopSource(Source):
    """Rojashop: server-rendered search page (Toman)."""
    key, name, homepage = "rojashop", "رژا", "https://rojashop.com"
    supports_refresh = True

    def _cards(self, page: str) -> list[Candidate]:
        soup = BeautifulSoup(page, "lxml")
        out = []
        for card in soup.select("div.productct[data-id]"):
            a = card.select_one("a.productLink")
            title = card.select_one(".ptitle")
            if not a or not title:
                continue
            sale = card.select_one(".price .sale-price")
            reg = card.select_one(".price .regular-price")
            only = card.select_one(".price")
            price = tn.parse_price(sale.get_text()) if sale else (tn.parse_price(only.get_text()) if only else None)
            regular = tn.parse_price(reg.get_text()) if reg else price
            text = card.get_text(" ")
            img = card.select_one("img")
            out.append(Candidate(
                site=self.key, external_id=card["data-id"], title=strip_tags(title.get_text()),
                url=a.get("href") or "", price=price, regular_price=regular,
                in_stock=bool(price) and "ناموجود" not in text,
                image=(img.get("data-src") or img.get("src")) if img else None,
                extra={"variants": len(card.select(".childs li"))} if card.select(".childs li") else {},
            ))
        return out

    async def search(self, query: str) -> list[Candidate]:
        page = await self.get(f"{self.homepage}/search", params={"term": query})
        return self._cards(page) if page else []

    async def _product_page(self, url: str, external_id: str | None = None) -> Candidate | None:
        page = await self.get(url)
        if not page:
            return None
        for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            for item in data if isinstance(data, list) else [data]:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    offers = item.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = tn.parse_price(offers.get("price") or offers.get("lowPrice"))
                    if price and (offers.get("priceCurrency") or "").upper() == "IRR":
                        price //= 10
                    m = re.search(r'data-id="(\d+)"', page)
                    return Candidate(
                        site=self.key, external_id=external_id or (m.group(1) if m else url),
                        title=item.get("name") or "", url=url, price=price, regular_price=price,
                        in_stock="InStock" in str(offers.get("availability", "")) and bool(price),
                        image=item.get("image") if isinstance(item.get("image"), str) else None,
                    )
        return None

    async def refresh(self, external_id: str, url: str) -> Candidate | None:
        return await self._product_page(url, external_id) if url else None

    async def from_url(self, url: str) -> Candidate | None:
        return await self._product_page(url)


class ElanzaSource(Source):
    """Elanza: JSON search API (prices displayed as Toman on the site)."""
    key, name, homepage = "elanza", "النزا", "https://elanza.com"
    API = "https://api.elanza.com"

    async def search(self, query: str) -> list[Candidate]:
        data = await self.get(f"{self.API}/search", params={"search": query, "page": 1}, expect_json=True)
        rows = (((((data or {}).get("data") or {}).get("catalogServiceData") or {}).get("searchResults") or {}).get("data")) or []
        out = []
        for r in rows[:24]:
            p = r.get("product") or {}
            if not p.get("unique_id"):
                continue
            price = r.get("sale_price") or r.get("price") or None
            brand = p.get("brand")
            out.append(Candidate(
                site=self.key, external_id=p["unique_id"], title=p.get("title") or "",
                url=f"{self.homepage}/product/{p['unique_id']}/{p.get('slug') or ''}",
                price=int(price) if price else None,
                regular_price=int(r.get("price") or price or 0) or None,
                in_stock=bool(price) and (r.get("quantity") or 0) > 0,
                seller=(r.get("seller") or {}).get("title") if isinstance(r.get("seller"), dict) else None,
                image=p.get("image"),
                brand=(brand.get("title") if isinstance(brand, dict) else None),
            ))
        return out
