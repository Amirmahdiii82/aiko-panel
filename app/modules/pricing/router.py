"""Price checker HTTP API (mounted at /api/pricing)."""
import csv
import io
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...core import auth
from . import config, crawler, db, insights, research, schedule, sources
from .matching import Matcher, Own
from .runner import start_crawl

log = logging.getLogger("aiko.pricing")
router = APIRouter()
Viewer = Depends(auth.require("pricing"))
Editor = Depends(auth.require("pricing", "editor"))


# ------------------------------------------------------------------ meta & status
@router.get("/meta", dependencies=[Viewer])
def meta():
    disabled = set(db.get_setting("disabled_sites", []) or [])
    excluded = insights.excluded_sites()
    return {
        "own": {"name": config.OWN_SITE_NAME, "url": config.own_site_url()},
        "branding": db.get_setting("branding", {}) or {},
        "sites": [{"key": k, "name": n, "url": sources.HOMEPAGES.get(k), "enabled": k not in disabled,
                   "in_stats": k not in excluded, "marketplace": k in sources.MARKETPLACES} for k, n, _ in sources.COMPETITORS],
        "schedule": schedule.times(),
        "timezone": config.TIMEZONE,
        "next_run": schedule.next_run(),
        "running": crawler.is_running(),
        "progress": crawler.progress,
        "thresholds": {"auto": config.MATCH_AUTO, "review": config.MATCH_REVIEW},
        "positions": insights.POSITIONS,
    }


class ScheduleBody(BaseModel):
    times: list[str] = []


@router.put("/schedule", dependencies=[Editor])
def save_schedule(body: ScheduleBody):
    """The daily timetable of automatic crawls (Tehran time)."""
    try:
        saved = schedule.save(body.times)
    except schedule.ScheduleError as exc:
        raise HTTPException(400, str(exc))
    return {"schedule": saved, "next_run": schedule.next_run()}


@router.get("/summary", dependencies=[Viewer])
def summary():
    return insights.summary()


# ------------------------------------------------------------------ products
@router.get("/products", dependencies=[Viewer])
def products(q: str = "", position: str = "", brand: str = "", site: str = "", opportunity: str = "",
             sort: str = "gap", include_untracked: bool = False):
    from .textnorm import normalize
    rows = insights.analyse_all(include_untracked=include_untracked)
    if q:
        nq = normalize(q)
        rows = [r for r in rows if nq in normalize(r["name"]) or nq in normalize(r["brand"] or "") or nq == str(r["id"])]
    if position:
        rows = [r for r in rows if r["position"] in position.split(",")]
    if brand:
        rows = [r for r in rows if (r["brand"] or "بدون برند") == brand]
    if site:
        rows = [r for r in rows if any(s["site"] == site for s in r["sites"])]
    if opportunity:
        rows = [r for r in rows if r["opportunity"] == opportunity]
    keys = {
        "gap": lambda r: (r["gap_min_pct"] is None, -(r["gap_min_pct"] or 0)),
        "gap_asc": lambda r: (r["gap_min_pct"] is None, r["gap_min_pct"] or 0),
        "name": lambda r: r["name"],
        "price": lambda r: -(r["my_price"] or 0),
        "sites": lambda r: -r["n_sites"],
        "impact": lambda r: -(r["impact"] or 0),
    }
    rows.sort(key=keys.get(sort, keys["gap"]))
    brands = sorted({r["brand"] or "بدون برند" for r in insights.analyse_all()})
    return {"items": rows, "total": len(rows), "brands": brands}


@router.get("/products/{pid}", dependencies=[Viewer])
def product(pid: int):
    p = db.q1("SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404)
    offers = db.q("SELECT * FROM offers WHERE product_id=? ORDER BY site, status='rejected', price", (pid,))
    cutoff, reads = insights._cutoff(), insights.site_reads()
    analysis = insights.analyse_product(p, [o for o in offers if o["status"] != "rejected"], cutoff, reads=reads)
    current = {o["id"] for o in insights.current_offers(offers, cutoff, reads)}
    for o in offers:
        o["reasons"] = json.loads(o["reasons"] or "[]")
        o["extra"] = json.loads(o["extra"] or "{}")
        o["pack"] = insights.pack_size(o["title"])
        unit = insights.unit_price(o, p["name"])
        o["unit_price"] = unit if unit != o["price"] else None
        o["current"] = o["id"] in current
        o["fresh"] = o["current"] and (o["last_seen"] or "") >= cutoff
        o["counted"] = o["current"] and insights._offer_ok({**o, "price": unit}, p["price"])
    return {
        "product": {**p, "categories": json.loads(p["categories"] or "[]")},
        "analysis": analysis,
        "offers": offers,
        "history": insights.product_history(pid),
        "changes": insights.recent_changes(limit=20, product_id=pid),
        "site_names": sources.SITE_NAMES,
    }


class ProductPatch(BaseModel):
    tracked: bool | None = None
    search_query: str | None = None


@router.patch("/products/{pid}", dependencies=[Editor])
def patch_product(pid: int, body: ProductPatch):
    with db.tx() as c:
        if body.tracked is not None:
            c.execute("UPDATE products SET tracked=? WHERE id=?", (int(body.tracked), pid))
        if body.search_query is not None:
            c.execute("UPDATE products SET search_query=? WHERE id=?", (body.search_query.strip() or None, pid))
    return {"ok": True}


# ------------------------------------------------------------------ matching review
class StatusBody(BaseModel):
    status: str


@router.post("/offers/{oid}/status", dependencies=[Editor])
def set_offer_status(oid: int, body: StatusBody):
    if body.status not in ("confirmed", "rejected", "pending"):
        raise HTTPException(400, "invalid status")
    with db.tx() as c:
        c.execute("UPDATE offers SET status=? WHERE id=?", (body.status, oid))
    return {"ok": True}


@router.get("/review", dependencies=[Viewer])
def review(limit: int = 50, site: str = ""):
    where, params = "o.status='pending'", []
    if site:
        where += " AND o.site=?"
        params.append(site)
    rows = db.q(f"""SELECT o.*, p.name product_name, p.image product_image, p.price my_price, p.brand product_brand
                    FROM offers o JOIN products p ON p.id=o.product_id
                    WHERE {where} AND p.active=1 ORDER BY o.score DESC LIMIT ?""", (*params, limit))
    for r in rows:
        r["reasons"] = json.loads(r["reasons"] or "[]")
        r["extra"] = json.loads(r["extra"] or "{}")
    total = db.q1("SELECT COUNT(*) n FROM offers o JOIN products p ON p.id=o.product_id WHERE o.status='pending' AND p.active=1")
    return {"items": rows, "total": total["n"]}


class ManualBody(BaseModel):
    url: str


@router.post("/products/{pid}/manual", dependencies=[Editor])
async def manual_match(pid: int, body: ManualBody):
    """Paste a competitor product URL to link it to one of your products."""
    p = db.q1("SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404)
    host = urlparse(body.url.strip()).netloc.replace("www.", "")
    site = next((k for k, u in sources.HOMEPAGES.items() if urlparse(u).netloc.replace("www.", "") == host), None)
    if not site:
        raise HTTPException(400, "این دامنه جزو رقبای تعریف‌شده نیست")
    async with sources.make(site) as src:
        cand = await src.from_url(body.url.strip())
        if cand and src.marketplace:
            cand = await src.enrich(cand)
    if not cand:
        raise HTTPException(422, "خواندن این لینک برای این سایت پشتیبانی نمی‌شود یا محصول پیدا نشد")
    score, reasons = Matcher([p["name"]]).score(Own(p["id"], crawler.match_name(p), p["brand"], p["sku"]), cand)
    last = db.q1("SELECT MAX(id) id FROM crawls")["id"] or 0
    existing = db.q1("SELECT * FROM offers WHERE product_id=? AND site=? AND external_id=?", (pid, site, cand.external_id))
    with db.tx() as c:
        crawler._save_offer(c, pid, cand, score, ["افزوده‌شده دستی", *reasons], last, db.now_iso(), existing)
        c.execute("UPDATE offers SET status='confirmed' WHERE product_id=? AND site=? AND external_id=?",
                  (pid, site, cand.external_id))
    return {"ok": True, "title": cand.title, "price": cand.price}


# ------------------------------------------------------------------ pricing a new product
class NewProductBody(BaseModel):
    name: str
    brand: str | None = None
    cost: int | None = None
    target_margin: float | None = None
    search_query: str | None = None


class NewProductPatch(BaseModel):
    name: str | None = None
    brand: str | None = None
    cost: int | None = None
    target_margin: float | None = None
    search_query: str | None = None
    choices: dict[str, bool] | None = None


def _new_product_out(r: dict) -> dict:
    return {**r, "summary": research.summarize(r)}


@router.get("/newproducts", dependencies=[Viewer])
def new_products():
    rows = [research._row(r["id"]) for r in db.q("SELECT id FROM new_products ORDER BY id DESC")]
    out = []
    for r in rows:
        item = _new_product_out(r)
        item.pop("results")
        out.append(item)
    return {"items": out}


@router.post("/newproducts", dependencies=[Editor])
async def create_new_product(body: NewProductBody):
    name = body.name.strip()
    if len(name) < 3:
        raise HTTPException(400, "نام محصول را کامل‌تر بنویسید")
    now = db.now_iso()
    with db.tx() as c:
        np_id = c.execute(
            """INSERT INTO new_products(name, brand, cost, target_margin, search_query, status, created_at, updated_at)
               VALUES(?,?,?,?,?,'running',?,?)""",
            (name, (body.brand or "").strip() or None, body.cost, body.target_margin or 25,
             (body.search_query or "").strip() or None, now, now),
        ).lastrowid
    research.start(np_id)
    return {"id": np_id}


@router.get("/newproducts/{np_id}", dependencies=[Viewer])
def new_product(np_id: int):
    r = research._row(np_id)
    if not r:
        raise HTTPException(404)
    return {**_new_product_out(r), "site_names": sources.SITE_NAMES,
            "excluded_sites": sorted(insights.excluded_sites()), "auto": config.MATCH_AUTO}


@router.patch("/newproducts/{np_id}", dependencies=[Editor])
def patch_new_product(np_id: int, body: NewProductPatch):
    r = research._row(np_id)
    if not r:
        raise HTTPException(404)
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "choices"}
    for k in ("brand", "search_query", "name"):
        if k in fields:
            fields[k] = (fields[k] or "").strip() or None
    if body.choices is not None:
        fields["choices"] = {**r["choices"], **body.choices}
    if fields:
        research._save(np_id, **fields)
    return new_product(np_id)


@router.post("/newproducts/{np_id}/refresh", dependencies=[Editor])
def refresh_new_product(np_id: int):
    r = research._row(np_id)
    if not r:
        raise HTTPException(404)
    if r["status"] == "running":
        raise HTTPException(409, "جستجوی این محصول در حال اجراست")
    research.start(np_id)
    return {"ok": True}


@router.delete("/newproducts/{np_id}", dependencies=[Editor])
def delete_new_product(np_id: int):
    with db.tx() as c:
        c.execute("DELETE FROM new_products WHERE id=?", (np_id,))
    return {"ok": True}


# ------------------------------------------------------------------ crawl control
class CrawlBody(BaseModel):
    sites: list[str] | None = None
    product_ids: list[int] | None = None


@router.post("/crawl", dependencies=[Editor])
async def crawl_now(body: CrawlBody | None = None):
    body = body or CrawlBody()
    for site in body.sites or []:
        crawler._set_cooldown(site, 0)
    if not start_crawl("manual", only_sites=body.sites, product_ids=body.product_ids):
        raise HTTPException(409, "یک بروزرسانی در حال اجراست")
    return {"ok": True}


@router.get("/crawls", dependencies=[Viewer])
def crawls(limit: int = 20):
    rows = db.q("SELECT * FROM crawls ORDER BY id DESC LIMIT ?", (limit,))
    runs = db.q(f"SELECT * FROM site_runs WHERE crawl_id IN ({','.join('?' * len(rows)) or 'NULL'})",
                [r["id"] for r in rows])
    for r in rows:
        r["stats"] = json.loads(r["stats"] or "{}")
        r["sites"] = [s for s in runs if s["crawl_id"] == r["id"]]
    return {"items": rows}


class SiteBody(BaseModel):
    enabled: bool | None = None      # crawl this site at all
    in_stats: bool | None = None     # count it in index / rank / recommendations


@router.post("/sites/{key}", dependencies=[Editor])
def toggle_site(key: str, body: SiteBody):
    for setting, value in (("disabled_sites", body.enabled), ("stats_excluded_sites", body.in_stats)):
        if value is None:
            continue
        current = set(db.get_setting(setting, []) or [])
        (current.discard if value else current.add)(key)
        db.set_setting(setting, sorted(current))
    return {"ok": True}


@router.get("/export.csv", dependencies=[Viewer])
def export_csv():
    rows = insights.analyse_all()
    buf = io.StringIO()
    buf.write("﻿")  # Excel-friendly UTF-8
    w = csv.writer(buf)
    names = sources.SITE_NAMES
    w.writerow(["شناسه", "محصول", "برند", "قیمت من (تومان)", "ارزان‌ترین رقیب", "سایت ارزان‌ترین", "میانه بازار",
                "اختلاف با ارزان‌ترین ٪", "شاخص قیمت", "رتبه", "وضعیت", "قیمت پیشنهادی", "تعداد سایت‌ها",
                *[names[k] for k, _, _ in sources.COMPETITORS]])
    for r in rows:
        per_site = {s["site"]: s["price"] for s in r["sites"]}
        w.writerow([r["id"], r["name"], r["brand"] or "", r["my_price"] or "", r["min"] or "",
                    names.get(r["cheapest_site"], "") if r["cheapest_site"] else "", r["median"] or "",
                    r["gap_min_pct"] if r["gap_min_pct"] is not None else "", r["index"] or "", r["rank"] or "",
                    insights.POSITIONS.get(r["position"], ""), r["suggested_price"] or "", r["n_sites"],
                    *[per_site.get(k, "") for k, _, _ in sources.COMPETITORS]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=price-comparison.csv"})
