"""ERP through its HTTP API: stock, sales, sellers and the core activity feed."""
import time

from app.core import db

from .conftest import H, as_user, make_user


def _product(c, **kw):
    body = {"name": "لیپ گلاس", "price": 250_000, "stock": 5, **kw}
    r = c.post("/api/erp/products", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _feed(module="erp"):
    with db.core.read() as con:
        return [dict(r) for r in con.execute("SELECT * FROM activity WHERE module = ? ORDER BY id", (module,))]


def test_first_start_creates_partners_accounts_and_staff(owner):
    me = owner.get("/api/erp/me").json()
    assert [p["name"] for p in me["partners"]] == ["امیر", "تینا"]
    assert {a["kind"] for a in me["accounts"]} == {"partner", "shop"}
    staff = {s["username"]: s for s in owner.get("/api/erp/staff").json()}
    assert staff["amir"]["partner_id"] and staff["amir"]["account_name"] == "کارت امیر"


def test_sale_decrements_stock_and_void_restores_it(owner):
    pid = _product(owner)
    sale = owner.post("/api/erp/sales", json={"channel": "in_person", "items": [{"product_id": pid, "qty": 2, "unit_price": 250_000}]},
                      headers=H).json()["id"]
    assert owner.get(f"/api/erp/products/{pid}").json()["product"]["stock"] == 3
    assert owner.post(f"/api/erp/sales/{sale}/void", json={"reason": "test"}, headers=H).status_code == 200
    assert owner.get(f"/api/erp/products/{pid}").json()["product"]["stock"] == 5


def test_activity_is_written_to_core_only_after_commit(owner):
    pid = _product(owner)
    bad = owner.post("/api/erp/sales", json={"channel": "in_person", "items": [{"product_id": 9999, "qty": 1, "unit_price": 1}]}, headers=H)
    assert bad.status_code == 400
    owner.post("/api/erp/sales", json={"channel": "in_person", "items": [{"product_id": pid, "qty": 1, "unit_price": 250_000}]}, headers=H)
    time.sleep(0.1)
    kinds = [a["kind"] for a in _feed()]
    assert kinds.count("sale") == 1 and "product" in kinds
    sale = next(a for a in _feed() if a["kind"] == "sale")
    assert sale["link"].startswith("#/erp/sales/") and sale["notify"] == 1


def test_seller_profile_and_cash_account_come_from_the_team_page(owner):
    uid = make_user(owner, "sara", {"erp": "seller"}, profile={"erp": {"commission_pct": 10}})
    staff = {s["id"]: s for s in owner.get("/api/erp/staff").json()}
    assert staff[uid]["role"] == "seller" and staff[uid]["account_name"] == "پول نزد Sara"
    assert staff[uid]["commission_pct"] == 10


def test_seller_sale_goes_to_their_cash_account_and_hides_costs(owner):
    pid = _product(owner)
    make_user(owner, "sara", {"erp": "seller"}, profile={"erp": {"commission_pct": 10}})
    as_user(owner, "sara")
    r = owner.post("/api/erp/sales", json={"channel": "in_person", "items": [{"product_id": pid, "qty": 1, "unit_price": 250_000}]},
                   headers=H)
    assert r.status_code == 200, r.text
    sale = owner.get(f"/api/erp/sales/{r.json()['id']}").json()["sale"]
    assert sale["account_name"] == "پول نزد Sara" and "cogs" not in sale
    assert "avg_cost" not in owner.get("/api/erp/products").json()[0]
    home = owner.get("/api/home").json()["erp"]
    assert home["seller"] and home["month_total"] == 250_000


def test_dashboard_and_reports(owner):
    _product(owner)
    d = owner.get("/api/erp/dashboard").json()
    assert {"today", "period", "inventory", "trend", "channels"} <= set(d)
    for days in (7, 90, 365):
        t = owner.get(f"/api/erp/dashboard?days={days}&channel=website").json()
        assert t["days"] == days and t["channel"] == "website" and len(t["trend"]["current"]) == len(t["trend"]["previous"])
    assert owner.get("/api/erp/reports?period=month").status_code == 200
    assert owner.get("/api/erp/export.xlsx").status_code == 200


def test_woo_webhook_rejects_bad_signatures(client):
    r = client.post("/api/erp/woo/webhook", content=b"{}", headers={"x-wc-webhook-topic": "order.created",
                                                                  "x-wc-webhook-signature": "nope"})
    assert r.status_code == 401
