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
