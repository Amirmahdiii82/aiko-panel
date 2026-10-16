"""One-time import of the old "Aiko's Inventory.xlsx" workbook.

The workbook kept amounts in thousand Toman (540 = 540,000 Toman); a few cells were typed in full
Toman, so any value of 100,000 or more is taken as already being in Toman.

* Products   -> products (stock is rebuilt from purchases and sales, then checked against the sheet)
* Purchases  -> purchases (payment is not attached: the sheet "Expenses" already holds who paid)
* Sales      -> sales, grouped by Order ID
* Expenses   -> expenses; "Products" rows are stock spending (not running costs), "Investment" rows are
                capital put in by a partner
* The "Settled" status of the expense sheet becomes one balancing settlement, so the partner balance
  here matches the sheet.
"""
from datetime import date, datetime

from . import db, ledger, notify

CATEGORY = {"Lips": "لب", "Face": "صورت", "Eyes": "چشم", "Hair": "مو", "Body": "بدن", "Tools": "ابزار و براش"}
EXPENSE_CATEGORY = {
    "Website & Domain": "سایت و دامنه", "Tax & License": "مالیات و مجوز", "Software & Tools": "نرم‌افزار و ابزار",
    "Packaging": "بسته‌بندی", "Shipping Supplies": "حمل و رفت‌وآمد", "Dishes": "پذیرایی",
    "Marketing": "تبلیغات و بازاریابی", "Products": "خرید کالا",
}
CHANNEL = {"website": "website", "direct": "instagram", "instagram": "instagram", "in person": "in_person"}
PARTNER = {"amir": 1, "tina": 2}
PARTNER_ACCOUNT = {1: 1, 2: 2}
SHOP_BANK = 4


def toman(v) -> int:
    if v in (None, ""):
        return 0
    v = float(v)
    return int(round(v)) if abs(v) >= 100000 else int(round(v * 1000))


def _iso(v) -> str:
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v or db.today())[:10]


def _sheet_rows(ws, header_first: str) -> list[dict]:
    rows = list(ws.iter_rows(values_only=True))
    for i, r in enumerate(rows):
        cells = [c for c in r if c is not None]
        if cells and str(cells[0]).strip() == header_first:
            start_col = next(j for j, c in enumerate(r) if c is not None)
            headers = [str(h).strip() if h is not None else "" for h in r[start_col:]]
            out = []
            for data in rows[i + 1:]:
                data = data[start_col:]
                if data and data[0] not in (None, ""):
                    out.append({h: v for h, v in zip(headers, data) if h})
            return out
    return []


def run(path: str, user: dict | None = None) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    report = {"products": 0, "purchases": 0, "sales": 0, "expenses": 0, "capital": 0, "stock_mismatch": [],
              "settlement": 0}
    with db.tx() as con:
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0]:
            raise ledger.LedgerError("محصولات قبلاً وارد شده‌اند؛ ایمپورت فقط روی پایگاه‌داده خالی انجام می‌شود.")
        accounts = db.get_setting("channel_accounts", {}, con) or {}

        expected_stock, sku_to_id = {}, {}
        for r in _sheet_rows(wb["Products"], "SKU"):
            sku = str(r["SKU"]).strip()
            pid = ledger.create_product(con, {
                "sku": sku, "name": str(r.get("Product Name") or sku).strip(),
                "brand": r.get("Brand") if r.get("Brand") not in ("Generic", None) else None,
                "category": CATEGORY.get(str(r.get("Category") or "").strip(), r.get("Category")),
                "price": toman(r.get("Unit Price")), "low_stock": 2, "notes": r.get("Notes"),
            }, None, quiet=True)
            sku_to_id[sku] = pid
            expected_stock[pid] = int(r.get("Current Stock") or 0)
            report["products"] += 1

        for r in _sheet_rows(wb["Purchases"], "Purchase ID"):
            pid = sku_to_id.get(str(r.get("SKU") or "").strip())
            if not pid:
                continue
            ledger.create_purchase(con, {
                "code": str(r["Purchase ID"]).strip(), "date": _iso(r.get("Date")), "supplier": r.get("Supplier"),
                "shipping": toman(r.get("Shipping / Fees")), "account_id": None,
                "note": "از فایل اکسل — پرداختش در هزینه‌های «خرید کالا» ثبت است",
                "items": [{"product_id": pid, "qty": int(r.get("Quantity") or 0), "unit_cost": toman(r.get("Unit Cost"))}],
            }, None, quiet=True)
            report["purchases"] += 1

        orders: dict[str, dict] = {}
        for r in _sheet_rows(wb["Sales"], "Order ID"):
            code = str(r["Order ID"]).strip()
            o = orders.setdefault(code, {"code": code, "date": _iso(r.get("Date")),
                                         "channel": CHANNEL.get(str(r.get("Channel") or "").strip().lower(), "other"),
                                         "customer_name": r.get("Customer Name"), "items": []})
            pid = sku_to_id.get(str(r.get("SKU") or "").strip())
            o["items"].append({"product_id": pid, "name": r.get("Product Name"), "qty": int(r.get("Quantity") or 1),
                               "unit_price": toman(r.get("Net Price")), "unit_cost": toman(r.get("Unit COGS"))})
        for o in orders.values():
            o["account_id"] = accounts.get(o["channel"])
            o["note"] = "از فایل اکسل"
            o["source"] = "sheet"
            ledger.create_sale(con, o, None, quiet=True, legacy=True)
            report["sales"] += 1

        unsettled = {1: 0, 2: 0}
        last_settled = None
        for r in _sheet_rows(wb["Expenses"], "Expense ID"):
            category = str(r.get("Category") or "").strip()
            payer = PARTNER.get(str(r.get("Paid By") or "").strip().lower())
            amount = toman(r.get("Amount"))
            day = _iso(r.get("Date"))
            note = " — ".join(filter(None, [str(r.get("Notes") or "").strip(), "از فایل اکسل"]))
            if str(r.get("Status") or "").strip().lower() == "unsettled" and payer:
                unsettled[payer] += amount
            elif payer:
                last_settled = max(last_settled or day, day)
            if category == "Investment":
                ledger.save_capital(con, {"date": day, "partner_id": payer or 1, "kind": "in", "amount": amount,
                                          "account_id": SHOP_BANK, "note": note, "quiet": True}, None)
                report["capital"] += 1
                continue
            ledger.save_expense(con, {
                "code": str(r["Expense ID"]).strip(), "date": day,
                "category": EXPENSE_CATEGORY.get(category, category or "سایر"),
                "description": str(r.get("Description") or "").strip(), "amount": amount,
                "account_id": PARTNER_ACCOUNT.get(payer, SHOP_BANK), "is_inventory": category == "Products",
                "note": note, "quiet": True,
            }, user or {"id": None, "name": "ایمپورت"})
            report["expenses"] += 1

        # Partners evened out everything marked "Settled". One balancing transfer reproduces that.
        target_amir = (unsettled[1] - unsettled[2]) / 2
        current = {p["id"]: p for p in ledger.partner_positions(con)["partners"]}
        gap = int(round(current[1]["excess"] - target_amir)) if 1 in current else 0
        if abs(gap) >= 1:
            src, dst = (2, 1) if gap > 0 else (1, 2)
            ledger.save_transfer(con, {
                "date": last_settled or db.today(), "from_account": PARTNER_ACCOUNT[src], "to_account": PARTNER_ACCOUNT[dst],
                "amount": abs(gap), "kind": "settlement", "quiet": True,
                "note": "تسویه‌های قبلی که در اکسل «Settled» زده شده بودند (محاسبه خودکار برای تطبیق مانده)",
            }, None)
            report["settlement"] = abs(gap)

        # history dates: moves and products take the date of the document that created them
        con.execute("""UPDATE stock_moves SET created_at = (SELECT date FROM purchases WHERE id = ref_id) || 'T12:00:00+03:30'
                       WHERE ref_type = 'purchase'""")
        con.execute("""UPDATE stock_moves SET created_at = (SELECT date FROM sales WHERE id = ref_id) || 'T18:00:00+03:30'
                       WHERE ref_type = 'sale'""")
        con.execute("""UPDATE products SET created_at = IFNULL((SELECT MIN(created_at) FROM stock_moves m
                       WHERE m.product_id = products.id), created_at)""")
        con.execute("UPDATE sales SET created_at = date || 'T18:00:00+03:30', updated_at = date || 'T18:00:00+03:30'")
        con.execute("UPDATE purchases SET created_at = date || 'T12:00:00+03:30'")
        con.execute("UPDATE expenses SET created_at = date || 'T12:00:00+03:30'")

        for pid, expected in expected_stock.items():
            p = ledger.get_product(con, pid)
            if p["stock"] != expected:
                report["stock_mismatch"].append({"sku": p["sku"], "name": p["name"], "excel": expected, "computed": p["stock"]})

        notify.activity(con, "import", "📥 داده‌های فایل اکسل وارد شد",
                        f"{ledger.fa(report['products'])} محصول، {ledger.fa(report['sales'])} فروش، "
                        f"{ledger.fa(report['purchases'])} خرید، {ledger.fa(report['expenses'])} هزینه",
                        user_id=user["id"] if user else None, level="success")
    return report
