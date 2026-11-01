"""The old sheet's books, shipped with the panel (counts/books_*.json) and applied once.

The sheet kept on recording in-person sales, purchases and expenses after it was imported; the hand count already
holds every one of those items, so this records the money and the history without moving today's stock:

* every sale/purchase gets its normal stock moves on its own date, and one adjustment on the count date takes them
  back ("already in the count"); stock today and each product's counted unit cost stay exactly as they are, and the
  balance sheet of an earlier month still sees the goods that were on the shelf then;
* a sale already here (by its sheet code), replaced by its exact site order, or typed in by hand (same day, same
  amount) is not recorded twice; one already here only takes the sheet's channel;
* a sheet row is the site product it names when that product has no colors (an old sheet record of it that the
  tidy-up retired is merged into it); a product with colors keeps its history on the old sheet record, or on a
  retired record made for it, since the sheet never said which color was sold;
* expenses by their code; the partners' "Settled" rows by one balancing settlement, like the first import.

Only on the shop it was made for (the first sheet import is there) and only after the count it follows.
"""
import json
import logging
from pathlib import Path

from . import db, ledger, notify

log = logging.getLogger("aiko.erp.books")

BOOK_FILES = sorted((Path(__file__).resolve().parent / "counts").glob("books_*.json"))
PARTNERS = {"amir": "امیر", "tina": "تینا"}
UNKNOWN_ITEMS = "اقلام این فروش در اکسل نیامده؛ فقط مبلغش ثبت شده"


def _plans() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in BOOK_FILES]


def _stamp(con, table: str, row_id: int, day: str, hour: str = "18:00:00") -> None:
    ts = f"{day}T{hour}+03:30"
    con.execute(f"UPDATE {table} SET created_at = ? WHERE id = ?", (ts, row_id))
    if table == "sales":
        con.execute("UPDATE sales SET updated_at = ? WHERE id = ?", (ts, row_id))
    ref = {"sales": "sale", "purchases": "purchase"}.get(table)
    if ref:
        con.execute("UPDATE stock_moves SET created_at = ? WHERE ref_type = ? AND ref_id = ?", (ts, ref, row_id))


def _counted(con, book: dict, moved: dict[int, int], note: str) -> None:
    """Take back what a recorded document moved: the count already holds it. The counted unit cost stays."""
    for pid, qty in moved.items():
        before = ledger.get_product(con, pid)["avg_cost"]
        ledger.add_move(con, pid, -qty, "adjust", note=note, quiet=True)
        con.execute("UPDATE products SET avg_cost = ? WHERE id = ?", (before, pid))
        con.execute("UPDATE stock_moves SET created_at = ? WHERE id = (SELECT MAX(id) FROM stock_moves WHERE product_id = ?)",
                    (f"{book['counted']}T12:00:00+03:30", pid))


def _product(con, p: dict, label: str, report: dict) -> int:
    holder = None
    if p["purchases"]:
        marks = ",".join("?" * len(p["purchases"]))
        row = con.execute(f"""SELECT i.product_id FROM purchase_items i JOIN purchases u ON u.id = i.purchase_id
                              WHERE u.code IN ({marks}) ORDER BY i.id LIMIT 1""", p["purchases"]).fetchone()
        holder = ledger.get_product(con, row[0]) if row else None
    colors = con.execute("""SELECT COUNT(*) FROM products WHERE active = 1 AND woo_id = ?
                            AND woo_variation_id IS NOT NULL""", (p["woo_id"],)).fetchone()[0]
    single = None if colors else db.one(con.execute(
        "SELECT * FROM products WHERE active = 1 AND woo_id = ? AND woo_variation_id IS NULL", (p["woo_id"],)))
    if single:
        if holder and holder["id"] != single["id"] and not holder["active"]:
            stock, cost = single["stock"], single["avg_cost"]
            ledger.merge_products(con, holder["id"], single["id"], {"id": None}, quiet=True)
            after = ledger.get_product(con, single["id"])["stock"]
            if after != stock:
                ledger.add_move(con, single["id"], stock - after, "adjust", note=label, quiet=True)
            con.execute("UPDATE products SET avg_cost = ? WHERE id = ?", (cost, single["id"]))
            report["merged"].append(single["name"])
        return single["id"]
    if holder:
        return holder["id"]
    pid = ledger.create_product(con, {"name": p["name"], "price": p["price"], "avg_cost": p["cost"],
                                      "notes": "سوابق اکسل این محصول (بدون رنگ)؛ موجودی هر رنگ در محصول سایت است"},
                                None, quiet=True)
    con.execute("UPDATE products SET active = 0 WHERE id = ?", (pid,))
    return pid


def _sale(con, book: dict, s: dict, pids: dict, accounts: dict, report: dict) -> None:
    here = db.one(con.execute("SELECT * FROM sales WHERE code = ?", (s["code"],)))
    if here:
        if here["source"] == "sheet" and here["status"] == "done" and here["channel"] != s["channel"]:
            ledger.update_sale(con, here["id"], {"channel": s["channel"], "account_id": accounts.get(s["channel"])},
                               {"id": None, "name": book["label"]})
            report["channels"] += 1
        return
    if con.execute("SELECT 1 FROM sales WHERE note LIKE ?", (f"%جایگزین {s['code']} %",)).fetchone():
        return                                               # its exact site order is already here
    items = [{"product_id": pids[i["sku"]], "qty": i["qty"], "unit_price": i["unit_price"], "unit_cost": i["unit_cost"]}
             for i in s["items"]]
    if not items:
        items = [{"name": UNKNOWN_ITEMS, "qty": 1, "unit_price": s["total"], "unit_cost": 0}]
    total = sum(i["qty"] * i["unit_price"] for i in items)
    twin = db.one(con.execute("""SELECT code FROM sales WHERE status = 'done' AND date = ? AND total = ?
                                 AND IFNULL(source, '') != 'sheet'""", (s["date"], total)))
    if twin:
        report["skipped"].append(f"{s['code']} (همان {twin['code']})")
        return
    note = "از فایل اکسل" + ("؛ تاریخش در اکسل نبود، نزدیک‌ترین تاریخ گذاشته شد" if s.get("date_guessed") else "")
    sale_id = ledger.create_sale(con, {
        "code": s["code"], "date": s["date"], "channel": s["channel"], "customer_name": s["customer"],
        "items": items, "account_id": accounts.get(s["channel"]), "source": "sheet", "note": note,
    }, None, quiet=True)
    _stamp(con, "sales", sale_id, s["date"])
    moved = {}
    for i in items:
        if i.get("product_id"):
            moved[i["product_id"]] = moved.get(i["product_id"], 0) - i["qty"]
    _counted(con, book, moved, f"{s['code']} — {book['after_count']} این فروش را از قبل داشت")
    report["sales"] += 1
    report["revenue"] += total


def _purchase(con, book: dict, p: dict, pids: dict, report: dict) -> None:
    if con.execute("SELECT 1 FROM purchases WHERE code = ?", (p["code"],)).fetchone():
        return
    items = [{"product_id": pids[i["sku"]], "qty": i["qty"], "unit_cost": i["unit_cost"]} for i in p["items"]]
    costs = {i["product_id"]: ledger.get_product(con, i["product_id"])["avg_cost"] for i in items}
    purchase_id = ledger.create_purchase(con, {"code": p["code"], "date": p["date"], "account_id": None,
                                               "note": p["note"], "items": items}, None, quiet=True)
    _stamp(con, "purchases", purchase_id, p["date"], "12:00:00")
    for pid, cost in costs.items():
        con.execute("UPDATE products SET avg_cost = ? WHERE id = ?", (cost, pid))
    moved = {}
    for i in items:
        moved[i["product_id"]] = moved.get(i["product_id"], 0) + i["qty"]
    _counted(con, book, moved, f"{p['code']} — {book['after_count']} این کالاها را از قبل داشت")
    report["purchases"] += 1
    report["purchased"] += sum(i["qty"] * i["unit_cost"] for i in items)


def _partner_accounts(con) -> dict[str, int]:
    out = {}
    for key, name in PARTNERS.items():
        row = con.execute("""SELECT a.id FROM accounts a JOIN partners p ON p.id = a.partner_id
                             WHERE a.kind = 'partner' AND p.name = ? ORDER BY a.sort, a.id LIMIT 1""", (name,)).fetchone()
        if row:
            out[key] = row[0]
    return out


def apply(con) -> dict | None:
    result = None
    for book in _plans():
        done = db.get_setting("books_applied", [], con) or []
        counts = db.get_setting("stock_counts_applied", [], con) or []
        if book["label"] in done or book["after_count"] not in counts \
                or not con.execute("SELECT 1 FROM purchases WHERE code = 'PO-1001'").fetchone():
            continue
        report = {"sales": 0, "revenue": 0, "channels": 0, "purchases": 0, "purchased": 0, "expenses": 0,
                  "settlement": 0, "merged": [], "skipped": []}
        pids = {p["sku"]: _product(con, p, book["label"], report) for p in book["products"]}
        accounts = db.get_setting("channel_accounts", {}, con) or {}
        for s in book["sales"]:
            _sale(con, book, s, pids, accounts, report)
        for p in book["purchases"]:
            _purchase(con, book, p, pids, report)

        cards = _partner_accounts(con)
        shop_bank = accounts.get("other")                      # the shop's bank account, as in the first import
        system = {"id": None, "name": book["label"]}
        for e in book["expenses"]:
            if con.execute("SELECT 1 FROM expenses WHERE code = ?", (e["code"],)).fetchone():
                continue
            expense_id = ledger.save_expense(con, {
                "code": e["code"], "date": e["date"], "category": book["categories"].get(e["category"], "سایر"),
                "description": e["description"], "amount": e["amount"],
                "account_id": cards.get(e["paid_by"]) or shop_bank, "is_inventory": e["category"] == "Products",
                "note": " — ".join(filter(None, [e["note"], "از فایل اکسل"])), "quiet": True}, system)
            _stamp(con, "expenses", expense_id, e["date"], "12:00:00")
            report["expenses"] += 1
        for c in book["capital"]:
            partner = con.execute("SELECT id FROM partners WHERE name = ?", (PARTNERS.get(c["paid_by"]),)).fetchone()
            if partner and not con.execute("SELECT 1 FROM capital WHERE date = ? AND amount = ? AND partner_id = ?",
                                           (c["date"], c["amount"], partner[0])).fetchone():
                ledger.save_capital(con, {"date": c["date"], "partner_id": partner[0], "kind": "in", "amount": c["amount"],
                                          "account_id": shop_bank, "note": "از فایل اکسل", "quiet": True}, None)

        # settled rows: what Tina paid Amir in all; the sheet settlements already here count towards it
        target = book["settlement"]["tina_to_amir"]
        if "amir" in cards and "tina" in cards:
            have = con.execute("""SELECT IFNULL(SUM(CASE WHEN from_account = ? THEN amount ELSE -amount END), 0)
                                  FROM transfers WHERE kind = 'settlement' AND note LIKE '%اکسل%'
                                  AND from_account IN (?, ?) AND to_account IN (?, ?)""",
                               (cards["tina"], cards["tina"], cards["amir"], cards["tina"], cards["amir"])).fetchone()[0]
            gap = target - have
            if gap:
                src, dst = ("tina", "amir") if gap > 0 else ("amir", "tina")
                ledger.save_transfer(con, {"date": book["settlement"]["date"], "from_account": cards[src],
                                           "to_account": cards[dst], "amount": abs(gap), "kind": "settlement",
                                           "quiet": True, "note": "تسویه ردیف‌های «Settled» فایل اکسل"}, None)
                report["settlement"] = gap

        db.set_setting("books_applied", [*done, book["label"]], con)
        body = (f"{ledger.fa(report['sales'])} فروش ({ledger.toman(report['revenue'])})، "
                f"{ledger.fa(report['purchases'])} خرید ({ledger.toman(report['purchased'])})، "
                f"{ledger.fa(report['expenses'])} هزینه"
                + (f"، کانال {ledger.fa(report['channels'])} فروش اصلاح شد" if report["channels"] else "")
                + (f"، سوابق {ledger.fa(len(report['merged']))} محصول یکی شد" if report["merged"] else "")
                + ". موجودی همان شمارش ۱ آبان ماند."
                + (f" دوباره ثبت نشد: {'، '.join(report['skipped'][:5])}" if report["skipped"] else ""))
        notify.activity(con, "import", f"📥 {book['label']} ثبت شد", body, level="success", link="#/erp/sales",
                        notify=True)
        result = {"label": book["label"], **report}
    return result


def apply_shipped() -> None:
    """At startup: apply a shipped book that is waiting. A failure leaves everything as it was (one transaction)."""
    try:
        with db.tx() as con:
            report = apply(con)
        if report:
            log.info("books applied: %s", report)
    except Exception:                                              # never keep the app from starting
        log.exception("applying the shipped books failed")
