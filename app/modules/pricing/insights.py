"""Turns raw offers into answers: where am I expensive, where can I earn more, what changed."""
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import db, sources
from . import textnorm as tn

STALE_HOURS = 30          # two crawls a day; tolerate one missed run
MAX_AGE_DAYS = 14         # older than this a price says nothing about today's market
CLOSE_PCT = 3.0           # within 3% of the cheapest = competitive
FAR_PCT = 10.0            # more than 10% above the cheapest = at risk
HEADROOM_PCT = 5.0        # cheapest by more than 5% = room to raise
SANITY_LOW, SANITY_HIGH = 0.5, 2.0   # auto matches outside this band vs. my price are suspicious
# a confirmed listing is the same product, but at 5x our price it is another market (imported original, gift box...)
CONFIRMED_LOW, CONFIRMED_HIGH = 0.4, 2.5
MAX_PACK = 12             # "بسته ۷۰ عددی" pads are the product itself, not a multipack

POSITIONS = {
    "cheapest": "ارزان‌ترین",
    "close": "رقابتی (تا ۳٪)",
    "above": "گران‌تر (۳ تا ۱۰٪)",
    "far_above": "خیلی گران‌تر (+۱۰٪)",
    "unique": "بدون رقیب",
    "no_price": "بدون قیمت / ناموجود",
}


def _cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)).replace(microsecond=0).isoformat()


def _round_down(v: float, step: int = 1000) -> int:
    return int(v // step * step)


def excluded_sites() -> set[str]:
    """Sites that are still crawled and shown, but left out of the index, rank and recommendations."""
    return set(db.get_setting("stats_excluded_sites", []) or [])


_PACK_RE = re.compile(r"\b(?:مجموعه|بسته|پک|pack of|pack)\s*(\d+)\s*(?:عددی|عدد|تایی|تا|pcs)?\b|\b(\d+)\s*(?:pack|pk)\b")


def pack_size(title: str | None) -> int:
    """How many of the item a listing sells: 'مجموعه ۲ عددی' -> 2. 1 when it does not say."""
    m = _PACK_RE.search(tn.normalize(title))
    n = int(m.group(1) or m.group(2)) if m else 1
    return n if 2 <= n <= MAX_PACK else 1


def unit_price(o: dict, own_name: str | None) -> int | None:
    """The offer's price for the quantity we sell, so a 2-pack is compared per piece.

    Only for single items of ours: in '8 تکه' brush sets or 'ست' bundles the number is the content."""
    if not o.get("price"):
        return o.get("price")
    theirs = pack_size(o.get("title"))
    if theirs == 1 or tn.counts(own_name or "") or re.search(r"\bست\b|\bset\b", tn.normalize(own_name)):
        return o["price"]
    return round(o["price"] * pack_size(own_name) / theirs)


def _offer_ok(o: dict, my_price: int | None) -> bool:
    if o["status"] not in ("auto", "confirmed") or not o["price"] or not o["in_stock"]:
        return False
    if my_price:
        low, high = (SANITY_LOW, SANITY_HIGH) if o["status"] == "auto" else (CONFIRMED_LOW, CONFIRMED_HIGH)
        if not low <= o["price"] / my_price <= high:
            return False
    return True


def site_reads() -> dict[str, str]:
    """Per competitor, when its latest complete read started (a site that finished, in a run over all products).

    A listing seen then or later is current; one not seen since was gone from the site's results."""
    return {r["site"]: r["ts"] for r in db.q(
        """SELECT r.site, MAX(c.started_at) ts FROM site_runs r JOIN crawls c ON c.id = r.crawl_id
           WHERE r.status IN ('ok', 'partial') AND json_extract(COALESCE(c.stats, '{}'), '$.partial') IS NULL
           GROUP BY r.site""")}


def current_offers(offers: list[dict], cutoff: str, reads: dict[str, str] | None = None) -> list[dict]:
    """The listings that describe the market now: per site, those seen in its latest read.

    When reads stop (no schedule, a site blocking us) the last known prices stay in use for MAX_AGE_DAYS and
    are reported as stale, instead of the product silently turning into "no competitor"."""
    reads = site_reads() if reads is None else reads
    oldest = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).replace(microsecond=0).isoformat()
    out = [o for o in offers if (o["last_seen"] or "") >= max(min(reads.get(o["site"], cutoff), cutoff), oldest)]
    # per site, only the listings seen in that site's latest observation of this product
    latest: dict[str, int] = {}
    for o in out:
        latest[o["site"]] = max(latest.get(o["site"], 0), o["last_crawl_id"] or 0)
    return [o for o in out if (o["last_crawl_id"] or 0) == latest[o["site"]]]


def analyse_product(p: dict, offers: list[dict], cutoff: str, excluded: set[str] | None = None,
                    reads: dict[str, str] | None = None) -> dict:
    my = p["price"] if p["in_stock"] else None
    excluded = excluded_sites() if excluded is None else excluded
    offers = [{**o, "price": unit_price(o, p["name"]), "listed_price": o["price"]} for o in offers if o["site"] not in excluded]
    fresh = current_offers(offers, cutoff, reads)
    valid = [o for o in fresh if _offer_ok(o, p["price"])]
    suspicious = [o for o in fresh if o["status"] in ("auto", "confirmed") and o["price"] and o["in_stock"]
                  and not _offer_ok(o, p["price"])]
    matched_oos = [o for o in fresh if o["status"] in ("auto", "confirmed") and not o["in_stock"]]
    as_of = min((o["last_seen"] for o in valid), default=None)

    by_site: dict[str, dict] = {}
    for o in valid:
        cur = by_site.get(o["site"])
        if cur is None or o["price"] < cur["price"]:
            by_site[o["site"]] = {"site": o["site"], "price": o["price"], "url": o["url"], "seller": o["seller"],
                                  "regular_price": o["regular_price"], "seen": o["last_seen"],
                                  "pack": pack_size(o["title"]) if o["price"] != o["listed_price"] else 1}
    site_mins = sorted(by_site.values(), key=lambda s: s["price"])
    comps = [s["price"] for s in site_mins]

    res = {
        "id": p["id"], "name": p["name"], "brand": p["brand"], "image": p["image"], "permalink": p["permalink"],
        "categories": json.loads(p["categories"] or "[]"), "my_price": p["price"], "my_regular": p["regular_price"],
        "in_stock": bool(p["in_stock"]), "tracked": bool(p["tracked"]),
        "n_sites": len(site_mins), "n_listings": len(valid), "n_pending": sum(1 for o in offers if o["status"] == "pending"),
        "n_suspicious": len(suspicious), "as_of": as_of, "stale": bool(as_of and as_of < cutoff),
        "min": comps[0] if comps else None, "median": int(statistics.median(comps)) if comps else None,
        "max": comps[-1] if comps else None, "cheapest_site": site_mins[0]["site"] if site_mins else None,
        "cheapest_url": site_mins[0]["url"] if site_mins else None,
        "cheapest_pack": site_mins[0]["pack"] if site_mins else 1,
        "sites": site_mins, "index": None, "gap_min_pct": None, "rank": None, "position": None,
        "opportunity": None, "suggested_price": None, "impact": 0,
    }
    if not my:
        res["position"] = "no_price"
        return res
    if not comps:
        res["position"] = "unique"
        if matched_oos:
            res["opportunity"] = "competitors_oos"
        return res

    gap = (my - comps[0]) / comps[0] * 100
    res["gap_min_pct"] = round(gap, 1)
    res["index"] = round(my / statistics.median(comps) * 100, 1)
    res["rank"] = 1 + sum(1 for c in comps if c < my)
    if gap <= 0:
        res["position"] = "cheapest"
        headroom = (comps[0] - my) / my * 100
        if headroom > HEADROOM_PCT:
            suggested = _round_down(comps[0] * 0.99)
            if suggested > my:
                res["opportunity"] = "raise"
                res["suggested_price"] = suggested
                res["impact"] = suggested - my
    elif gap <= CLOSE_PCT:
        res["position"] = "close"
    elif gap <= FAR_PCT:
        res["position"] = "above"
    else:
        res["position"] = "far_above"
        res["opportunity"] = "risk"
        res["suggested_price"] = _round_down(comps[0])
        res["impact"] = my - comps[0]
    return res


def analyse_all(include_untracked: bool = False) -> list[dict]:
    cutoff = _cutoff()
    products = db.q("SELECT * FROM products WHERE active=1" + ("" if include_untracked else " AND tracked=1"))
    offers = defaultdict(list)
    for o in db.q("SELECT * FROM offers WHERE status != 'rejected'"):
        offers[o["product_id"]].append(o)
    excluded, reads = excluded_sites(), site_reads()
    return [analyse_product(p, offers[p["id"]], cutoff, excluded, reads) for p in products]


def summary() -> dict:
    rows = analyse_all()
    priced = [r for r in rows if r["position"] not in ("no_price",)]
    compared = [r for r in rows if r["index"] is not None]
    dist = {k: 0 for k in POSITIONS}
    for r in rows:
        dist[r["position"]] += 1

    last = db.q1("SELECT * FROM crawls WHERE status IN ('done','failed') ORDER BY id DESC LIMIT 1")
    running = db.q1("SELECT * FROM crawls WHERE status='running' ORDER BY id DESC LIMIT 1")

    raise_list = sorted([r for r in rows if r["opportunity"] == "raise"], key=lambda r: -r["impact"])
    risk_list = sorted([r for r in rows if r["opportunity"] == "risk"], key=lambda r: -(r["gap_min_pct"] or 0))
    oos_list = [r for r in rows if r["opportunity"] == "competitors_oos"]

    return {
        "products": len(rows),
        "priced": len(priced),
        "compared": len(compared),
        "coverage_pct": round(len(compared) / len(priced) * 100) if priced else 0,
        "median_index": round(statistics.median(
            [r["my_price"] / statistics.median([x["price"] for x in r["sites"]]) * 100 for r in compared]), 1)
        if compared else None,
        "cheapest_share": round(dist["cheapest"] / len(compared) * 100) if compared else 0,
        "distribution": [{"key": k, "label": v, "count": dist[k]} for k, v in POSITIONS.items()],
        "raise_total": sum(r["impact"] for r in raise_list),
        "raise_count": len(raise_list),
        "raise": raise_list[:12],
        "risk": risk_list[:12],
        "competitors_oos": oos_list[:12],
        "pending_reviews": db.q1("SELECT COUNT(*) n FROM offers WHERE status='pending'")["n"],
        # the numbers above lean on prices older than a day: say so, and since when
        "stale": sum(1 for r in compared if r["stale"]),
        "as_of": min((r["as_of"] for r in compared if r["as_of"]), default=None),
        "last_crawl": last,
        "running": running,
        "index_history": index_history(),
        "head_to_head": head_to_head(rows),
        "brands": brand_breakdown(rows),
        "changes": recent_changes(limit=25),
    }


def head_to_head(rows: list[dict]) -> list[dict]:
    """Per competitor: on shared products, how often are they cheaper and by how much."""
    acc = defaultdict(lambda: {"overlap": 0, "cheaper": 0, "diffs": []})
    for r in rows:
        if not r["my_price"] or not r["in_stock"]:
            continue
        for s in r["sites"]:
            a = acc[s["site"]]
            a["overlap"] += 1
            diff = (s["price"] - r["my_price"]) / r["my_price"] * 100
            a["diffs"].append(diff)
            if s["price"] < r["my_price"]:
                a["cheaper"] += 1
    runs = {r["site"]: r for r in db.q(
        "SELECT * FROM site_runs WHERE crawl_id=(SELECT MAX(crawl_id) FROM site_runs)")}
    out = []
    for key, name, _ in sources.COMPETITORS:
        a = acc.get(key)
        out.append({
            "site": key, "name": name, "overlap": a["overlap"] if a else 0,
            "cheaper": a["cheaper"] if a else 0,
            "cheaper_pct": round(a["cheaper"] / a["overlap"] * 100) if a and a["overlap"] else None,
            "median_diff_pct": round(statistics.median(a["diffs"]), 1) if a and a["diffs"] else None,
            "last_status": (runs.get(key) or {}).get("status"),
            "last_error": (runs.get(key) or {}).get("last_error"),
        })
    return sorted(out, key=lambda x: -x["overlap"])


def brand_breakdown(rows: list[dict]) -> list[dict]:
    acc = defaultdict(list)
    for r in rows:
        if r["index"] is not None:
            acc[r["brand"] or "بدون برند"].append(r)
    out = []
    for brand, items in acc.items():
        out.append({
            "brand": brand, "count": len(items),
            "median_index": round(statistics.median([i["index"] for i in items]), 1),
            "far_above": sum(1 for i in items if i["position"] == "far_above"),
            "cheapest": sum(1 for i in items if i["position"] == "cheapest"),
        })
    return sorted(out, key=lambda b: -b["count"])[:20]


def index_history(limit: int = 60) -> list[dict]:
    """Median price index per crawl (100 = same as market median).

    Uses the same rules as the live numbers: per product and site, the latest observation
    up to that crawl (carried forward for STALE_HOURS), only valid in-stock matches."""
    crawls = list(reversed(db.q("SELECT id, started_at FROM crawls WHERE status='done' ORDER BY id DESC LIMIT ?", (limit,))))
    if not crawls:
        return []
    first_id = crawls[0]["id"]
    excluded = excluded_sites()
    my = defaultdict(dict)
    for r in db.q("SELECT * FROM my_prices WHERE crawl_id >= ?", (first_id,)):
        if r["price"] and r["in_stock"]:
            my[r["crawl_id"]][r["product_id"]] = r["price"]
    obs = defaultdict(list)  # crawl -> observations
    for r in db.q(
        """SELECT op.crawl_id, op.price, op.in_stock, op.ts, o.status, o.product_id, o.site, o.title
           FROM offer_prices op JOIN offers o ON o.id=op.offer_id
           WHERE op.crawl_id >= ? AND o.status IN ('auto','confirmed')""", (first_id,)):
        if r["site"] not in excluded:
            obs[r["crawl_id"]].append(r)

    names = {r["id"]: r["name"] for r in db.q("SELECT id, name FROM products")}
    state: dict[tuple, tuple[int, str, list]] = {}  # (product, site) -> (crawl_id, ts, observations)
    done_ids = {c["id"] for c in crawls}
    all_ids = sorted(set(obs) | done_ids)
    out = []
    for cid in all_ids:
        for r in obs.get(cid, []):
            key = (r["product_id"], r["site"])
            if key not in state or state[key][0] != cid:
                state[key] = (cid, r["ts"], [])
            state[key][2].append(r)
        if cid not in done_ids:
            continue
        crawl = next(c for c in crawls if c["id"] == cid)
        cutoff = (datetime.fromisoformat(crawl["started_at"]) - timedelta(hours=STALE_HOURS)).isoformat()
        site_min = defaultdict(dict)
        for (pid, site), (_, ts, rows) in state.items():
            mine = my[cid].get(pid)
            if not mine or ts < cutoff:
                continue
            rows = [{**r, "price": unit_price(r, names.get(pid))} for r in rows]
            vals = [r["price"] for r in rows if _offer_ok(r, mine)]
            if vals:
                site_min[pid][site] = min(vals)
        idx, cheapest = [], 0
        for pid, price in my[cid].items():
            vals = list(site_min.get(pid, {}).values())
            if vals:
                idx.append(price / statistics.median(vals) * 100)
                cheapest += price <= min(vals)
        if idx:
            out.append({"crawl_id": cid, "ts": crawl["started_at"], "index": round(statistics.median(idx), 1),
                        "cheapest_share": round(cheapest / len(idx) * 100), "n": len(idx)})
    return out


def recent_changes(limit: int = 30, product_id: int | None = None) -> list[dict]:
    """Competitor price moves and stock changes between their last two observations."""
    where = "AND o.product_id=?" if product_id else ""
    params = (product_id,) if product_id else ()
    rows = db.q(f"""
        WITH ranked AS (
            SELECT op.*, ROW_NUMBER() OVER (PARTITION BY op.offer_id ORDER BY op.crawl_id DESC) rn
            FROM offer_prices op
        )
        SELECT o.id offer_id, o.product_id, o.site, o.title, o.seller, o.url, p.name product_name, p.price my_price,
               cur.price new_price, prev.price old_price, cur.in_stock new_stock, prev.in_stock old_stock, cur.ts
        FROM offers o
        JOIN products p ON p.id=o.product_id
        JOIN ranked cur ON cur.offer_id=o.id AND cur.rn=1
        JOIN ranked prev ON prev.offer_id=o.id AND prev.rn=2
        WHERE o.status IN ('auto','confirmed') {where}
          AND (COALESCE(cur.price,0) != COALESCE(prev.price,0) OR cur.in_stock != prev.in_stock)
        ORDER BY cur.ts DESC LIMIT 400""", params)
    out = []
    for r in rows:
        kind = "price"
        if r["new_stock"] != r["old_stock"]:
            kind = "back_in_stock" if r["new_stock"] else "out_of_stock"
        pct = None
        if r["old_price"] and r["new_price"]:
            pct = round((r["new_price"] - r["old_price"]) / r["old_price"] * 100, 1)
            if kind == "price" and abs(pct) < 0.5:
                continue
        out.append({**r, "kind": kind, "pct": pct})
    out.sort(key=lambda r: (r["ts"], abs(r["pct"] or 0)), reverse=True)
    return out[:limit]


def product_history(product_id: int, limit: int = 60) -> dict:
    crawls = db.q("SELECT id, started_at FROM crawls ORDER BY id DESC LIMIT ?", (limit,))
    ids = [c["id"] for c in crawls]
    if not ids:
        return {"points": [], "sites": []}
    marks = ",".join("?" * len(ids))
    my = {r["crawl_id"]: r for r in db.q(
        f"SELECT * FROM my_prices WHERE product_id=? AND crawl_id IN ({marks})", (product_id, *ids))}
    comp = defaultdict(dict)
    for r in db.q(
        f"""SELECT op.crawl_id, op.price, o.site FROM offer_prices op JOIN offers o ON o.id=op.offer_id
            WHERE o.product_id=? AND op.crawl_id IN ({marks}) AND o.status IN ('auto','confirmed')
              AND op.in_stock=1 AND op.price>0""", (product_id, *ids)):
        cur = comp[r["crawl_id"]].get(r["site"])
        if cur is None or r["price"] < cur:
            comp[r["crawl_id"]][r["site"]] = r["price"]
    points = []
    for c in reversed(crawls):
        m = my.get(c["id"])
        if not m and not comp.get(c["id"]):
            continue
        vals = sorted(comp.get(c["id"], {}).values())
        points.append({
            "ts": c["started_at"],
            "my": m["price"] if m and m["in_stock"] else None,
            "min": vals[0] if vals else None,
            "median": int(statistics.median(vals)) if vals else None,
            "sites": comp.get(c["id"], {}),
        })
    return {"points": points}
