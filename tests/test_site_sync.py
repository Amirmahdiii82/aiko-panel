"""Full site sync: exact website figures, merging with sheet/hand-typed sales, products made from the site,
missing costs, shared connections and the Telegram backup."""
import httpx

from app.core import backup, integrations
from app.modules.erp import db, ledger, sitesync, woo

from .conftest import H


def _catalog():
    return {"fetched_at": "2026-10-01T10:00:00+03:30", "source": "api", "items": [
        {"woo_id": 10, "variation_id": None, "type": "simple", "name": "لیپ گلاس کیکو", "price": 540_000,
         "image": None, "url": "https://shop/lip", "status": "publish", "manage_stock": True, "stock": 9,
         "in_stock": True, "sku": "", "categories": ["لب"], "brand": "KIKO"},
        {"woo_id": 20, "variation_id": None, "type": "variable", "name": "رژ مایع", "price": 240_000, "image": None,
         "url": "https://shop/rouge", "status": "publish", "manage_stock": False, "stock": None, "in_stock": True,
         "sku": "", "categories": ["لب"], "brand": ""},
        {"woo_id": 20, "variation_id": 21, "type": "variation", "name": "رژ مایع — قرمز", "variation_label": "قرمز",
         "price": 240_000, "image": None, "url": "https://shop/rouge", "status": "publish", "manage_stock": True,
         "stock": 4, "in_stock": True, "sku": "", "categories": ["لب"], "brand": ""},
        {"woo_id": 20, "variation_id": 22, "type": "variation", "name": "رژ مایع — صورتی", "variation_label": "صورتی",
         "price": 240_000, "image": None, "url": "https://shop/rouge", "status": "publish", "manage_stock": True,
         "stock": 2, "in_stock": True, "sku": "", "categories": ["لب"], "brand": ""},
        {"woo_id": 30, "variation_id": None, "type": "simple", "name": "ریمل حجم دهنده اسنس", "price": 550_000,
         "image": None, "url": "https://shop/mascara", "status": "publish", "manage_stock": True, "stock": 3,
         "in_stock": True, "sku": "ESS-1", "categories": ["چشم"], "brand": ""},
    ]}


def _order(oid, day, lines, status="completed", shipping="0", refunds=(), coupon=0):
    items = []
    for pid, vid, name, qty, unit in lines:
        sub = qty * unit
        items.append({"product_id": pid, "variation_id": vid, "name": name, "quantity": qty,
                      "subtotal": str(sub), "total": str(sub - coupon)})
    total = sum(qty * unit for *_, qty, unit in lines) - coupon * len(lines) + int(shipping)
    return {"id": oid, "number": str(oid), "status": status, "currency": "IRT", "date_created": f"{day}T11:20:00",
            "line_items": items, "shipping_total": shipping, "discount_total": str(coupon * len(lines)),
            "total": str(total), "total_tax": "0", "fee_lines": [], "refunds": list(refunds),
            "billing": {"first_name": "مریم", "last_name": "الف", "phone": "0912"}, "payment_method_title": "زرین‌پال"}


def _sheet_product(con, name, cost, qty, price):
    pid = ledger.create_product(con, {"name": name, "price": price}, None, quiet=True)
    ledger.create_purchase(con, {"date": "2026-08-01", "items": [{"product_id": pid, "qty": qty, "unit_cost": cost}]},
                           None, quiet=True)
    return pid


def _sheet_sale(con, day, items, channel="website"):
    return ledger.create_sale(con, {"code": f"ORD-{day}", "date": day, "channel": channel, "source": "sheet",
                                    "note": "از فایل اکسل", "items": items}, None, quiet=True, legacy=True)


def test_full_sync_merges_sheet_sales_with_exact_site_orders(owner):
    with db.tx() as con:
        lip = _sheet_product(con, "لیپ‌گلاس کیکو", 380_000, 15, 540_000)          # same name, different spacing
        rouge = _sheet_product(con, "رژ مایع Dihoor", 180_000, 6, 240_000)        # no SKU, different name
        _sheet_sale(con, "2026-09-01", [{"product_id": lip, "qty": 1, "unit_price": 540_000}])
        _sheet_sale(con, "2026-09-02", [{"product_id": rouge, "qty": 2, "unit_price": 240_000}])
        instagram = _sheet_sale(con, "2026-09-03", [{"product_id": lip, "qty": 1, "unit_price": 500_000}],
                                channel="instagram")
    orders = [
        _order(501, "2026-08-20", [(30, None, "ریمل حجم دهنده اسنس", 1, 550_000)], shipping="60000"),   # before the sheet
        _order(502, "2026-09-01", [(10, None, "لیپ گلاس کیکو", 1, 540_000)], shipping="50000"),
        _order(503, "2026-09-02", [(20, 21, "رژ مایع - قرمز", 1, 240_000), (20, 22, "رژ مایع - صورتی", 1, 240_000)]),
        _order(504, "2026-09-10", [(10, None, "لیپ گلاس کیکو", 2, 540_000)], coupon=80_000,
               refunds=[{"id": 1, "total": "-100000"}]),
        _order(505, "2026-09-11", [(10, None, "لیپ گلاس کیکو", 1, 540_000)], status="cancelled"),
    ]
    report = sitesync.apply(_catalog(), orders)
    assert report["sales_replaced"] == 2 and report["sales_created"] == 2

    with db.read() as con:
        sales = {r["code"]: dict(r) for r in con.execute("SELECT * FROM sales WHERE status = 'done'")}
        products = {r["id"]: dict(r) for r in con.execute("SELECT * FROM products WHERE active = 1")}
    # the sheet's website copies are gone, replaced by the site orders; the Instagram sale is untouched
    assert set(sales) == {"WEB-501", "WEB-502", "WEB-503", "WEB-504", f"ORD-2026-09-03"}
    assert sales["ORD-2026-09-03"]["id"] == instagram
    # exact site money: shipping included, coupon and refund taken off
    assert sales["WEB-502"]["total"] == 590_000 and sales["WEB-502"]["shipping"] == 50_000
    assert sales["WEB-504"]["discount"] == 80_000 and sales["WEB-504"]["refunded"] == 100_000
    assert sales["WEB-504"]["total"] == 2 * 540_000 - 80_000 - 100_000
    # linked by name, and the sheet product sold in two colors links to the whole site product
    assert products[lip]["woo_id"] == 10 and products[rouge]["woo_id"] == 20 and products[rouge]["woo_variation_id"] is None
    # the sheet's purchase cost is kept on the replaced sale
    assert sales["WEB-502"]["cogs"] == 380_000 and sales["WEB-503"]["cogs"] == 2 * 180_000
    # stock: lip 15 bought − 1 (502) − 1 (instagram) − 2 (504) = 11
    assert products[lip]["stock"] == 11
    # a site product the panel never had is created, with the site's stock as opening (3 now + 1 sold = 4 in)
    mascara = next(p for p in products.values() if p["woo_id"] == 30)
    assert mascara["stock"] == 3 and mascara["sku"] == "ESS-1" and mascara["category"] == "چشم"
    # its sale has no cost yet → reported, and filled once a cost is entered
    assert report["missing_cost"]["lines"] == 1
    with db.tx() as con:
        ledger.update_product(con, mascara["id"], {"avg_cost": 220_000})
    with db.read() as con:
        assert con.execute("SELECT cogs FROM sales WHERE code = 'WEB-501'").fetchone()[0] == 220_000

    # running it again changes nothing
    again = sitesync.apply(_catalog(), orders)
    assert again["sales_created"] == again["sales_replaced"] == again["products_created"] == 0
    with db.read() as con:
        assert con.execute("SELECT COUNT(*) FROM sales WHERE status = 'done'").fetchone()[0] == 5


def test_variable_product_without_panel_record_gets_one_product_per_color(owner):
    sitesync.apply(_catalog(), [])
    with db.read() as con:
        rows = db.rows(con.execute("SELECT woo_id, woo_variation_id, stock FROM products WHERE woo_id = 20 ORDER BY woo_variation_id"))
    assert [(r["woo_variation_id"], r["stock"]) for r in rows] == [(21, 4), (22, 2)]


def test_refund_on_the_site_updates_the_recorded_sale(owner):
    db.set_setting("woo_catalog", _catalog())
    order = _order(600, "2026-10-01", [(10, None, "لیپ گلاس کیکو", 1, 540_000)])
    assert woo.process_order(order) == "created"
    order["refunds"] = [{"id": 9, "total": "-40000"}]
    assert woo.process_order(order) == "updated"
    with db.read() as con:
        sale = db.one(con.execute("SELECT total, refunded FROM sales WHERE woo_order_id = 600"))
    assert sale == {"total": 500_000, "refunded": 40_000}


def test_merge_moves_history_and_keeps_the_site_link(owner):
    with db.tx() as con:
        old = _sheet_product(con, "کانسیلر قدیمی", 100_000, 4, 200_000)
        new = ledger.create_product(con, {"name": "کانسیلر", "price": 200_000, "woo_id": 77}, None, quiet=True)
        ledger.create_sale(con, {"channel": "in_person", "items": [{"product_id": old, "qty": 1, "unit_price": 200_000}]},
                           None, quiet=True)
    r = owner.post(f"/api/erp/products/{old}/merge", json={"into": new}, headers=H)
    assert r.status_code == 200, r.text
    with db.read() as con:
        p = db.one(con.execute("SELECT stock, avg_cost, woo_id FROM products WHERE id = ?", (new,)))
        assert con.execute("SELECT active FROM products WHERE id = ?", (old,)).fetchone()[0] == 0
    assert p == {"stock": 3, "avg_cost": 100_000, "woo_id": 77}


def test_connections_are_shared_and_secrets_stay_on_the_server(owner):
    r = owner.put("/api/integrations", json={"woo": {"url": "https://shop.ir/", "key": "ck_1", "secret": "cs_2"},
                                             "proxy_url": "socks5://127.0.0.1:1080", "openrouter_key": "sk-or-abcd"},
                  headers=H)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["woo"]["url"] == "https://shop.ir" and view["woo"]["secret_set"] and "secret" not in view["woo"]
    assert view["openrouter"]["key_hint"] == "…abcd"
    # the ERP and the price checker read the same site; the studio reads the same key and proxy
    assert woo.settings()["key"] == "ck_1" and woo.configured()
    from app.modules.pricing import config as pricing_config
    from app.modules.media import openrouter
    assert pricing_config.own_site_url() == "https://shop.ir"
    assert openrouter.settings()["proxy_url"] == "socks5://127.0.0.1:1080"
    assert owner.put("/api/integrations", json={"proxy_url": "ftp://x"}, headers=H).status_code == 400


def test_old_module_keys_move_to_the_shared_connection(owner):
    db.set_setting("woo", {**(db.get_setting("woo") or {}), "key": "ck_old", "secret": "cs_old"})
    woo.adopt_legacy_keys()
    assert integrations.woo()["key"] == "ck_old" and "key" not in db.get_setting("woo")


def test_telegram_backup_goes_through_the_proxy(owner, monkeypatch):
    sent = {}

    def fake_client(**kw):
        def handler(request: httpx.Request):
            sent["url"] = str(request.url)
            sent["body"] = request.content
            return httpx.Response(200, json={"ok": True, "result": {}})
        sent["proxied"] = True
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(integrations, "abroad_client", fake_client)
    r = owner.put("/api/backup/telegram", json={"enabled": True, "chat_id": "-100123", "token": "123:ABC", "hours": 1},
                  headers=H)
    assert r.status_code == 200 and r.json()["token_set"]
    assert backup.telegram_due()
    r = owner.post("/api/backup/telegram/send", headers=H)
    assert r.status_code == 200, r.text
    assert sent["proxied"] and "/bot123:ABC/sendDocument" in sent["url"] and b"PK" in sent["body"]
    s = owner.get("/api/backup/telegram").json()
    assert s["last_ok"] is True and "token" not in s
    assert not backup.telegram_due()


def test_telegram_notifications_use_the_proxy_but_bale_does_not(monkeypatch):
    from app.core import activity
    used = []
    monkeypatch.setattr(integrations, "abroad_client", lambda **kw: used.append("proxy") or httpx.AsyncClient())
    activity.bot_client("telegram")
    activity.bot_client("bale")
    assert used == ["proxy"]
