"""Stock sync: the panel keeps stock, the site shows it — against a fake WooCommerce site."""
import asyncio
import re

import pytest

from app.core import integrations
from app.modules.erp import db, ledger, stocksync, woo

from .conftest import H


class FakeSite:
    """Just enough of the WooCommerce REST API: products, colors, stock writes, orders, webhooks."""

    def __init__(self):
        self.products: dict[int, dict] = {}
        self.variations: dict[int, dict[int, dict]] = {}
        self.orders: list[dict] = []
        self.writes: list[tuple[str, dict]] = []
        self.webhooks: list[dict] = []

    def add(self, pid, name, stock=None, *, manage=True, price=100_000, type_="simple"):
        self.products[pid] = {"id": pid, "name": name, "type": type_, "price": str(price), "status": "publish",
                              "manage_stock": manage, "stock_quantity": stock if manage else None,
                              "stock_status": "instock", "sku": "", "categories": [], "images": [], "permalink": f"https://shop/{pid}"}

    def add_color(self, pid, vid, label, stock):
        self.variations.setdefault(pid, {})[vid] = {"id": vid, "attributes": [{"option": label}], "price": "100000",
                                                    "status": "publish", "manage_stock": True, "stock_quantity": stock,
                                                    "stock_status": "instock", "sku": "", "image": {}}

    def order(self, oid, pid, qty, status="processing"):
        """A customer buys on the site: WooCommerce takes it out of stock at once."""
        self.products[pid]["stock_quantity"] -= qty
        self.orders.append({"id": oid, "number": str(oid), "status": status, "currency": "IRT",
                            "date_created": "2026-10-20T10:00:00", "line_items": [
                                {"product_id": pid, "variation_id": 0, "name": self.products[pid]["name"], "quantity": qty,
                                 "subtotal": str(qty * 100_000), "total": str(qty * 100_000)}],
                            "shipping_total": "0", "discount_total": "0", "total": str(qty * 100_000), "total_tax": "0",
                            "fee_lines": [], "refunds": [], "billing": {}})

    async def request(self, method, path, params=None, json=None):
        params = params or {}
        if method == "GET" and path == "products":
            ids = {int(x) for x in params["include"].split(",")} if params.get("include") else None
            return [p for p in self.products.values() if ids is None or p["id"] in ids], {"x-wp-totalpages": "1"}
        m = re.fullmatch(r"products/(\d+)/variations", path)
        if method == "GET" and m:
            return list(self.variations.get(int(m[1]), {}).values()), {"x-wp-totalpages": "1"}
        if method == "POST" and path.endswith("batch"):
            self.writes.append((path, json))
            m = re.fullmatch(r"products/(\d+)/variations/batch", path)
            pool = self.variations[int(m[1])] if m else self.products
            out = []
            for u in json["update"]:
                pool[u["id"]].update(manage_stock=u["manage_stock"], stock_quantity=u["stock_quantity"])
                out.append(dict(pool[u["id"]]))
            return {"update": out}, {}
        if method == "GET" and path == "orders":
            return list(self.orders), {"x-wp-totalpages": "1"}
        if path == "webhooks" or path.startswith("webhooks/"):
            if method == "POST":
                self.webhooks.append(json)
            return (self.webhooks if method == "GET" else {"id": len(self.webhooks)}), {"x-wp-totalpages": "1"}
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def site(owner, monkeypatch):
    fake = FakeSite()

    async def request(self, method, path, params=None, json=None):
        return await fake.request(method, path, params, json)

    async def idle(s):                      # the app's own background worker stays out of the way
        return None
    monkeypatch.setattr(stocksync, "_tick", idle)
    monkeypatch.setattr(woo.Woo, "request", request)
    integrations.save_woo({"url": "https://shop", "key": "ck", "secret": "cs"})
    woo._save_woo({"last_order_sync": "2026-01-01T00:00:00+00:00"})
    return fake


def run(coro):
    return asyncio.run(coro)


def product(woo_id, variation=None):
    with db.read() as con:
        return db.one(con.execute("SELECT * FROM products WHERE woo_id = ? AND IFNULL(woo_variation_id, 0) = ?",
                                  (woo_id, variation or 0)))


def moves(pid, kind):
    with db.read() as con:
        return [r[0] for r in con.execute("SELECT qty FROM stock_moves WHERE product_id = ? AND kind = ?", (pid, kind))]


USER = {"id": None, "name": "امیر"}


def start(side):
    return run(stocksync.start(side, USER))


def test_a_new_site_product_arrives_with_the_sites_stock(site):
    site.add(10, "رژ لب", 5)
    run(stocksync.refresh(full=True))
    p = product(10)
    assert p["stock"] == 5 and p["woo_state"] == "ok" and p["woo_stock"] == 5


def test_nothing_is_sent_before_the_one_time_start(site):
    site.add(10, "رژ لب", 5)
    run(stocksync.refresh(full=True))
    with db.tx() as con:
        ledger.add_move(con, product(10)["id"], -2, "adjust", quiet=True)
    run(stocksync.refresh(full=True))
    run(stocksync.push_pending())
    assert site.writes == [] and product(10)["woo_state"] == "differ" and product(10)["stock"] == 3


def _differing(site):
    site.add(10, "رژ لب", 5)
    run(stocksync.refresh(full=True))
    with db.tx() as con:
        ledger.add_move(con, product(10)["id"], 3, "adjust", quiet=True)      # here 8, on the site 5


def test_starting_with_the_sites_numbers(site):
    _differing(site)
    r = start("site")
    assert r["changed"] == 1 and product(10)["stock"] == 5 and product(10)["woo_state"] == "ok" and site.writes == []


def test_starting_with_the_panels_numbers(site, owner):
    _differing(site)
    r = owner.post("/api/erp/woo/start", json={"side": "panel"}, headers=H)
    assert r.status_code == 200, r.text
    assert site.products[10]["stock_quantity"] == 8 and product(10)["woo_state"] == "ok"
    assert {w["topic"] for w in site.webhooks} == set(woo.WEBHOOK_TOPICS)     # instant updates set up on the way


def test_every_change_here_sets_the_site_to_the_panels_number(site):
    site.add(10, "رژ لب", 5)
    start("site")
    pid = product(10)["id"]
    with db.tx() as con:
        ledger.create_sale(con, {"channel": "in_person", "items": [{"product_id": pid, "qty": 2, "unit_price": 1}]},
                           None, quiet=True)
    run(stocksync.push_pending())
    assert site.products[10]["stock_quantity"] == 3
    with db.tx() as con:
        ledger.create_purchase(con, {"items": [{"product_id": pid, "qty": 10, "unit_cost": 1}]}, None, quiet=True)
    run(stocksync.push_pending())
    assert site.products[10]["stock_quantity"] == 13 and product(10)["woo_state"] == "ok"


def test_a_website_order_is_counted_once(site):
    site.add(10, "رژ لب", 5)
    start("site")
    site.order(501, 10, 1)                                 # the site took it out of stock itself
    run(stocksync.refresh(full=True))
    run(stocksync.push_pending())
    p = product(10)
    assert p["stock"] == 4 and site.products[10]["stock_quantity"] == 4 and p["woo_state"] == "ok"


def test_stock_typed_by_hand_on_the_site_goes_back_to_the_panels_number(site):
    site.add(10, "رژ لب", 5)
    start("site")
    site.products[10]["stock_quantity"] = 9                # edited in the WordPress admin
    report = run(stocksync.refresh(full=True))
    assert len(report["corrected"]) == 1
    run(stocksync.push_pending())
    assert site.products[10]["stock_quantity"] == 5 and product(10)["stock"] == 5
    with db.read() as con:
        assert con.execute("SELECT COUNT(*) FROM core.activity WHERE kind = 'site_stock' AND title LIKE '%دستی%'").fetchone()[0] == 1


def test_an_item_the_site_does_not_count_is_left_alone_until_counted_here(site, owner):
    site.add(20, "براش", manage=False)
    start("panel")
    p = product(20)
    assert p["woo_state"] == "nocount" and site.writes == []
    with db.tx() as con:
        ledger.add_move(con, p["id"], 1, "adjust", quiet=True)          # a change alone does not switch counting on
    run(stocksync.push_pending())
    run(stocksync.refresh(parents={20}))
    assert site.writes == [] and product(20)["woo_state"] == "nocount"
    r = owner.post("/api/erp/woo/count", json={"product_id": p["id"], "qty": 7}, headers=H)
    assert r.status_code == 200, r.text
    run(stocksync.push_pending())
    assert site.products[20]["manage_stock"] is True and site.products[20]["stock_quantity"] == 7
    assert product(20)["stock"] == 7 and product(20)["woo_state"] == "ok"


def test_a_product_deleted_on_the_site_is_marked_and_never_pushed(site):
    site.add(10, "رژ لب", 5)
    site.add(11, "ریمل", 2)
    start("site")
    del site.products[10]
    run(stocksync.refresh(full=True))
    assert product(10)["woo_state"] == "gone"
    run(stocksync.push_pending())
    assert site.writes == []


def test_an_empty_answer_from_the_site_never_marks_everything_deleted(site):
    site.add(10, "رژ لب", 5)
    run(stocksync.refresh(full=True))
    site.products.clear()
    with pytest.raises(woo.WooError):
        run(stocksync.refresh(full=True))
    assert product(10)["woo_state"] == "ok"


def test_a_product_linked_as_a_whole_to_one_with_colors_is_read_only(site):
    site.add(30, "رژ مایع", manage=False, type_="variable")
    site.add_color(30, 31, "قرمز", 4)
    site.add_color(30, 32, "صورتی", 2)
    with db.tx() as con:
        pid = ledger.create_product(con, {"name": "رژ مایع قدیمی", "stock": 9}, None, quiet=True)
        woo.link_product(con, pid, 30, None, None)
    start("panel")
    p = product(30)
    assert p["id"] == pid and p["woo_state"] == "whole" and p["woo_stock"] == 6 and p["stock"] == 9
    with db.tx() as con:
        ledger.add_move(con, pid, -1, "adjust", quiet=True)
    run(stocksync.push_pending())
    run(stocksync.refresh(parents={30}))
    assert site.writes == [] and product(30)["woo_state"] == "whole"


def test_a_new_link_is_read_before_anything_is_sent(site):
    site.add(20, "براش", manage=False)
    start("site")
    stocksync._touched.clear()
    with db.tx() as con:
        pid = ledger.create_product(con, {"name": "براش قدیمی", "stock": 0}, None, quiet=True)
        con.execute("UPDATE products SET woo_id = NULL WHERE woo_id = 20")
        woo.link_product(con, pid, 20, None, None)
        ledger.add_move(con, pid, 1, "adjust", quiet=True)
    run(stocksync.push_pending())
    assert site.writes == [] and 20 in stocksync._touched     # read first: the site does not count this one


def test_a_price_change_on_the_site_updates_the_price_here(site):
    site.add(10, "رژ لب", 5, price=100_000)
    run(stocksync.refresh(full=True))
    site.products[10]["price"] = "120000"
    run(stocksync.refresh(full=True))
    assert product(10)["price"] == 120_000


def test_sync_now_from_the_site_page(site, owner):
    site.add(10, "رژ لب", 5)
    r = owner.post("/api/erp/woo/sync-now", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["checked"] == 1


def test_a_product_webhook_queues_that_product_for_a_reread(site, owner):
    import base64
    import hashlib
    import hmac
    import json
    stocksync._touched.clear()
    body = json.dumps({"id": 31, "parent_id": 30}).encode()
    secret = woo.settings()["webhook_secret"].encode()
    sig = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
    r = owner.post("/api/erp/woo/webhook", content=body,
                   headers={"x-wc-webhook-topic": "product.updated", "x-wc-webhook-signature": sig})
    assert r.status_code == 200, r.text
    assert 30 in stocksync._touched
    r = owner.post("/api/erp/woo/webhook", content=body,
                   headers={"x-wc-webhook-topic": "product.updated", "x-wc-webhook-signature": "forged"})
    assert r.status_code == 401
