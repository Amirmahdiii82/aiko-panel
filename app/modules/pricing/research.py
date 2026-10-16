"""Market research for a product you do not sell yet: find it at every competitor and suggest a price."""
import asyncio
import json
import logging
import statistics

from . import config, db, sources
from . import textnorm as tn
from .crawler import _is_own_listing, cooldown_until, enabled_sites, learn_brands, main_title, search_queries
from .insights import excluded_sites
from .matching import Matcher, Own

log = logging.getLogger("research")

MAX_PER_SITE = 10
SITE_TIMEOUT = 120
_tasks: set[asyncio.Task] = set()


def _row(np_id: int) -> dict | None:
    r = db.q1("SELECT * FROM new_products WHERE id=?", (np_id,))
    if r:
        for k, default in (("results", []), ("site_status", {}), ("choices", {})):
            r[k] = json.loads(r[k]) if r[k] else default
    return r


def _save(np_id: int, **fields) -> None:
    fields["updated_at"] = db.now_iso()
    for k in ("results", "site_status", "choices"):
        if k in fields:
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.tx() as c:
        c.execute(f"UPDATE new_products SET {cols} WHERE id=?", (*fields.values(), np_id))


def included(listing: dict, choices: dict, excluded: set[str]) -> bool:
    """Counted in the price suggestion: your choice wins; otherwise confident, in-stock, not an excluded site."""
    key = f"{listing['site']}:{listing['external_id']}"
    if key in choices:
        return bool(choices[key]) and bool(listing.get("price"))
    return listing["score"] >= config.MATCH_AUTO and listing["in_stock"] and bool(listing.get("price")) \
        and listing["site"] not in excluded


def round_price(v: float) -> int:
    """Shop-style price just below v: 2,153,060 -> 2,149,000; 345,678 -> 339,000."""
    if v >= 100_000:
        return max(int(v // 10_000 * 10_000 - 1_000), 1_000)
    return max(int(v // 1_000 * 1_000), 1_000)


def summarize(row: dict) -> dict:
    """Market numbers and the three pricing strategies, from the listings that are counted."""
    excluded = excluded_sites()
    per_site: dict[str, int] = {}
    for l in row["results"]:
        if included(l, row["choices"], excluded):
            per_site[l["site"]] = min(per_site.get(l["site"], l["price"]), l["price"])
    prices = sorted(per_site.values())
    out = {"n_sites": len(prices), "min": None, "median": None, "max": None, "strategies": [], "recommended": None,
           "floor": None, "cheapest_site": None}
    cost, margin = row.get("cost"), row.get("target_margin") or 0
    if cost:
        out["floor"] = int(round(cost / (1 - min(margin, 90) / 100)))
    if not prices:
        return out
    q1 = statistics.quantiles(prices, n=4, method="inclusive")[0] if len(prices) >= 3 \
        else (prices[0] + statistics.median(prices)) / 2
    out.update(min=prices[0], median=int(statistics.median(prices)), max=prices[-1],
               cheapest_site=min(per_site, key=per_site.get))
    strategies = [
        ("cheapest", "ارزان‌ترین بازار", "کمی زیر ارزان‌ترین رقیب؛ برای فروش سریع و جذب مشتری", round_price(prices[0] * 0.99)),
        ("competitive", "رقابتی", "بین ارزان‌ترین و میانه بازار؛ تعادل فروش و سود", round_price(q1)),
        ("market", "هم‌سطح بازار", "حدود میانه قیمت رقبا؛ سود بیشتر، فروش کندتر", round_price(statistics.median(prices))),
    ]
    for key, label, hint, price in strategies:
        s = {"key": key, "label": label, "hint": hint, "price": price,
             "rank": 1 + sum(1 for p in prices if p < price), "of": len(prices) + 1}
        if cost:
            s["profit"] = price - cost
            s["margin"] = round((price - cost) / price * 100, 1)
            s["ok"] = s["margin"] >= margin
        out["strategies"].append(s)
    if cost:
        ok = [s for s in out["strategies"] if s["ok"]]
        out["recommended"] = ok[0]["key"] if ok else None
    else:
        out["recommended"] = "competitive"
    return out


async def _search_site(site: str, product: dict, matcher: Matcher, own: Own) -> tuple[list[dict], dict]:
    found: dict[str, dict] = {}
    async with sources.make(site) as src:
        for query in search_queries(product)[:src.max_queries]:
            for cand in await src.search(query):
                if not cand.external_id or not cand.price or _is_own_listing(cand):
                    continue
                score, reasons = matcher.score(own, cand)
                if score < config.MATCH_REVIEW:
                    continue
                if cand.external_id not in found or found[cand.external_id]["score"] < score:
                    found[cand.external_id] = {
                        "site": site, "external_id": cand.external_id, "title": cand.title, "url": cand.url,
                        "price": cand.price, "regular_price": cand.regular_price, "in_stock": cand.in_stock,
                        "seller": cand.seller, "image": cand.image, "score": score, "reasons": reasons,
                        "extra": cand.extra, "_cand": cand,
                    }
            if any(f["score"] >= config.MATCH_AUTO for f in found.values()):
                break
        best = sorted(found.values(), key=lambda f: -f["score"])[:MAX_PER_SITE]
        if src.marketplace:
            for f in best[:2]:
                if f["score"] >= config.MATCH_AUTO:
                    try:
                        c = await src.enrich(f["_cand"])
                        f.update(price=c.price, regular_price=c.regular_price, in_stock=c.in_stock,
                                 seller=c.seller, extra=c.extra)
                    except sources.SiteBlocked:
                        raise
                    except Exception:
                        pass
    for f in best:
        f.pop("_cand", None)
    return best, {"status": "ok", "found": len(best)}


async def run(np_id: int) -> None:
    row = _row(np_id)
    if not row:
        return
    catalog = db.q("SELECT name, brand FROM products WHERE active=1")
    learn_brands(catalog + [{"name": row["name"], "brand": row["brand"]}])
    brand = row["brand"] or tn.detect_brand(row["name"])
    product = {"id": -np_id, "name": row["name"], "brand": brand, "search_query": row["search_query"]}
    matcher = Matcher([main_title(p["name"], p["brand"]) for p in catalog] + [row["name"]])
    own = Own(-np_id, main_title(row["name"], brand), brand)

    sites = [s for s in enabled_sites() if not cooldown_until(s)]
    status = {s: {"status": "running", "found": 0} for s in sites}
    results: list[dict] = []
    _save(np_id, status="running", site_status=status)

    async def one(site):
        try:
            found, st = await asyncio.wait_for(_search_site(site, product, matcher, own), SITE_TIMEOUT)
        except sources.SiteBlocked as e:
            found, st = [], {"status": "blocked", "found": 0, "error": str(e)}
        except asyncio.TimeoutError:
            found, st = [], {"status": "failed", "found": 0, "error": "زمان جستجو تمام شد"}
        except Exception as e:
            found, st = [], {"status": "failed", "found": 0, "error": f"{type(e).__name__}: {e}"[:200]}
        results.extend(found)
        status[site] = st
        _save(np_id, results=sorted(results, key=lambda r: (r["price"] or 0)), site_status=status)

    await asyncio.gather(*(one(s) for s in sites))
    _save(np_id, status="done", results=sorted(results, key=lambda r: (r["price"] or 0)), site_status=status)


def start(np_id: int) -> None:
    task = asyncio.create_task(run(np_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def refresh_all() -> None:
    """Called after each scheduled crawl so saved research stays current."""
    for r in db.q("SELECT id FROM new_products ORDER BY id"):
        try:
            await run(r["id"])
        except Exception as e:
            log.warning("new product %s refresh failed: %s", r["id"], e)
