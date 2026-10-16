"""Digikala: public JSON API. Prices come in Rial and are converted to Toman."""
import re

from ..matching import Candidate
from .base import Source

API = "https://api.digikala.com"


def _rial(v) -> int | None:
    return int(v) // 10 if v else None


def _real_brand(b: str | None) -> str | None:
    return None if not b or b.strip() in ("متفرقه", "نامشخص", "generic", "Generic") else b


class DigikalaSource(Source):
    key, name, homepage = "digikala", "دیجی‌کالا", "https://www.digikala.com"
    marketplace = True
    supports_refresh = True

    def _from_search(self, p: dict) -> Candidate:
        dv = p.get("default_variant") or {}
        pr = dv.get("price") or {} if isinstance(dv, dict) else {}
        price = _rial(pr.get("selling_price"))
        images = (p.get("images") or {}).get("main") or {}
        return Candidate(
            site=self.key,
            external_id=str(p["id"]),
            title=(p.get("title_fa") or "") + (f" {p['title_en']}" if p.get("title_en") else ""),
            url=self.homepage + ((p.get("url") or {}).get("uri") or f"/product/dkp-{p['id']}/"),
            price=price,
            regular_price=_rial(pr.get("rrp_price")) or price,
            in_stock=p.get("status") == "marketable" and bool(price),
            seller=((dv.get("seller") or {}).get("title")) if isinstance(dv, dict) else None,
            image=(images.get("url") or [None])[0],
            brand=_real_brand((p.get("data_layer") or {}).get("brand")),
        )

    async def search(self, query: str) -> list[Candidate]:
        data = await self.get(f"{API}/v1/search/", params={"q": query, "page": 1}, expect_json=True)
        products = ((data or {}).get("data") or {}).get("products") or []
        return [self._from_search(p) for p in products[:20]]

    async def _detail(self, dkp: str) -> Candidate | None:
        data = await self.get(f"{API}/v2/product/{dkp}/", expect_json=True)
        p = ((data or {}).get("data") or {}).get("product")
        if not p or not p.get("id"):
            return None
        cand = self._from_search(p)
        sellers = []
        for v in p.get("variants") or []:
            vp = v.get("price") or {}
            sellers.append({
                "seller": (v.get("seller") or {}).get("title"),
                "price": _rial(vp.get("selling_price")),
                "regular_price": _rial(vp.get("rrp_price")),
                "variant": (v.get("color") or {}).get("title") or (v.get("size") or {}).get("title"),
            })
        sellers = [s for s in sellers if s["price"]]
        if sellers:
            sellers.sort(key=lambda s: s["price"])
            cand.extra["sellers"] = sellers
            cand.price = sellers[0]["price"]
            cand.regular_price = sellers[0]["regular_price"] or cand.price
            cand.seller = sellers[0]["seller"]
            cand.in_stock = True
        else:
            cand.in_stock = False
        return cand

    async def enrich(self, cand: Candidate) -> Candidate:
        return await self._detail(cand.external_id) or cand

    async def refresh(self, external_id: str, url: str) -> Candidate | None:
        return await self._detail(external_id)

    async def from_url(self, url: str) -> Candidate | None:
        m = re.search(r"dkp-(\d+)", url)
        return await self._detail(m.group(1)) if m else None
