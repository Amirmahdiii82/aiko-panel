"""Pricing API on its own database: competitors, the crawl schedule, the match review queue."""
from app.core import db, modules

from .conftest import H


def test_pricing_api_on_an_empty_database(owner):
    meta = owner.get("/api/pricing/meta").json()
    assert len(meta["sites"]) >= 5 and meta["running"] is False
    s = owner.get("/api/pricing/summary").json()
    assert s["products"] == 0 and s["pending_reviews"] == 0
    assert owner.get("/api/pricing/products").json()["total"] == 0
    assert owner.get("/api/pricing/export.csv").status_code == 200
    assert owner.post("/api/pricing/sites/digikala", json={"in_stats": False}, headers=H).status_code == 200
    assert next(x for x in owner.get("/api/pricing/meta").json()["sites"] if x["key"] == "digikala")["in_stats"] is False


def test_crawl_schedule_is_set_from_the_panel(owner):
    r = owner.put("/api/pricing/schedule", json={"times": ["۹:۰۰", "21:30", "09:00"]}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["schedule"] == ["09:00", "21:30"] and r.json()["next_run"]
    assert owner.get("/api/pricing/meta").json()["schedule"] == ["09:00", "21:30"]
    assert owner.put("/api/pricing/schedule", json={"times": ["25:00"]}, headers=H).status_code == 400
    assert owner.put("/api/pricing/schedule", json={"times": []}, headers=H).json()["next_run"] is None


def test_offer_review_flow(owner):
    pricing_db = modules.loaded["pricing"].databases[0]
    with pricing_db.tx() as con:
        con.execute("INSERT INTO products (id, name, price, in_stock, active, tracked) VALUES (1, 'ریمل', 300000, 1, 1, 1)")
        con.execute("""INSERT INTO offers (product_id, site, external_id, title, score, status, price, in_stock, reasons, extra, last_seen)
                       VALUES (1, 'digikala', 'dkp-1', 'ریمل مشابه', 0.6, 'pending', 290000, 1, '[]', '{}', ?)""", (db.utcnow(),))
    q = owner.get("/api/pricing/review").json()
    assert q["total"] == 1
    oid = q["items"][0]["id"]
    assert owner.post(f"/api/pricing/offers/{oid}/status", json={"status": "confirmed"}, headers=H).status_code == 200
    assert owner.get("/api/pricing/review").json()["total"] == 0
    detail = owner.get("/api/pricing/products/1").json()
    assert detail["offers"][0]["status"] == "confirmed"


def _ago(days: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def test_old_prices_are_used_and_flagged_instead_of_reading_as_no_competitor(owner):
    """No crawl for days (no schedule, a deploy...) must not turn every product into "بدون رقیب"."""
    pricing_db = modules.loaded["pricing"].databases[0]
    with pricing_db.tx() as con:
        con.execute("INSERT INTO products (id, name, price, in_stock, active, tracked) VALUES (1, 'ریمل اسنس', 300000, 1, 1, 1)")
        con.execute("INSERT INTO crawls (id, started_at, finished_at, status) VALUES (1, ?, ?, 'done'), (2, ?, ?, 'done')",
                    (_ago(9), _ago(9), _ago(5), _ago(5)))
        con.execute("INSERT INTO site_runs (crawl_id, site, status) VALUES (1, 'digikala', 'ok'), (2, 'digikala', 'ok')")
        offer = """INSERT INTO offers (product_id, site, external_id, title, score, status, price, in_stock, reasons, extra,
                       last_seen, last_crawl_id) VALUES (1, 'digikala', ?, 'ریمل اسنس', 0.9, 'auto', ?, 1, '[]', '{}', ?, ?)"""
        con.execute(offer, ("seen-last-read", 250000, _ago(5), 2))
        con.execute(offer, ("gone-since", 100000, _ago(9), 1))       # not in the latest read: no longer listed
    a = owner.get("/api/pricing/products/1").json()["analysis"]
    assert a["position"] == "far_above" and a["min"] == 250000 and a["stale"] is True
    s = owner.get("/api/pricing/summary").json()
    assert s["stale"] == 1 and s["as_of"]


def test_multipacks_compare_per_piece_and_far_off_confirmed_prices_are_left_out(owner):
    pricing_db = modules.loaded["pricing"].databases[0]
    with pricing_db.tx() as con:
        con.execute("INSERT INTO products (id, name, price, in_stock, active, tracked) VALUES (1, 'اسفنج آرایشی تخم مرغی', 80000, 1, 1, 1)")
        offer = """INSERT INTO offers (product_id, site, external_id, title, score, status, price, in_stock, reasons, extra,
                       last_seen, last_crawl_id) VALUES (1, ?, ?, ?, 0.7, 'confirmed', ?, 1, '[]', '{}', ?, 1)"""
        con.execute(offer, ("digikala", "pack", "پد آرایشی مدل تخم مرغی مجموعه 2 عددی", 150000, db.utcnow()))
        con.execute(offer, ("basalam", "original", "اسفنج آرایشی تخم مرغی اورجینال", 450000, db.utcnow()))
    d = owner.get("/api/pricing/products/1").json()
    assert d["analysis"]["min"] == 75000 and d["analysis"]["n_sites"] == 1 and d["analysis"]["n_suspicious"] == 1
    pack = next(o for o in d["offers"] if o["external_id"] == "pack")
    assert pack["unit_price"] == 75000 and pack["pack"] == 2 and pack["counted"]


def test_matcher_tells_colours_apart_and_distrusts_brandless_lookalikes():
    from app.modules.pricing.matching import Candidate, Matcher, Own
    from app.modules.pricing import config
    m = Matcher(["خط چشم ماژیکی قهوه ای هدی بیوتی", "ریمل قهوه ای آرت اسکین مدل Sky High", "لیپ تینت پپتاید روود Rhode"])
    c = lambda t: Candidate("basalam", "1", t, "", 100000)
    brown = Own(1, "خط چشم ماژیکی قهوه‌ای هدی بیوتی Huda Beauty", "Huda Beauty")
    assert m.score(brown, c("خط چشم ماژیکی قهوه ای هدی بیوتی Huda Beauty"))[0] >= config.MATCH_AUTO
    score, reasons = m.score(brown, c("خط چشم ماژیکی مشکی هدی بیوتی Huda Beauty"))
    assert score < config.MATCH_AUTO and "رنگ متفاوت" in reasons
    # the model name still carries a brandless listing to the review queue; a bare description does not
    sky = Own(2, "ریمل قهوه‌ای آرت اسکین (Artskin) مدل Sky High", "Artskin")
    assert m.score(sky, c("ریمل قهوه ای sky high"))[0] >= config.MATCH_REVIEW
    assert m.score(sky, c("ریمل قهوه ای حجم دهنده"))[0] < config.MATCH_REVIEW
