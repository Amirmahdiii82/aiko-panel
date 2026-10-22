"""Business rules: stock, sales, purchases, expenses and money.

Stock is a ledger: every change is a row in `stock_moves` and `products.stock` is its running total.
Cost of goods uses the weighted average landed cost (purchase price + share of shipping).

Money is tracked per account (a partner's personal card, the site gateway, the cash box, a friend who
sold for you, ...). A partner's stake in the shop is what they paid in minus what they hold of the
shop's money; the settlement tells partners how to even out their stakes by ownership share.
"""
from ...core.text import fa, toman
from . import db, notify

CHANNELS = {
    "website": "سایت",
    "instagram": "دایرکت / اینستاگرام",
    "in_person": "حضوری",
    "agent": "نماینده / دوستان",
    "other": "سایر",
}


# Set by the WooCommerce module: called after a commit that changed stock of a linked product
sync_wake = None


class LedgerError(ValueError):
    """A user-facing validation error (message is shown as-is)."""


def _int(value, field: str, minimum: int | None = 0) -> int:
    try:
        v = int(round(float(value or 0)))
    except (TypeError, ValueError):
        raise LedgerError(f"مقدار «{field}» عدد نیست")
    if minimum is not None and v < minimum:
        raise LedgerError(f"مقدار «{field}» نمی‌تواند کمتر از {fa(minimum)} باشد")
    return v


def _date(value) -> str:
    value = (value or "").strip()[:10]
    if not value:
        return db.today()
    try:
        from datetime import date
        date.fromisoformat(value)
    except ValueError:
        raise LedgerError("تاریخ نامعتبر است")
    return value


def _wake_sync() -> None:
    if sync_wake:
        sync_wake()


# ---------------------------------------------------------------- products & stock

def get_product(con, product_id: int) -> dict:
    p = db.one(con.execute("SELECT * FROM products WHERE id = ?", (product_id,)))
    if not p:
        raise LedgerError("محصول پیدا نشد")
    return p


def next_sku(con) -> str:
    rows = con.execute("SELECT sku FROM products WHERE sku LIKE 'PRD-%'").fetchall()
    nums = [int(r[0][4:]) for r in rows if r[0][4:].isdigit()]
    return f"PRD-{(max(nums) if nums else 0) + 1:03d}"


def create_product(con, data: dict, user_id: int | None = None, *, quiet: bool = False) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise LedgerError("نام محصول را وارد کنید")
    sku = (data.get("sku") or "").strip() or next_sku(con)
    if con.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone():
        raise LedgerError(f"کد {sku} قبلاً استفاده شده")
    low = db.get_setting("shop", {}, con).get("low_stock", 2)
    cur = con.execute(
        """INSERT INTO products (sku, name, brand, category, price, avg_cost, stock, low_stock, woo_id, woo_variation_id,
                                 woo_name, woo_url, image, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sku, name, (data.get("brand") or "").strip() or None, (data.get("category") or "").strip() or None,
         _int(data.get("price"), "قیمت فروش"), float(data.get("avg_cost") or 0),
         _int(data.get("low_stock", low), "حد هشدار"), data.get("woo_id") or None, data.get("woo_variation_id") or None,
         data.get("woo_name"), data.get("woo_url"), data.get("image"), (data.get("notes") or "").strip() or None,
         db.now(), db.now()))
    pid = cur.lastrowid
    opening = _int(data.get("stock"), "موجودی اولیه", minimum=None)
    if opening:
        add_move(con, pid, opening, "opening", unit_cost=float(data.get("avg_cost") or 0), note="موجودی اولیه",
                 user_id=user_id, quiet=True)
    if not quiet:
        notify.activity(con, "product", f"محصول جدید: {name}", user_id=user_id, link=f"#/erp/products/{pid}")
    return pid


PRODUCT_FIELDS = ("name", "brand", "category", "price", "low_stock", "notes", "avg_cost", "sku", "active")


def update_product(con, product_id: int, data: dict, user_id: int | None = None) -> None:
    p = get_product(con, product_id)
    sets, args = [], []
    for field in PRODUCT_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field in ("price", "low_stock"):
            value = _int(value, field)
        elif field == "avg_cost":
            value = float(value or 0)
        elif field == "active":
            value = 1 if value else 0
        elif field == "name":
            value = (value or "").strip()
            if not value:
                raise LedgerError("نام محصول را وارد کنید")
        elif field == "sku":
            value = (value or "").strip() or p["sku"]
            if value != p["sku"] and con.execute("SELECT 1 FROM products WHERE sku = ?", (value,)).fetchone():
                raise LedgerError(f"کد {value} قبلاً استفاده شده")
        else:
            value = (value or "").strip() or None
        sets.append(f"{field} = ?")
        args.append(value)
    if not sets:
        return
    con.execute(f"UPDATE products SET {', '.join(sets)}, updated_at = ? WHERE id = ?", (*args, db.now(), product_id))
    if "avg_cost" in data:
        fill_missing_costs(con, [product_id])
    notify.publish_after(con, {"type": "refresh", "scope": "products"})


def add_move(con, product_id: int, qty: int, kind: str, *, unit_cost: float | None = None, ref_type: str | None = None,
             ref_id: int | None = None, note: str | None = None, user_id: int | None = None, quiet: bool = False) -> dict:
    p = get_product(con, product_id)
    before, after = p["stock"], p["stock"] + qty
    avg = p["avg_cost"]
    if qty > 0 and unit_cost is not None:
        base = max(before, 0)
        avg = (base * avg + qty * unit_cost) / (base + qty)
    con.execute(
        """INSERT INTO stock_moves (product_id, qty, kind, unit_cost, ref_type, ref_id, note, user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (product_id, qty, kind, unit_cost, ref_type, ref_id, note, user_id, db.now()))
    linked = p["woo_id"] is not None
    con.execute("UPDATE products SET stock = ?, avg_cost = ?, woo_state = CASE WHEN ? THEN 'pending' ELSE woo_state END,"
                " updated_at = ? WHERE id = ?", (after, avg, 1 if linked else 0, db.now(), product_id))
    if not quiet:
        _stock_alerts(con, p, before, after, user_id)
    notify.publish_after(con, {"type": "product", "id": product_id, "stock": after,
                               "woo_state": "pending" if linked else p["woo_state"]})
    if linked and _wake_sync not in con.after_commit:
        con.after_commit.append(_wake_sync)
    return {**p, "stock": after, "avg_cost": avg}


def _site_note(con, p: dict) -> str:
    if p["woo_id"] is None:
        return "این محصول به سایت وصل نیست؛ اگر در سایت هست، دستی ناموجودش کنید."
    if (db.get_setting("woo", {}, con) or {}).get("stock_start"):
        return "در سایت هم خودکار به‌روز می‌شود."
    return "همگام‌سازی موجودی با سایت هنوز شروع نشده؛ صفحه «اتصال سایت» را باز کنید."


def _stock_alerts(con, p: dict, before: int, after: int, user_id: int | None) -> None:
    if before > 0 >= after:
        notify.activity(con, "stock_out", f"⛔ «{p['name']}» تمام شد",
                        f"موجودی: {fa(after)}. {_site_note(con, p)}", user_id=user_id, level="danger",
                        link=f"#/erp/products/{p['id']}", notify=True, bot="on_stock_out")
    elif before > p["low_stock"] >= after > 0:
        notify.activity(con, "low_stock", f"⚠️ «{p['name']}» رو به اتمام است",
                        f"فقط {fa(after)} عدد مانده.", user_id=user_id, level="warning",
                        link=f"#/erp/products/{p['id']}", notify=True, bot="on_low_stock")


def recompute_product(con, product_id: int) -> None:
    """Rebuild stock and average cost from the move history (after a purchase is voided)."""
    stock, avg = 0, 0.0
    for m in con.execute("SELECT qty, unit_cost FROM stock_moves WHERE product_id = ? ORDER BY id", (product_id,)):
        if m["qty"] > 0 and m["unit_cost"] is not None:
            base = max(stock, 0)
            avg = (base * avg + m["qty"] * m["unit_cost"]) / (base + m["qty"])
        stock += m["qty"]
    p = get_product(con, product_id)
    linked = p["woo_id"] is not None
    con.execute("UPDATE products SET stock = ?, avg_cost = ?, woo_state = CASE WHEN ? THEN 'pending' ELSE woo_state END,"
                " updated_at = ? WHERE id = ?", (stock, avg, 1 if linked else 0, db.now(), product_id))
    notify.publish_after(con, {"type": "product", "id": product_id, "stock": stock})
    if linked and _wake_sync not in con.after_commit:
        con.after_commit.append(_wake_sync)


def adjust_stock(con, product_id: int, *, set_to: int | None = None, delta: int | None = None, reason: str = "",
                 user: dict) -> dict:
    p = get_product(con, product_id)
    qty = (set_to - p["stock"]) if set_to is not None else (delta or 0)
    if qty == 0:
        return p
    note = reason.strip() or ("ناموجود کردن" if set_to == 0 else "اصلاح موجودی")
    unit_cost = p["avg_cost"] if qty > 0 else None
    result = add_move(con, product_id, qty, "adjust", unit_cost=unit_cost, note=note, user_id=user["id"])
    sign = "+" if qty > 0 else "−"
    notify.activity(con, "adjust", f"اصلاح موجودی «{p['name']}»",
                    f"{sign}{fa(abs(qty))} ← موجودی جدید {fa(result['stock'])} ({note}) توسط {user['name']}",
                    user_id=user["id"], link=f"#/erp/products/{product_id}")
    return result


def split_product(con, product_id: int, variants: list[dict], user: dict) -> list[int]:
    """Turn one product into one product per WooCommerce variation (e.g. per color), moving the stock."""
    p = get_product(con, product_id)
    if not variants:
        raise LedgerError("حداقل یک رنگ/مدل انتخاب کنید")
    total = sum(_int(v.get("qty"), "تعداد") for v in variants)
    con.execute("UPDATE products SET active = 0, woo_id = NULL, woo_variation_id = NULL, woo_state = NULL,"
                " updated_at = ? WHERE id = ?", (db.now(), product_id))
    if p["stock"]:
        add_move(con, product_id, -p["stock"], "split", note="تفکیک به رنگ‌ها", user_id=user["id"], quiet=True)
    new_ids = []
    for i, v in enumerate(variants, 1):
        name = (v.get("name") or "").strip() or f"{p['name']} — {i}"
        sku = f"{p['sku']}-{i}" if p["sku"] else None
        if sku and con.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone():
            sku = None
        pid = create_product(con, {
            "name": name, "brand": p["brand"], "category": p["category"],
            "price": v.get("price") or p["price"], "avg_cost": p["avg_cost"], "low_stock": min(p["low_stock"], 1),
            "woo_id": p["woo_id"] if v.get("woo_variation_id") else None,
            "woo_variation_id": v.get("woo_variation_id"), "woo_name": v.get("woo_name"),
            "woo_url": p["woo_url"], "image": v.get("image") or p["image"],
            "sku": sku,
        }, user["id"], quiet=True)
        qty = _int(v.get("qty"), "تعداد")
        if qty:
            add_move(con, pid, qty, "split", unit_cost=p["avg_cost"], note=f"از تفکیک {p['sku'] or p['name']}",
                     user_id=user["id"], quiet=True)
        new_ids.append(pid)
    note = "" if total == p["stock"] else f" (مجموع جدید {fa(total)} به‌جای {fa(p['stock'])})"
    notify.activity(con, "split", f"«{p['name']}» به {fa(len(variants))} رنگ/مدل تفکیک شد{note}",
                    user_id=user["id"], link="#/erp/products")
    return new_ids


def fill_missing_costs(con, product_ids: list[int] | None = None) -> int:
    """Sales recorded before a product's purchase cost was known (e.g. site orders of a product that was
    created from the site) have a cost of 0, which would show the whole price as profit. Once the product
    has a cost, give those lines that cost and recompute the cost of goods of their sales.
    Returns how many lines were fixed."""
    where, args = "", []
    if product_ids:
        where = f" AND i.product_id IN ({','.join('?' * len(product_ids))})"
        args = list(product_ids)
    rows = con.execute(
        f"""SELECT i.id, i.sale_id, p.avg_cost FROM sale_items i JOIN products p ON p.id = i.product_id
            WHERE i.unit_cost = 0 AND p.avg_cost > 0{where}""", args).fetchall()
    for r in rows:
        con.execute("UPDATE sale_items SET unit_cost = ? WHERE id = ?", (r["avg_cost"], r["id"]))
    for sale_id in {r["sale_id"] for r in rows}:
        con.execute("""UPDATE sales SET cogs = (SELECT IFNULL(SUM(qty * unit_cost), 0) FROM sale_items WHERE sale_id = ?)
                       WHERE id = ?""", (sale_id, sale_id))
    if rows:
        notify.publish_after(con, {"type": "refresh", "scope": "sales"})
    return len(rows)


def missing_costs(con, start: str = "2000-01-01", end: str = "2100-01-01") -> dict:
    """Sold lines whose cost is unknown (0): their profit is overstated until the cost is entered."""
    r = con.execute(
        """SELECT COUNT(*) AS lines, IFNULL(SUM(i.line_total - i.discount), 0) AS revenue,
                  COUNT(DISTINCT IFNULL(i.product_id, -i.id)) AS products
           FROM sale_items i JOIN sales s ON s.id = i.sale_id
           WHERE s.status = 'done' AND i.unit_cost = 0 AND s.date BETWEEN ? AND ?""", (start, end)).fetchone()
    stock = con.execute("SELECT COUNT(*) FROM products WHERE active = 1 AND avg_cost = 0 AND stock > 0").fetchone()[0]
    return {"lines": r["lines"], "revenue": int(r["revenue"]), "products": r["products"], "stock_products": stock}


def merge_products(con, source_id: int, target_id: int, user: dict) -> None:
    """Two records of the same item (e.g. one from the old sheet, one created from the site): move every
    sale, purchase and stock move of `source` to `target`, rebuild target's stock and cost, retire source."""
    if source_id == target_id:
        raise LedgerError("یک محصول را نمی‌توان با خودش ادغام کرد")
    src, dst = get_product(con, source_id), get_product(con, target_id)
    for table in ("stock_moves", "sale_items", "purchase_items"):
        con.execute(f"UPDATE {table} SET product_id = ? WHERE product_id = ?", (target_id, source_id))
    link = {}
    if dst["woo_id"] is None and src["woo_id"] is not None:
        link = {"woo_id": src["woo_id"], "woo_variation_id": src["woo_variation_id"], "woo_name": src["woo_name"],
                "woo_url": src["woo_url"], "woo_stock": src["woo_stock"]}
    con.execute("""UPDATE products SET active = 0, stock = 0, woo_id = NULL, woo_variation_id = NULL, woo_state = NULL,
                   notes = TRIM(IFNULL(notes, '') || ' ' || ?), updated_at = ? WHERE id = ?""",
                (f"[ادغام شد در {dst['sku'] or dst['name']}]", db.now(), source_id))
    if link:
        con.execute("""UPDATE products SET woo_id = ?, woo_variation_id = ?, woo_name = ?, woo_url = ?, woo_stock = ?
                       WHERE id = ?""", (*link.values(), target_id))
    con.execute("""UPDATE products SET site_created = 0, image = COALESCE(image, ?), brand = COALESCE(brand, ?),
                   category = COALESCE(category, ?) WHERE id = ?""", (src["image"], src["brand"], src["category"], target_id))
    recompute_product(con, target_id)
    fill_missing_costs(con, [target_id])
    notify.activity(con, "merge", f"«{src['name']}» با «{dst['name']}» ادغام شد",
                    "همه فروش‌ها، خریدها و موجودی به یک محصول منتقل شد.", user_id=user["id"],
                    link=f"#/erp/products/{target_id}")
    notify.publish_after(con, {"type": "refresh", "scope": "products"})


def delete_sale(con, sale_id: int) -> list[dict]:
    """Remove a sale as if it was never recorded (used when the site's exact order replaces a copy that was
    typed in by hand or came from the sheet). Returns its items so their costs can be kept."""
    items = db.rows(con.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)))
    pids = {r[0] for r in con.execute(
        "SELECT DISTINCT product_id FROM stock_moves WHERE ref_type = 'sale' AND ref_id = ?", (sale_id,))}
    con.execute("DELETE FROM stock_moves WHERE ref_type = 'sale' AND ref_id = ?", (sale_id,))
    con.execute("DELETE FROM expenses WHERE sale_id = ?", (sale_id,))
    con.execute("DELETE FROM sale_items WHERE sale_id = ?", (sale_id,))
    con.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
    for pid in pids:
        recompute_product(con, pid)
    return items


# ---------------------------------------------------------------- sales

def _items_summary(items: list[dict], stocks: dict[int, int]) -> str:
    lines = []
    for it in items:
        left = ""
        if it.get("product_id") in stocks:
            s = stocks[it["product_id"]]
            left = " — تمام شد ⛔" if s <= 0 else f" — مانده {fa(s)}"
        lines.append(f"{fa(it['qty'])}× {it['name']}{left}")
    return "\n".join(lines)


def create_sale(con, data: dict, user: dict | None, *, quiet: bool = False, legacy: bool = False) -> int:
    items_in = data.get("items") or []
    if not items_in:
        raise LedgerError("حداقل یک محصول به فروش اضافه کنید")
    channel = data.get("channel") or "in_person"
    if channel not in CHANNELS:
        raise LedgerError("کانال فروش نامعتبر است")
    seller_id = data.get("seller_id") or (user["id"] if user else None)
    seller = db.one(con.execute("SELECT id, name, role, account_id, commission_pct FROM users WHERE id = ?",
                                (seller_id,))) if seller_id else None

    items = []
    for raw in items_in:
        qty = _int(raw.get("qty"), "تعداد", minimum=1)
        price = _int(raw.get("unit_price"), "قیمت")
        # an exact line amount (e.g. from a site order) wins over qty × rounded unit price
        line_total = _int(raw["line_total"], "مبلغ ردیف") if raw.get("line_total") is not None else qty * price
        line_discount = _int(raw.get("discount"), "تخفیف ردیف")
        pid = raw.get("product_id")
        if pid:
            p = get_product(con, int(pid))
            unit_cost = float(raw["unit_cost"]) if raw.get("unit_cost") is not None else p["avg_cost"]
            name = (raw.get("name") or "").strip() if raw.get("keep_name") else p["name"]
            items.append({"product_id": p["id"], "name": name or p["name"], "qty": qty, "unit_price": price,
                          "unit_cost": unit_cost, "line_total": line_total, "discount": line_discount})
        else:
            name = (raw.get("name") or "").strip() or "محصول نامشخص"
            items.append({"product_id": None, "name": name, "qty": qty, "unit_price": price,
                          "unit_cost": float(raw.get("unit_cost") or 0), "line_total": line_total,
                          "discount": line_discount})

    subtotal = sum(i["line_total"] for i in items)
    if data.get("discount") in (None, "") and any(i["discount"] for i in items):
        discount = sum(i["discount"] for i in items)
    else:
        discount = _int(data.get("discount"), "تخفیف")
    shipping = _int(data.get("shipping"), "هزینه ارسال")
    if "total" in data and data["total"] not in (None, ""):
        total = _int(data["total"], "مبلغ کل")
    else:
        total = subtotal - discount + shipping
    if total < 0:
        raise LedgerError("تخفیف از مبلغ فروش بیشتر است")
    cogs = sum(i["qty"] * i["unit_cost"] for i in items)
    commission = 0
    if seller and seller["commission_pct"] and not legacy:
        commission = int(round((subtotal - discount) * seller["commission_pct"] / 100))
    account_id = data.get("account_id") or None
    paid = 1 if data.get("paid", True) else 0

    source = data.get("source") or ("site" if data.get("woo_order_id") else "manual")
    cur = con.execute(
        """INSERT INTO sales (code, date, channel, seller_id, customer_name, customer_phone, subtotal, discount, shipping,
                              total, cogs, commission, paid, account_id, status, woo_order_id, woo_status, note,
                              refunded, fees, tax, source, receipt, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.get("code"), _date(data.get("date")), channel, seller_id, (data.get("customer_name") or "").strip() or None,
         (data.get("customer_phone") or "").strip() or None, subtotal, discount, shipping, total, cogs, commission,
         paid, account_id, data.get("woo_order_id"), data.get("woo_status"), (data.get("note") or "").strip() or None,
         _int(data.get("refunded"), "مبلغ برگشتی"), _int(data.get("fees"), "کارمزد", minimum=None),
         _int(data.get("tax"), "مالیات"), source, (data.get("receipt") or "").strip() or None,
         user["id"] if user else None, db.now(), db.now()))
    sale_id = cur.lastrowid
    if not data.get("code"):
        con.execute("UPDATE sales SET code = ? WHERE id = ?", (f"S-{sale_id}", sale_id))

    stocks = {}
    for it in items:
        con.execute("""INSERT INTO sale_items (sale_id, product_id, name, qty, unit_price, unit_cost, line_total, discount)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sale_id, it["product_id"], it["name"], it["qty"], it["unit_price"], it["unit_cost"], it["line_total"],
                     it["discount"]))
        if it["product_id"]:
            res = add_move(con, it["product_id"], -it["qty"], "sale", ref_type="sale", ref_id=sale_id,
                           user_id=user["id"] if user else None, quiet=quiet)
            stocks[it["product_id"]] = res["stock"]

    if commission:
        com_account = (seller and seller["account_id"]) or account_id
        con.execute("""INSERT INTO expenses (code, date, category, description, amount, account_id, sale_id, created_by, created_at)
                       VALUES (?, ?, 'پورسانت فروش', ?, ?, ?, ?, ?, ?)""",
                    (f"COM-{sale_id}", _date(data.get("date")), f"پورسانت {seller['name']} برای فروش S-{sale_id}",
                     commission, com_account, sale_id, user["id"] if user else None, db.now()))

    if not quiet:
        who = f" توسط {seller['name']}" if seller and channel != "website" else ""
        cust = f" — {data.get('customer_name')}" if data.get("customer_name") else ""
        title = f"🛍 فروش جدید ({CHANNELS[channel]}){who}"
        body = f"{_items_summary(items, stocks)}\nجمع: {toman(total)}{cust}"
        if not paid:
            body += "\n(هنوز پرداخت نشده)"
        notify.activity(con, "sale", title, body, user_id=user["id"] if user else None, level="success",
                        link=f"#/erp/sales/{sale_id}", notify=True,
                        bot="on_web_order" if channel == "website" else "on_sale")
    notify.publish_after(con, {"type": "refresh", "scope": "sales"})
    return sale_id


def void_sale(con, sale_id: int, user: dict | None, reason: str = "") -> None:
    sale = db.one(con.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)))
    if not sale:
        raise LedgerError("فروش پیدا نشد")
    if sale["status"] == "void":
        return
    con.execute("UPDATE sales SET status = 'void', note = TRIM(IFNULL(note, '') || ' ' || ?), updated_at = ? WHERE id = ?",
                (f"[ابطال: {reason}]" if reason else "[ابطال]", db.now(), sale_id))
    for it in con.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall():
        if it["product_id"]:
            add_move(con, it["product_id"], it["qty"], "sale_void", unit_cost=it["unit_cost"], ref_type="sale",
                     ref_id=sale_id, note="برگشت/ابطال فروش", user_id=user["id"] if user else None, quiet=True)
    con.execute("DELETE FROM expenses WHERE sale_id = ?", (sale_id,))
    who = user["name"] if user else "سایت"
    notify.activity(con, "sale_void", f"↩️ فروش {sale['code']} باطل شد",
                    f"{toman(sale['total'])} — کالاها به انبار برگشت. ({who}{'، ' + reason if reason else ''})",
                    user_id=user["id"] if user else None, level="warning", link=f"#/erp/sales/{sale_id}", notify=True)
    notify.publish_after(con, {"type": "refresh", "scope": "sales"})


SALE_META = ("date", "channel", "customer_name", "customer_phone", "paid", "account_id", "note", "seller_id")


def update_sale(con, sale_id: int, data: dict, user: dict) -> None:
    sale = db.one(con.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)))
    if not sale:
        raise LedgerError("فروش پیدا نشد")
    sets, args = [], []
    for field in SALE_META:
        if field not in data:
            continue
        value = data[field]
        if field == "date":
            value = _date(value)
        elif field == "paid":
            value = 1 if value else 0
        elif field == "channel" and value not in CHANNELS:
            raise LedgerError("کانال فروش نامعتبر است")
        elif field in ("account_id", "seller_id"):
            value = int(value) if value else None
        elif isinstance(value, str):
            value = value.strip() or None
        sets.append(f"{field} = ?")
        args.append(value)
    if sets:
        con.execute(f"UPDATE sales SET {', '.join(sets)}, updated_at = ? WHERE id = ?", (*args, db.now(), sale_id))
        if "date" in data:
            con.execute("UPDATE expenses SET date = ? WHERE sale_id = ?", (_date(data["date"]), sale_id))
        notify.publish_after(con, {"type": "refresh", "scope": "sales"})


# ---------------------------------------------------------------- purchases

def create_purchase(con, data: dict, user: dict | None, *, quiet: bool = False) -> int:
    items_in = data.get("items") or []
    if not items_in:
        raise LedgerError("حداقل یک قلم کالا وارد کنید")
    lines = []
    for raw in items_in:
        qty = _int(raw.get("qty"), "تعداد", minimum=1)
        unit_cost = float(raw.get("unit_cost") or 0)
        if unit_cost < 0:
            raise LedgerError("قیمت خرید نمی‌تواند منفی باشد")
        pid = raw.get("product_id")
        if not pid:
            new = raw.get("new_product") or {}
            pid = create_product(con, {**new, "avg_cost": unit_cost}, user["id"] if user else None, quiet=True)
        else:
            get_product(con, int(pid))
        lines.append({"product_id": int(pid), "qty": qty, "unit_cost": unit_cost, "line_total": int(round(qty * unit_cost))})
    subtotal = sum(l["line_total"] for l in lines)
    shipping = _int(data.get("shipping"), "هزینه حمل")
    total = subtotal + shipping
    cur = con.execute(
        """INSERT INTO purchases (code, date, supplier, subtotal, shipping, total, account_id, receipt, note, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.get("code"), _date(data.get("date")), (data.get("supplier") or "").strip() or None, subtotal, shipping,
         total, data.get("account_id") or None, data.get("receipt"), (data.get("note") or "").strip() or None,
         user["id"] if user else None, db.now()))
    purchase_id = cur.lastrowid
    if not data.get("code"):
        con.execute("UPDATE purchases SET code = ? WHERE id = ?", (f"P-{purchase_id}", purchase_id))
    for l in lines:
        share = (shipping * l["line_total"] / subtotal) if subtotal else (shipping / len(lines))
        landed = l["unit_cost"] + share / l["qty"]
        con.execute("""INSERT INTO purchase_items (purchase_id, product_id, qty, unit_cost, landed_cost, line_total)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (purchase_id, l["product_id"], l["qty"], l["unit_cost"], landed, l["line_total"]))
        add_move(con, l["product_id"], l["qty"], "purchase", unit_cost=landed, ref_type="purchase", ref_id=purchase_id,
                 user_id=user["id"] if user else None, quiet=True)
    fill_missing_costs(con, [l["product_id"] for l in lines])
    if not quiet:
        supplier = f" از {data.get('supplier')}" if data.get("supplier") else ""
        notify.activity(con, "purchase", f"📦 خرید کالا{supplier}",
                        f"{fa(sum(l['qty'] for l in lines))} عدد در {fa(len(lines))} قلم — {toman(total)}",
                        user_id=user["id"] if user else None, link=f"#/erp/purchases/{purchase_id}")
    notify.publish_after(con, {"type": "refresh", "scope": "purchases"})
    return purchase_id


def void_purchase(con, purchase_id: int, user: dict) -> None:
    pur = db.one(con.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)))
    if not pur:
        raise LedgerError("خرید پیدا نشد")
    if pur["status"] == "void":
        return
    con.execute("UPDATE purchases SET status = 'void' WHERE id = ?", (purchase_id,))
    pids = [r[0] for r in con.execute(
        "SELECT DISTINCT product_id FROM stock_moves WHERE ref_type = 'purchase' AND ref_id = ?", (purchase_id,))]
    con.execute("DELETE FROM stock_moves WHERE ref_type = 'purchase' AND ref_id = ?", (purchase_id,))
    for pid in pids:
        recompute_product(con, pid)
    notify.activity(con, "purchase_void", f"خرید {pur['code']} باطل شد",
                    f"{toman(pur['total'])} — موجودی و میانگین قیمت تمام‌شده دوباره محاسبه شد. ({user['name']})",
                    user_id=user["id"], level="warning", link=f"#/erp/purchases/{purchase_id}")
    notify.publish_after(con, {"type": "refresh", "scope": "purchases"})


# ---------------------------------------------------------------- expenses, capital, transfers

def save_expense(con, data: dict, user: dict, expense_id: int | None = None) -> int:
    amount = _int(data.get("amount"), "مبلغ", minimum=1)
    category = (data.get("category") or "").strip()
    if not category:
        raise LedgerError("دسته هزینه را انتخاب کنید")
    values = (_date(data.get("date")), category, (data.get("description") or "").strip() or None, amount,
              data.get("account_id") or None, 1 if data.get("is_inventory") else 0, (data.get("note") or "").strip() or None)
    if expense_id:
        old = db.one(con.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)))
        if not old:
            raise LedgerError("هزینه پیدا نشد")
        con.execute("""UPDATE expenses SET date = ?, category = ?, description = ?, amount = ?, account_id = ?,
                       is_inventory = ?, note = ? WHERE id = ?""", (*values, expense_id))
        if "receipt" in data:
            con.execute("UPDATE expenses SET receipt = ? WHERE id = ?", (data.get("receipt"), expense_id))
    else:
        cur = con.execute("""INSERT INTO expenses (date, category, description, amount, account_id, is_inventory, note,
                                                   receipt, code, created_by, created_at)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (*values, data.get("receipt"), data.get("code"), user["id"] if user else None, db.now()))
        expense_id = cur.lastrowid
        if not data.get("code"):
            con.execute("UPDATE expenses SET code = ? WHERE id = ?", (f"E-{expense_id}", expense_id))
        if not data.get("quiet"):
            desc = f" — {data.get('description')}" if data.get("description") else ""
            notify.activity(con, "expense", f"💸 هزینه: {category}{desc}", f"{toman(amount)} ({user['name']})",
                            user_id=user["id"], link=f"#/erp/expenses/{expense_id}")
    notify.publish_after(con, {"type": "refresh", "scope": "expenses"})
    return expense_id


def save_capital(con, data: dict, user: dict | None) -> int:
    amount = _int(data.get("amount"), "مبلغ", minimum=1)
    kind = data.get("kind") or "in"
    if kind not in ("in", "out"):
        raise LedgerError("نوع نامعتبر")
    partner = db.one(con.execute("SELECT * FROM partners WHERE id = ?", (data.get("partner_id"),)))
    if not partner:
        raise LedgerError("شریک را انتخاب کنید")
    cur = con.execute("""INSERT INTO capital (date, partner_id, kind, amount, account_id, note, created_by, created_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                      (_date(data.get("date")), partner["id"], kind, amount, data.get("account_id") or None,
                       (data.get("note") or "").strip() or None, user["id"] if user else None, db.now()))
    if user and not data.get("quiet"):
        verb = "آورده سرمایه" if kind == "in" else "برداشت"
        notify.activity(con, "capital", f"💰 {verb} {partner['name']}", toman(amount), user_id=user["id"], link="#/erp/money")
    notify.publish_after(con, {"type": "refresh", "scope": "money"})
    return cur.lastrowid


def save_transfer(con, data: dict, user: dict | None) -> int:
    amount = _int(data.get("amount"), "مبلغ", minimum=1)
    a, b = data.get("from_account"), data.get("to_account")
    if not a or not b or int(a) == int(b):
        raise LedgerError("حساب مبدأ و مقصد را درست انتخاب کنید")
    kind = data.get("kind") or "transfer"
    cur = con.execute("""INSERT INTO transfers (date, from_account, to_account, amount, kind, note, created_by, created_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                      (_date(data.get("date")), int(a), int(b), amount, kind, (data.get("note") or "").strip() or None,
                       user["id"] if user else None, db.now()))
    if user and not data.get("quiet"):
        names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM accounts WHERE id IN (?, ?)", (a, b))}
        label = {"settlement": "🤝 تسویه شرکا", "handover": "💵 تحویل پول"}.get(kind, "🔁 انتقال وجه")
        notify.activity(con, "transfer", label, f"{names.get(int(a))} ← {names.get(int(b))}: {toman(amount)}",
                        user_id=user["id"], link="#/erp/money", notify=kind != "transfer")
    notify.publish_after(con, {"type": "refresh", "scope": "money"})
    return cur.lastrowid


# ---------------------------------------------------------------- money summaries

def account_balances(con, until: str | None = None) -> list[dict]:
    where = "WHERE date <= ?" if until else ""
    args = (until,) if until else ()
    flows = {r["account_id"]: r for r in con.execute(
        f"""SELECT account_id, SUM(amount) AS balance, SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS money_in,
                   SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS money_out, COUNT(*) AS n
            FROM money_flows {where} GROUP BY account_id""", args)}
    out = []
    for a in con.execute("""SELECT a.*, p.name AS partner_name, u.name AS user_name FROM accounts a
                            LEFT JOIN partners p ON p.id = a.partner_id LEFT JOIN users u ON u.id = a.user_id
                            ORDER BY a.sort, a.id"""):
        f = flows.get(a["id"])
        out.append({**dict(a), "balance": int(f["balance"] or 0) if f else 0,
                    "money_in": int(f["money_in"] or 0) if f else 0, "money_out": int(f["money_out"] or 0) if f else 0,
                    "n": f["n"] if f else 0})
    return out


def partner_positions(con) -> dict:
    """Each partner's net stake, their fair share, and the transfers that would even things out."""
    partners = db.rows(con.execute("SELECT * FROM partners WHERE active = 1 ORDER BY id"))
    balances = account_balances(con)
    cap = {r["partner_id"]: r for r in con.execute(
        """SELECT partner_id, SUM(CASE WHEN kind = 'in' THEN amount ELSE 0 END) AS cin,
                  SUM(CASE WHEN kind = 'out' THEN amount ELSE 0 END) AS cout FROM capital GROUP BY partner_id""")}
    detail = {}
    for row in con.execute(
            """SELECT a.partner_id, f.src, SUM(CASE WHEN f.amount < 0 THEN -f.amount ELSE 0 END) AS paid,
                      SUM(CASE WHEN f.amount > 0 THEN f.amount ELSE 0 END) AS received
               FROM money_flows f JOIN accounts a ON a.id = f.account_id
               WHERE a.kind = 'partner' GROUP BY a.partner_id, f.src"""):
        detail.setdefault(row["partner_id"], {})[row["src"]] = {"paid": int(row["paid"] or 0),
                                                               "received": int(row["received"] or 0)}
    total_share = sum(p["share"] for p in partners) or 1
    result = []
    for p in partners:
        own = [b for b in balances if b["kind"] == "partner" and b["partner_id"] == p["id"]]
        held = sum(b["balance"] for b in own)
        c = cap.get(p["id"])
        cin, cout = (int(c["cin"] or 0), int(c["cout"] or 0)) if c else (0, 0)
        d = detail.get(p["id"], {})
        result.append({
            "id": p["id"], "name": p["name"], "share": p["share"], "color": p["color"],
            "capital_in": cin, "capital_out": cout,
            "paid_expenses": d.get("expense", {}).get("paid", 0) + d.get("purchase", {}).get("paid", 0),
            "received_sales": d.get("sale", {}).get("received", 0),
            "transfers_out": d.get("transfer", {}).get("paid", 0),
            "transfers_in": d.get("transfer", {}).get("received", 0),
            "net": cin - cout - held,
            "accounts": [{"id": b["id"], "name": b["name"], "balance": b["balance"]} for b in own],
        })
    total_net = sum(r["net"] for r in result)
    for r in result:
        r["fair"] = total_net * r["share"] / total_share
        r["excess"] = int(round(r["net"] - r["fair"]))
    # greedy settlement: whoever is short pays whoever is over
    debtors = sorted([dict(r) for r in result if r["excess"] < 0], key=lambda r: r["excess"])
    creditors = sorted([dict(r) for r in result if r["excess"] > 0], key=lambda r: -r["excess"])
    moves = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(-debtors[i]["excess"], creditors[j]["excess"])
        if amount >= 1000:
            moves.append({"from_partner": debtors[i]["id"], "from_name": debtors[i]["name"],
                          "to_partner": creditors[j]["id"], "to_name": creditors[j]["name"], "amount": amount,
                          "from_account": (debtors[i]["accounts"] or [{}])[0].get("id"),
                          "to_account": (creditors[j]["accounts"] or [{}])[0].get("id")})
        debtors[i]["excess"] += amount
        creditors[j]["excess"] -= amount
        if debtors[i]["excess"] >= 0:
            i += 1
        if creditors[j]["excess"] <= 0:
            j += 1
    return {"partners": result, "total_net": total_net, "settlement": moves}


def summary_money(con) -> dict:
    balances = account_balances(con)
    shop = sum(b["balance"] for b in balances if b["kind"] == "shop")
    agents = sum(b["balance"] for b in balances if b["kind"] == "agent")
    receivable = con.execute("SELECT IFNULL(SUM(total), 0) FROM sales WHERE status = 'done' AND paid = 0").fetchone()[0]
    return {"shop_cash": shop, "with_agents": agents, "receivable": int(receivable), "accounts": balances}


def ensure_agent_account(con, user_id: int, name: str) -> int:
    row = con.execute("SELECT id FROM accounts WHERE kind = 'agent' AND user_id = ?", (user_id,)).fetchone()
    if row:
        return row[0]
    cur = con.execute("INSERT INTO accounts (name, kind, user_id, note, sort) VALUES (?, 'agent', ?, ?, 50)",
                      (f"پول نزد {name}", user_id, "پول فروش‌هایی که این فرد انجام داده و هنوز تحویل نداده"))
    return cur.lastrowid
