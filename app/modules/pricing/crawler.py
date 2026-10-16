"""One crawl = sync our own catalog, then search every competitor for every product."""
import asyncio
import json
import re
import logging
import traceback

from . import config, db, sources
from . import textnorm as tn
from rapidfuzz import fuzz

from .matching import GENERIC, Candidate, Matcher, Own, skeleton, type_phrase
from .sources.woocommerce import WooCommerceSource, own_product_row

log = logging.getLogger("crawler")

MAX_OFFERS_PER_SITE = 8      # keep the best N listings per product per site
MAX_ENRICH_PER_SITE = 3      # detail requests per product per marketplace (all sellers)

_running = asyncio.Lock()
progress: dict = {}          # live progress for the UI


def is_running() -> bool:
    return _running.locked()


def enabled_sites() -> list[str]:
    disabled = set(db.get_setting("disabled_sites", []) or [])
    return [k for k, _, _ in sources.COMPETITORS if k not in disabled]


# ---------------------------------------------------------------- own catalog
async def sync_own_catalog(crawl_id: int) -> int:
    async with WooCommerceSource("own", config.OWN_SITE_NAME, config.OWN_SITE_URL) as own:
        raw = await own.all_products(config.PRODUCT_LIMIT)
    if not raw:
        raise RuntimeError(
            f"هیچ محصولی از {config.OWN_SITE_URL} دریافت نشد. "
            "سرور باید به سایت دسترسی داشته باشد (IP ایران) و Store API ووکامرس فعال باشد."
        )
    ts = db.now_iso()
    seen = []
    with db.tx() as c:
        for p in raw:
            row = own_product_row(p)
            if not row["name"]:
                continue
            seen.append(row["id"])
            c.execute(
                """INSERT INTO products(id, name, slug, sku, permalink, image, brand, size_hint, categories, price,
                       regular_price, in_stock, active, updated_at)
                   VALUES(:id, :name, :slug, :sku, :permalink, :image, :brand, :size_hint, :categories, :price,
                       :regular_price, :in_stock, 1, :ts)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, slug=excluded.slug, sku=excluded.sku,
                       permalink=excluded.permalink, image=excluded.image, brand=excluded.brand,
                       size_hint=excluded.size_hint,
                       categories=excluded.categories, price=excluded.price, regular_price=excluded.regular_price,
                       in_stock=excluded.in_stock, active=1, updated_at=excluded.updated_at""",
                {**row, "categories": json.dumps(row["categories"], ensure_ascii=False), "ts": ts},
            )
            c.execute(
                "INSERT OR REPLACE INTO my_prices(product_id, crawl_id, price, regular_price, in_stock, ts) "
                "VALUES(?,?,?,?,?,?)",
                (row["id"], crawl_id, row["price"], row["regular_price"], row["in_stock"], ts),
            )
        if seen and not config.PRODUCT_LIMIT:
            marks = ",".join("?" * len(seen))
            c.execute(f"UPDATE products SET active=0 WHERE id NOT IN ({marks})", seen)
    return len(seen)


# ---------------------------------------------------------------- competitor search
def main_title(name: str, brand: str | None) -> str:
    """Title without descriptive tails after '|' (kept only when the tail names the brand)."""
    parts = [x.strip() for x in name.split("|")]
    keep = [parts[0]]
    forms = tn.brand_forms(brand) if brand else set()
    for extra in parts[1:]:
        if forms and any(tn.contains_phrase(tn.normalize(extra), f) for f in forms):
            keep.append(extra)
    return " ".join(keep)


def search_queries(product: dict) -> list[str]:
    """Most specific query first; the rest only run when nothing matched well.

    Iranian shops usually put the English model name in the title, so an English
    "brand + model" query is tried first, then Persian "type + brand" queries."""
    if product.get("search_query"):
        return [product["search_query"]]
    brand = product.get("brand")
    title = main_title(product["name"], brand)
    core = tn.core_tokens(title)
    forms = tn.brand_forms(brand) if brand else set()
    brand_words = {w for f in forms for w in f.split()}
    latin_brand = next((f for f in sorted(forms, key=len) if re.fullmatch(r"[a-z0-9 .&]+", f)), "")
    fa_brand = next((f for f in sorted(forms, key=len, reverse=True)
                     if re.search(r"[\u0600-\u06FF]", f) and tn.contains_phrase(tn.normalize(title), f)), "") \
        or next((f for f in sorted(forms, key=len) if re.search(r"[\u0600-\u06FF]", f)), "")
    distinctive = [t for t in core if t not in GENERIC and t not in brand_words and not t.isdigit() and len(t) > 1]
    latin_model = [t for t in distinctive if re.fullmatch(r"[a-z0-9.]+", t) and not re.fullmatch(r"[\d.]+", t)]
    kind = type_phrase(title) or (core[0] if core else "")
    fa_model = [t for t in distinctive if re.search(r"[\u0600-\u06FF]", t) and t not in kind.split()]

    queries = []
    if latin_model:
        queries.append(" ".join(([latin_brand] if latin_brand else []) + latin_model[:3]))
    if kind and (fa_brand or latin_brand):
        queries.append(" ".join([kind, fa_brand or latin_brand] + fa_model[:1]))
        queries.append(f"{kind} {fa_brand or latin_brand}")
    queries.append(" ".join(core[:6]))
    if latin_model and latin_brand and len(latin_model) > 1:
        queries.append(" ".join(latin_model[:3]))
    # Last resort: the brand alone. Some shops only match single words or Persian titles
    # (Rojashop, small WooCommerce stores); the query is cached per run, so a brand costs one request.
    queries += [b for b in (fa_brand, latin_brand) if b]
    out = []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if re.search(r"[\u0600-\u06FF]", q):  # shops write "بی بی کرم", normalize() made it "bb کرم"
            q = re.sub(r"\bbb\b", "بی بی", re.sub(r"\bcc\b", "سی سی", q))
        if q and q not in out:
            out.append(q)
    return out


def match_name(product: dict) -> str:
    name = main_title(product["name"], product.get("brand"))
    if product.get("size_hint") and not tn.sizes(name):
        name = f"{name} {product['size_hint']}"
    return name


def learn_brands(products: list[dict]) -> None:
    """Pick up Persian brand spellings from your own titles, e.g. 'دروهو (Drohoo)'."""
    for p in products:
        brand = p.get("brand")
        if not brand:
            continue
        alias = tn.persian_brand_in_title(p["name"], brand)
        if not alias and re.search(r"[A-Za-z]", brand):
            # a Persian word in the title that sounds like the English brand: "لایتنس" ~ "Lightness"
            words = [w for w in tn.normalize(p["name"]).split() if re.search(r"[\u0600-\u06FF]", w)]
            n = len(brand.split())
            target = "".join(skeleton(w) for w in tn.normalize(brand).split())
            for i in range(len(words) - n + 1):
                cand = " ".join(words[i:i + n])
                sk = "".join(skeleton(w) for w in words[i:i + n])
                if len(target) >= 3 and fuzz.ratio(sk, target) >= 85:
                    alias = cand
                    break
        if alias:
            tn.learn_brand(brand, alias)


def _is_own_listing(c: Candidate) -> bool:
    own_name = tn.normalize(config.OWN_SITE_NAME)
    own_host = config.OWN_SITE_URL.split("//")[-1].split("/")[0].replace("www.", "")
    seller = tn.normalize(c.seller or "")
    return bool((own_name and own_name in seller) or (own_host and own_host in (c.url or "")))


def _save_offer(c, product_id: int, cand: Candidate, score: float, reasons: list[str],
                crawl_id: int, ts: str, existing: dict | None) -> None:
    if existing:
        status = existing["status"]
        if status in ("auto", "pending"):
            status = "auto" if score >= config.MATCH_AUTO else "pending"
        c.execute(
            """UPDATE offers SET url=?, title=?, seller=?, image=?, score=?, status=?, reasons=?, price=?,
                   regular_price=?, in_stock=?, extra=?, last_seen=?, last_crawl_id=? WHERE id=?""",
            (cand.url, cand.title, cand.seller, cand.image, score, status, json.dumps(reasons, ensure_ascii=False),
             cand.price, cand.regular_price, int(cand.in_stock), json.dumps(cand.extra, ensure_ascii=False),
             ts, crawl_id, existing["id"]),
        )
        offer_id = existing["id"]
    else:
        status = "auto" if score >= config.MATCH_AUTO else "pending"
        cur = c.execute(
            """INSERT INTO offers(product_id, site, external_id, url, title, seller, image, score, status, reasons,
                   price, regular_price, in_stock, extra, first_seen, last_seen, last_crawl_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (product_id, cand.site, cand.external_id, cand.url, cand.title, cand.seller, cand.image, score, status,
             json.dumps(reasons, ensure_ascii=False), cand.price, cand.regular_price, int(cand.in_stock),
             json.dumps(cand.extra, ensure_ascii=False), ts, ts, crawl_id),
        )
        offer_id = cur.lastrowid
    c.execute(
        "INSERT OR REPLACE INTO offer_prices(offer_id, crawl_id, price, regular_price, in_stock, ts) VALUES(?,?,?,?,?,?)",
        (offer_id, crawl_id, cand.price, cand.regular_price, int(cand.in_stock), ts),
    )


def _tehran_time(iso: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(iso).astimezone(ZoneInfo(config.TIMEZONE)).strftime("%H:%M")


def cooldown_until(site_key: str) -> str | None:
    until = (db.get_setting("site_cooldown", {}) or {}).get(site_key)
    return until if until and until > db.now_iso() else None


def src_cls_cooldown(site_key: str) -> float:
    return getattr(sources.make(site_key), "cooldown_hours", 0) or 0


def _set_cooldown(site_key: str, hours: float) -> None:
    from datetime import datetime, timedelta, timezone
    cd = db.get_setting("site_cooldown", {}) or {}
    if hours:
        cd[site_key] = (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()
    else:
        cd.pop(site_key, None)
    db.set_setting("site_cooldown", cd)


async def crawl_site(site_key: str, products: list[dict], matcher: Matcher, crawl_id: int) -> None:
    started = db.now_iso()
    until = cooldown_until(site_key)
    if until:
        with db.tx() as c:
            c.execute(
                """INSERT OR REPLACE INTO site_runs(crawl_id, site, started_at, finished_at, status, last_error)
                   VALUES(?,?,?,?,'skipped',?)""",
                (crawl_id, site_key, started, started,
                 f"بعد از مسدود شدن، تا ساعت {_tehran_time(until)} استراحت می‌کند؛ قیمت‌های قبلی معتبر می‌مانند"),
            )
        return
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO site_runs(crawl_id, site, started_at, status) VALUES(?,?,?,'running')",
                  (crawl_id, site_key, started))
    stats = {"searched": 0, "found": 0, "errors": 0, "last_error": None}
    cache: dict[str, asyncio.Task] = {}   # shared per run, so "ریمل میبلین" is searched once for all products
    status = "ok"
    progress.setdefault("sites", {})[site_key] = {"done": 0, "total": len(products), "status": "running"}

    async def cached_search(src, query):
        if query not in cache:
            cache[query] = asyncio.ensure_future(src.search(query))
        return await cache[query]

    async def handle(src, product):
        own = Own(product["id"], match_name(product), product.get("brand"), product.get("sku"))
        known = {o["external_id"]: o for o in db.q(
            "SELECT * FROM offers WHERE product_id=? AND site=?", (product["id"], site_key))}
        scored: dict[str, tuple[float, list[str], Candidate]] = {}
        for query in search_queries(product)[:src.max_queries]:
            results = await cached_search(src, query)
            stats["searched"] += 1
            for cand in results:
                if not cand.external_id or _is_own_listing(cand):
                    continue
                prev = known.get(cand.external_id)
                if prev and prev["status"] == "rejected":
                    continue
                score, reasons = matcher.score(own, cand)
                if prev and prev["status"] == "confirmed":
                    score = max(score, prev["score"] or 0)
                if score >= config.MATCH_REVIEW or (prev and prev["status"] == "confirmed"):
                    if cand.external_id not in scored or scored[cand.external_id][0] < score:
                        scored[cand.external_id] = (score, reasons, cand)
            if any(s >= config.MATCH_AUTO for s, _, _ in scored.values()):
                break
        best = sorted(scored.values(), key=lambda x: -x[0])[:MAX_OFFERS_PER_SITE]

        # marketplaces: read every seller for the strongest matches
        if src.marketplace:
            for i, (score, reasons, cand) in enumerate(best[:MAX_ENRICH_PER_SITE]):
                if score >= config.MATCH_AUTO or known.get(cand.external_id, {}).get("status") == "confirmed":
                    try:
                        best[i] = (score, reasons, await src.enrich(cand))
                    except sources.SiteBlocked:
                        raise
                    except Exception as e:  # detail page failing is not fatal
                        log.debug("enrich failed %s %s", site_key, e)

        # confirmed / auto matches that did not show up in search: read them directly
        seen_ids = {c.external_id for _, _, c in best}
        refreshed = []
        if src.supports_refresh:
            for ext_id, o in known.items():
                if o["status"] in ("confirmed", "auto") and ext_id not in seen_ids:
                    try:
                        cand = await src.refresh(ext_id, o["url"])
                    except sources.SiteBlocked:
                        raise
                    except Exception:
                        cand = None
                    if not cand:
                        continue
                    if o["status"] == "confirmed":
                        refreshed.append((o["score"] or 0, json.loads(o["reasons"] or "[]"), cand))
                    else:  # re-judge automatic matches, so a matcher fix also clears old false positives
                        score, reasons = matcher.score(own, cand)
                        if score >= config.MATCH_REVIEW:
                            refreshed.append((score, reasons, cand))

        ts = db.now_iso()
        with db.tx() as c:
            for score, reasons, cand in best + refreshed:
                _save_offer(c, product["id"], cand, score, reasons, crawl_id, ts, known.get(cand.external_id))
        stats["found"] += len(best)

    try:
        async with sources.make(site_key) as src:
            batch = max(config.SITE_CONCURRENCY * 2, 2)
            for i in range(0, len(products), batch):
                chunk = products[i:i + batch]
                results = await asyncio.gather(*(handle(src, p) for p in chunk), return_exceptions=True)
                for r in results:
                    if isinstance(r, sources.SiteBlocked):
                        raise r
                    if isinstance(r, Exception):
                        stats["errors"] += 1
                        stats["last_error"] = f"{type(r).__name__}: {r}"[:300]
                        log.warning("%s: %s", site_key, stats["last_error"])
                progress["sites"][site_key]["done"] = min(i + batch, len(products))
                if stats["errors"] > 25 and stats["errors"] > (i + batch) * 0.6:
                    raise RuntimeError(f"too many errors: {stats['last_error']}")
        if stats["errors"]:
            status = "partial"
    except sources.SiteBlocked as e:
        status, stats["last_error"] = "blocked", str(e)
        cool = src_cls_cooldown(site_key)
        if cool:
            _set_cooldown(site_key, cool)
    except Exception as e:
        status, stats["last_error"] = "failed", f"{type(e).__name__}: {e}"[:300]
        log.error("site %s failed: %s", site_key, traceback.format_exc())
    progress["sites"][site_key]["status"] = status
    with db.tx() as c:
        c.execute(
            """UPDATE site_runs SET finished_at=?, status=?, searched=?, found=?, errors=?, last_error=?
               WHERE crawl_id=? AND site=?""",
            (db.now_iso(), status, stats["searched"], stats["found"], stats["errors"], stats["last_error"],
             crawl_id, site_key),
        )


async def run_crawl(trigger: str = "schedule", only_sites: list[str] | None = None,
                    product_ids: list[int] | None = None) -> int | None:
    if _running.locked():
        log.info("crawl already running, skipping")
        return None
    async with _running:
        with db.tx() as c:
            crawl_id = c.execute(
                "INSERT INTO crawls(started_at, status, trigger) VALUES(?, 'running', ?)", (db.now_iso(), trigger)
            ).lastrowid
        progress.clear()
        progress.update({"crawl_id": crawl_id, "stage": "catalog", "sites": {}})
        try:
            n = await sync_own_catalog(crawl_id)
            try:
                from .branding import refresh_branding
                await refresh_branding()
            except Exception as e:  # branding is cosmetic only
                log.info("branding refresh skipped: %s", e)
            products = db.q("SELECT * FROM products WHERE active=1 AND tracked=1 ORDER BY id")
            if product_ids:
                products = [p for p in products if p["id"] in set(product_ids)]
            learn_brands(db.q("SELECT name, brand FROM products WHERE active=1"))
            matcher = Matcher([main_title(p["name"], p["brand"]) for p in db.q("SELECT name, brand FROM products WHERE active=1")])
            progress["stage"] = "competitors"
            sites = [s for s in enabled_sites() if not only_sites or s in only_sites]
            await asyncio.gather(*(crawl_site(s, products, matcher, crawl_id) for s in sites))
            if not product_ids and not only_sites:
                progress["stage"] = "new_products"
                from .research import refresh_all
                await refresh_all()
            runs = db.q("SELECT site, status FROM site_runs WHERE crawl_id=?", (crawl_id,))
            stats = {"products": n, "sites": {r["site"]: r["status"] for r in runs}}
            with db.tx() as c:
                c.execute("UPDATE crawls SET finished_at=?, status='done', stats=? WHERE id=?",
                          (db.now_iso(), json.dumps(stats, ensure_ascii=False), crawl_id))
        except Exception as e:
            log.error("crawl failed: %s", traceback.format_exc())
            with db.tx() as c:
                c.execute("UPDATE crawls SET finished_at=?, status='failed', stats=? WHERE id=?",
                          (db.now_iso(), json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False), crawl_id))
        finally:
            progress["stage"] = "idle"
        return crawl_id
