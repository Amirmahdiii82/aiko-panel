"""Stock sync: the panel keeps stock, the site shows it — against a fake WooCommerce site."""
import asyncio
import re

import pytest

from app.core import integrations
from app.modules.erp import db, ledger
from app.modules.erp.site import client, matching, stock

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
                pool[u["id"]].update({k: v for k, v in u.items() if k != "id"})
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
    monkeypatch.setattr(stock, "_tick", idle)
    monkeypatch.setattr(stock, "_compared", False)       # every test starts like a freshly started app
    monkeypatch.setattr(client.Woo, "request", request)
    integrations.save_woo({"url": "https://shop", "key": "ck", "secret": "cs"})
    client._save_woo({"last_order_sync": "2026-01-01T00:00:00+00:00"})
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


def compared():
    """What the worker does first after the app starts: one full comparison with the site."""
    return run(stock.refresh(full=True))


def test_a_new_site_product_arrives_with_the_sites_stock(site):
    site.add(10, "رژ لب", 5)
    run(stock.refresh(full=True))
    p = product(10)
    assert p["stock"] == 5 and p["woo_state"] == "ok" and p["woo_stock"] == 5


def test_nothing_is_sent_before_a_full_comparison_since_the_app_started(site):
    site.add(10, "رژ لب", 5)
    run(stock.refresh(parents={10}))                       # a partial read is not enough
    with db.tx() as con:
        ledger.add_move(con, product(10)["id"], -2, "adjust", quiet=True)
    run(stock.push_pending())
    assert site.writes == []
    compared()
    run(stock.push_pending())
    assert site.products[10]["stock_quantity"] == 3


def test_every_change_here_sets_the_site_to_the_panels_number(site):
    site.add(10, "رژ لب", 5)
    compared()
    pid = product(10)["id"]
    with db.tx() as con:
        ledger.create_sale(con, {"channel": "in_person", "items": [{"product_id": pid, "qty": 2, "unit_price": 1}]},
                           None, quiet=True)
    run(stock.push_pending())
    assert site.products[10]["stock_quantity"] == 3
    with db.tx() as con:
        ledger.create_purchase(con, {"items": [{"product_id": pid, "qty": 10, "unit_cost": 1}]}, None, quiet=True)
    run(stock.push_pending())
    assert site.products[10]["stock_quantity"] == 13 and product(10)["woo_state"] == "ok"


def test_a_website_order_is_counted_once(site):
    site.add(10, "رژ لب", 5)
    compared()
    site.order(501, 10, 1)                                 # the site took it out of stock itself
    run(stock.refresh(full=True))
    run(stock.push_pending())
    p = product(10)
    assert p["stock"] == 4 and site.products[10]["stock_quantity"] == 4 and p["woo_state"] == "ok"


def test_stock_typed_by_hand_on_the_site_goes_back_to_the_panels_number(site):
    site.add(10, "رژ لب", 5)
    compared()
    site.products[10]["stock_quantity"] = 9                # edited in the WordPress admin
    report = run(stock.refresh(full=True))
    assert len(report["corrected"]) == 1
    run(stock.push_pending())
    assert site.products[10]["stock_quantity"] == 5 and product(10)["stock"] == 5
    with db.read() as con:
        assert con.execute("SELECT COUNT(*) FROM core.activity WHERE kind = 'site_stock' AND title LIKE '%دستی%'").fetchone()[0] == 1


def test_an_item_the_site_does_not_count_is_left_alone_until_counted_here(site, owner):
    site.add(20, "براش", manage=False)
    compared()
    p = product(20)
    assert p["woo_state"] == "nocount" and site.writes == []
    with db.tx() as con:
        ledger.add_move(con, p["id"], 1, "sale_void", quiet=True)       # a sale or return alone does not switch counting on
    run(stock.push_pending())
    run(stock.refresh(parents={20}))
    assert site.writes == [] and product(20)["woo_state"] == "nocount"
    r = owner.post(f"/api/erp/products/{p['id']}/adjust", json={"set_to": 7, "reason": "شمارش"}, headers=H)
    assert r.status_code == 200, r.text                    # a number set by a person: the site gets it
    run(stock.push_pending())
    assert site.products[20]["manage_stock"] is True and site.products[20]["stock_quantity"] == 7
    assert product(20)["stock"] == 7 and product(20)["woo_state"] == "ok"


def test_a_product_deleted_on_the_site_is_marked_and_never_pushed(site):
    site.add(10, "رژ لب", 5)
    site.add(11, "ریمل", 2)
    compared()
    del site.products[10]
    run(stock.refresh(full=True))
    assert product(10)["woo_state"] == "gone"
    run(stock.push_pending())
    assert site.writes == []


def test_an_empty_answer_from_the_site_never_marks_everything_deleted(site):
    site.add(10, "رژ لب", 5)
    run(stock.refresh(full=True))
    site.products.clear()
    with pytest.raises(client.WooError):
        run(stock.refresh(full=True))
    assert product(10)["woo_state"] == "ok"


def test_a_product_linked_as_a_whole_to_one_with_colors_is_read_only(site):
    site.add(30, "رژ مایع", manage=False, type_="variable")
    site.add_color(30, 31, "قرمز", 4)
    site.add_color(30, 32, "صورتی", 2)
    with db.tx() as con:
        pid = ledger.create_product(con, {"name": "رژ مایع قدیمی", "stock": 9}, None, quiet=True)
        matching.link_product(con, pid, 30, None, None)
    compared()
    p = product(30)
    assert p["id"] == pid and p["woo_state"] == "whole" and p["woo_stock"] == 6 and p["stock"] == 9
    with db.tx() as con:
        ledger.add_move(con, pid, -1, "adjust", quiet=True)
    run(stock.push_pending())
    run(stock.refresh(parents={30}))
    assert site.writes == [] and product(30)["woo_state"] == "whole"


def test_a_new_link_is_read_before_anything_is_sent(site):
    site.add(20, "براش", manage=False)
    compared()
    stock._touched.clear()
    with db.tx() as con:
        pid = ledger.create_product(con, {"name": "براش قدیمی", "stock": 0}, None, quiet=True)
        con.execute("UPDATE products SET woo_id = NULL WHERE woo_id = 20")
        matching.link_product(con, pid, 20, None, None)
        ledger.add_move(con, pid, 1, "adjust", quiet=True)
    run(stock.push_pending())
    assert site.writes == [] and 20 in stock._touched     # read first: the site does not count this one


def test_a_price_change_on_the_site_updates_the_price_here(site):
    site.add(10, "رژ لب", 5, price=100_000)
    run(stock.refresh(full=True))
    site.products[10]["price"] = "120000"
    run(stock.refresh(full=True))
    assert product(10)["price"] == 120_000


def test_sync_now_from_the_site_page(site, owner):
    site.add(10, "رژ لب", 5)
    r = owner.post("/api/erp/woo/sync-now", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["checked"] == 1
    assert {w["topic"] for w in site.webhooks} == set(client.WEBHOOK_TOPICS)     # instant updates set up on the way


def test_a_product_webhook_queues_that_product_for_a_reread(site, owner):
    import base64
    import hashlib
    import hmac
    import json
    stock._touched.clear()
    body = json.dumps({"id": 31, "parent_id": 30}).encode()
    secret = client.settings()["webhook_secret"].encode()
    sig = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
    r = owner.post("/api/erp/woo/webhook", content=body,
                   headers={"x-wc-webhook-topic": "product.updated", "x-wc-webhook-signature": sig})
    assert r.status_code == 200, r.text
    assert 30 in stock._touched
    r = owner.post("/api/erp/woo/webhook", content=body,
                   headers={"x-wc-webhook-topic": "product.updated", "x-wc-webhook-signature": "forged"})
    assert r.status_code == 401



def test_a_code_set_on_the_site_becomes_the_code_here(site):
    site.add(10, "رژ لب", 5)
    run(stock.refresh(full=True))
    site.products[10]["sku"] = "LIP-10"
    run(stock.refresh(full=True))
    assert product(10)["sku"] == "LIP-10"


def test_the_panels_codes_are_written_where_the_site_has_none(site, owner):
    site.add(10, "رژ لب", 5)
    site.add(30, "رژ مایع", manage=False, type_="variable")
    site.add_color(30, 31, "قرمز", 4)
    site.products[10]["sku"] = ""
    run(stock.refresh(full=True))
    assert len(stock.missing_codes()) == 2
    r = owner.post("/api/erp/woo/codes", headers=H)
    assert r.status_code == 200, r.text
    assert r.json() == {"written": 2, "errors": []}
    assert site.products[10]["sku"] == product(10)["sku"] and site.variations[30][31]["sku"] == product(30, 31)["sku"]
    assert stock.missing_codes() == [] and client.settings()["write_sku"] is True


def _count_file(tmp_path, monkeypatch, items, panel_only=()):
    import json as _json
    path = tmp_path / "stock_count_test.json"
    path.write_text(_json.dumps({"label": "شمارش آزمایشی", "date": "2026-10-22", "panel_only": list(panel_only),
                                 "items": [{"woo_id": w, "variation_id": v, "qty": q, "name": f"{w}/{v}"} for w, v, q in items]},
                                ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(stock, "COUNT_FILES", [path])


def test_a_hand_count_is_applied_once_to_the_panel_and_sent_to_the_site(site, tmp_path, monkeypatch):
    site.add(10, "رژ لب", 5)
    site.add(20, "براش", manage=False)
    site.add(30, "رژ مایع", manage=False, type_="variable")
    site.add_color(30, 31, "قرمز", 4)
    site.add_color(30, 32, "صورتی", 2)
    with db.tx() as con:
        whole = ledger.create_product(con, {"name": "رژ مایع قدیمی", "stock": 9}, None, quiet=True)
        matching.link_product(con, whole, 30, None, None)
    _count_file(tmp_path, monkeypatch, [(10, None, 7), (20, None, 3), (30, 31, 2), (30, 32, 0)],
                [{"name": "مداد چشم زرشکی گلدن رز", "qty": 3}])
    report = run(stock.refresh(full=True))
    assert report["count"]["missing"] == [] and report["count"]["split"] == 1
    assert product(10)["stock"] == 7 and product(20)["stock"] == 3
    assert product(30, 31)["stock"] == 2 and product(30, 32)["stock"] == 0
    with db.read() as con:
        assert con.execute("SELECT active FROM products WHERE id = ?", (whole,)).fetchone()[0] == 0
        assert con.execute("SELECT stock FROM products WHERE name = 'مداد چشم زرشکی گلدن رز'").fetchone()[0] == 3
    assert stock._compared
    run(stock.push_pending())
    assert site.products[10]["stock_quantity"] == 7
    assert site.products[20]["manage_stock"] is True and site.products[20]["stock_quantity"] == 3
    assert site.variations[30][31]["stock_quantity"] == 2 and site.variations[30][32]["stock_quantity"] == 0
    with db.tx() as con:                                   # a sale after the count is not undone by it
        ledger.create_sale(con, {"channel": "in_person", "items": [{"product_id": product(10)["id"], "qty": 1, "unit_price": 1}]},
                           None, quiet=True)
    run(stock.refresh(full=True))
    run(stock.push_pending())
    assert product(10)["stock"] == 6 and site.products[10]["stock_quantity"] == 6


def test_a_hand_count_with_costs_sets_the_unit_cost(site, tmp_path, monkeypatch, owner):
    site.add(10, "رژ لب", 5)
    run(stock.refresh(full=True))
    with db.tx() as con:                                   # sold on the site before its cost was known
        ledger.create_sale(con, {"channel": "in_person", "items": [{"product_id": product(10)["id"], "qty": 1, "unit_price": 1}]},
                           None, quiet=True)
    _count_file(tmp_path, monkeypatch, [(10, None, 2)])
    import json as _json
    plan = _json.loads(stock.COUNT_FILES[0].read_text(encoding="utf-8"))
    plan["items"][0]["cost"] = 380_000
    stock.COUNT_FILES[0].write_text(_json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    report = run(stock.refresh(full=True))
    assert report["count"]["costed"] == 1
    assert product(10)["stock"] == 2 and product(10)["avg_cost"] == 380_000
    with db.read() as con:
        assert con.execute("SELECT unit_cost FROM sale_items").fetchone()[0] == 380_000


@pytest.mark.parametrize("messy", [False, True])
def test_the_shipped_count_leaves_exactly_the_site_items_and_the_site_follows(site, messy):
    """The real shipped count, on an empty panel or on one mixed with old sheet rows: afterwards the warehouse is
    exactly the site's items with the counted numbers and costs, and old sales stay."""
    import json as _json
    if messy:
        with db.tx() as con:
            dup = ledger.create_product(con, {"name": "مداد قهوه‌ای فلورمار Flormar ابرو", "stock": 4, "avg_cost": 70_000}, None, quiet=True)
            ledger.create_sale(con, {"channel": "in_person", "items": [{"product_id": dup, "qty": 1, "unit_price": 185_000}]},
                               None, quiet=True)
            ledger.create_product(con, {"name": "رژ لب جامد کیکو میلانو", "stock": 6}, None, quiet=True)
            ledger.create_product(con, {"name": "مداد چشم زرشکی گلدن رز", "stock": 3}, None, quiet=True)
    plan = _json.loads(stock.COUNT_FILES[-1].read_text(encoding="utf-8"))
    for it in plan["items"]:
        if it["variation_id"]:
            if it["woo_id"] not in site.products:
                site.add(it["woo_id"], it["name"].split(" — ")[0], manage=False, type_="variable")
            site.add_color(it["woo_id"], it["variation_id"], it["name"].split(" — ")[1], 5)
        else:
            site.add(it["woo_id"], it["name"], 5)
    report = run(stock.refresh(full=True))
    assert report["count"]["missing"] == []
    run(stock.push_pending())
    with db.read() as con:
        units, value, n, loose = con.execute("""SELECT SUM(stock), SUM(stock * avg_cost), COUNT(*),
                                                       SUM(woo_id IS NULL) FROM products WHERE active = 1""").fetchone()
        sold = con.execute("SELECT p.woo_id FROM sale_items i JOIN products p ON p.id = i.product_id").fetchall()
    assert n == len(plan["items"]) and loose == 0
    assert units == sum(i["qty"] for i in plan["items"]) and value == sum(i["qty"] * i["cost"] for i in plan["items"])
    if messy:
        assert report["count"]["merged"] == ["مداد قهوه‌ای فلورمار Flormar ابرو"] and len(report["count"]["retired"]) == 2
        assert [r[0] for r in sold] == [410]          # the old sale now belongs to the site product
    for it in plan["items"]:
        on_site = (site.variations[it["woo_id"]][it["variation_id"]] if it["variation_id"]
                   else site.products[it["woo_id"]])["stock_quantity"]
        assert on_site == it["qty"], it["name"]


def test_a_hand_count_for_another_shop_is_never_applied(site, tmp_path, monkeypatch):
    site.add(10, "رژ لب", 5)
    _count_file(tmp_path, monkeypatch, [(999, None, 1), (998, None, 2)], [{"name": "چیزی", "qty": 1}])
    report = run(stock.refresh(full=True))
    assert report["count"] is None and product(10)["stock"] == 5


def test_the_release_carries_the_hand_counts():
    """deploy.sh keeps the server's own data/ folder out of each release. The count files must not live in a folder
    with that name (an unanchored exclude skipped them, so the count never reached the server), and the excludes must
    only ever match the top-level folders."""
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert stock.COUNT_FILES, "no shipped hand count found"
    tracked = subprocess.run(["git", "ls-files", "app"], cwd=root, capture_output=True, text=True, check=True).stdout.split()
    assert not [f for f in tracked if "data" in Path(f).parts], "a folder named data inside app/ is dropped by old deploys"
    keep = re.search(r"^KEEP=\((.*)\)$", (root / "deploy/deploy.sh").read_text(encoding="utf-8"), re.M).group(1)
    assert all(p.startswith("/") for p in re.findall(r"--exclude (\S+)", keep)), keep
