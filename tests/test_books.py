"""The old sheet's books, shipped with the panel: money and history in, today's (counted) stock untouched."""
import json

import pytest

from app.modules.erp import books, db, ledger

COUNT = "شمارش آزمایشی"


def _book(tmp_path, monkeypatch, **parts):
    book = {"label": "دفتر آزمایشی", "after_count": COUNT, "counted": "2026-10-23", "products": [], "sales": [],
            "purchases": [], "expenses": [], "capital": [], "categories": {"Software & Tools": "نرم‌افزار و ابزار"},
            "settlement": {"date": "2026-10-07", "tina_to_amir": 0}, **parts}
    path = tmp_path / "books_test.json"
    path.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(books, "BOOK_FILES", [path])
    return book


@pytest.fixture
def shop(owner):
    """After the first sheet import and the hand count: a site product without colors (5 counted) with its old sheet
    record retired beside it, and a site product with two colors."""
    with db.tx() as con:
        lip = ledger.create_product(con, {"name": "رژ لب سایت", "sku": "LIP-1", "woo_id": 10, "avg_cost": 300000}, None, quiet=True)
        ledger.add_move(con, lip, 5, "adjust", note=COUNT, quiet=True)
        old = ledger.create_product(con, {"name": "رژ لب", "sku": "PRD-001"}, None, quiet=True)
        ledger.create_purchase(con, {"code": "PO-1001", "date": "2026-07-18",
                                     "items": [{"product_id": old, "qty": 3, "unit_cost": 250000}]}, None, quiet=True)
        ledger.create_sale(con, {"code": "ORD-2001", "date": "2026-09-01", "channel": "website", "source": "sheet",
                                 "items": [{"product_id": old, "qty": 1, "unit_price": 400000}]}, None, quiet=True)
        ledger.add_move(con, old, -2, "adjust", note=COUNT, quiet=True)
        con.execute("UPDATE products SET active = 0 WHERE id = ?", (old,))
        red = ledger.create_product(con, {"name": "پالت — قرمز", "woo_id": 30, "woo_variation_id": 31}, None, quiet=True)
        ledger.add_move(con, red, 4, "adjust", note=COUNT, quiet=True)
        ledger.create_product(con, {"name": "پالت — صورتی", "woo_id": 30, "woo_variation_id": 32}, None, quiet=True)
        db.set_setting("stock_counts_applied", [COUNT], con)
    return {"lip": lip, "old": old, "red": red}


def _stock():
    with db.read() as con:
        return {r["id"]: (r["stock"], r["avg_cost"]) for r in con.execute("SELECT * FROM products WHERE active = 1")}


def test_the_sheets_books_come_in_once_without_moving_counted_stock(shop, tmp_path, monkeypatch):
    _book(tmp_path, monkeypatch,
          products=[{"sku": "PRD-001", "name": "رژ لب", "woo_id": 10, "cost": 250000, "price": 400000, "purchases": ["PO-1001"]},
                    {"sku": "PRD-002", "name": "پالت", "woo_id": 30, "cost": 200000, "price": 350000, "purchases": []}],
          sales=[{"code": "ORD-2001", "date": "2026-09-01", "channel": "in_person", "customer": "", "items": []},
                 {"code": "ORD-2010", "date": "2026-10-13", "channel": "in_person", "customer": "Leyla",
                  "items": [{"sku": "PRD-001", "qty": 2, "unit_price": 400000, "unit_cost": 250000},
                            {"sku": "PRD-002", "qty": 1, "unit_price": 350000, "unit_cost": 200000}]},
                 {"code": "ORD-2012", "date": "2026-10-13", "date_guessed": True, "channel": "in_person",
                  "customer": "Kimia", "items": [], "total": 590000}],
          purchases=[{"code": "PO-1042", "date": "2026-10-07", "note": "از برگه محصولات",
                      "items": [{"sku": "PRD-002", "qty": 6, "unit_cost": 200000}]}],
          expenses=[{"code": "EXP-140", "date": "2026-10-10", "category": "Software & Tools", "description": "SMS",
                     "amount": 50000, "paid_by": "tina", "settled": False, "note": ""}])
    before = _stock()
    with db.tx() as con:
        report = books.apply(con)
    assert report["sales"] == 2 and report["purchases"] == 1 and report["expenses"] == 1 and report["channels"] == 1
    assert _stock() == before                                   # counted numbers and unit costs exactly as they were
    with db.read() as con:
        sale = db.one(con.execute("SELECT * FROM sales WHERE code = 'ORD-2010'"))
        assert sale["total"] == 1150000 and sale["cogs"] == 700000 and sale["source"] == "sheet"
        lines = {r["name"]: r["product_id"] for r in con.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale["id"],))}
        assert lines["رژ لب سایت"] == shop["lip"]               # the old sheet record merged into its site product
        palette = lines["پالت"]
        assert con.execute("SELECT active FROM products WHERE id = ?", (palette,)).fetchone()[0] == 0
        assert con.execute("SELECT stock FROM products WHERE id = ?", (palette,)).fetchone()[0] == 0
        moved = con.execute("""SELECT kind, qty, substr(created_at, 1, 10) FROM stock_moves WHERE product_id = ?
                               ORDER BY id""", (shop["lip"],)).fetchall()
        assert ("sale", -2, "2026-10-13") in [tuple(m) for m in moved] and ("adjust", 2, "2026-10-23") in [tuple(m) for m in moved]
        assert con.execute("SELECT COUNT(*) FROM sale_items WHERE product_id = ?", (shop["old"],)).fetchone()[0] == 0
        assert db.one(con.execute("SELECT channel FROM sales WHERE code = 'ORD-2001'"))["channel"] == "in_person"
        kimia = db.one(con.execute("SELECT * FROM sales WHERE code = 'ORD-2012'"))
        assert kimia["total"] == 590000 and "تاریخش در اکسل نبود" in kimia["note"]
        assert db.one(con.execute("SELECT account_id FROM expenses WHERE code = 'EXP-140'"))["account_id"] == 2
        assert db.one(con.execute("SELECT total, account_id FROM purchases WHERE code = 'PO-1042'")) == \
            {"total": 1200000, "account_id": None}
    with db.tx() as con:
        assert books.apply(con) is None                         # once


def test_a_sale_already_typed_in_or_replaced_by_its_site_order_is_not_recorded_twice(shop, tmp_path, monkeypatch):
    with db.tx() as con:
        ledger.create_sale(con, {"date": "2026-10-20", "channel": "in_person",
                                 "items": [{"product_id": shop["lip"], "qty": 1, "unit_price": 400000}]}, None, quiet=True)
        ledger.create_sale(con, {"code": "WEB-361", "date": "2026-09-02", "channel": "website", "source": "site",
                                 "note": "سفارش سایت #361 (جایگزین ORD-2002 که دستی/از اکسل ثبت شده بود)",
                                 "items": [{"product_id": shop["lip"], "qty": 1, "unit_price": 1}]}, None, quiet=True)
    item = [{"sku": "PRD-001", "qty": 1, "unit_price": 400000, "unit_cost": 250000}]
    _book(tmp_path, monkeypatch,
          products=[{"sku": "PRD-001", "name": "رژ لب", "woo_id": 10, "cost": 250000, "price": 400000, "purchases": ["PO-1001"]}],
          sales=[{"code": "ORD-2002", "date": "2026-09-02", "channel": "website", "customer": "", "items": item},
                 {"code": "ORD-2013", "date": "2026-10-20", "channel": "in_person", "customer": "", "items": item}])
    with db.tx() as con:
        report = books.apply(con)
        assert report["sales"] == 0 and report["skipped"] == ["ORD-2013 (همان S-2)"]
        assert not con.execute("SELECT 1 FROM sales WHERE code IN ('ORD-2002', 'ORD-2013')").fetchone()


def test_the_books_wait_for_the_count_and_only_go_to_the_shop_they_were_made_for(owner, tmp_path, monkeypatch):
    _book(tmp_path, monkeypatch)
    with db.tx() as con:
        db.set_setting("stock_counts_applied", [COUNT], con)
        assert books.apply(con) is None                         # no first sheet import here
        ledger.create_purchase(con, {"code": "PO-1001", "items": [{"new_product": {"name": "x"}, "qty": 1, "unit_cost": 1}]},
                               None, quiet=True)
        db.set_setting("stock_counts_applied", [], con)
        assert books.apply(con) is None                         # the count it follows has not been applied yet
        db.set_setting("stock_counts_applied", [COUNT], con)
        assert books.apply(con)["label"] == "دفتر آزمایشی"
