"""Record a sale or an expense from the owners' bot, step by step, with one confirmation before anything is saved.
Everything goes through the same ledger functions as the panel (stock, cost of goods, site sync, notifications)."""
from datetime import date, timedelta

from ...core.botkit import Reply, fa, norm, parse_amount, parse_int, toman
from . import db, ledger

SALE_CHANNELS = ["in_person", "instagram", "website", "agent", "other"]


def _user(u: dict) -> dict:
    """The ERP view of the panel user (name, staff account) for ledger calls."""
    with db.read() as con:
        row = db.one(con.execute("SELECT id, name, role, account_id FROM users WHERE id = ?", (u["id"],))) or {}
    return {"id": u["id"], "name": row.get("name") or u.get("name") or "", "role": row.get("role") or "admin",
            "account_id": row.get("account_id")}


def _search(text: str, limit: int = 8) -> list[dict]:
    words = [w for w in norm(text).split() if w]
    with db.read() as con:
        rows = db.rows(con.execute("SELECT id, name, sku, stock, price FROM products WHERE active = 1"))
    def key(p):
        return norm(f"{p['name']} {p['sku'] or ''}")
    hits = [p for p in rows if all(w in key(p) for w in words)] if words else []
    hits.sort(key=lambda p: (not key(p).startswith(words[0]) if words else 0, p["stock"] <= 0, p["name"]))
    return hits[:limit]


def _popular(limit: int = 6) -> list[dict]:
    since = (date.fromisoformat(db.today()) - timedelta(days=30)).isoformat()
    with db.read() as con:
        return db.rows(con.execute(
            """SELECT p.id, p.name, p.stock, p.price FROM products p JOIN sale_items i ON i.product_id = p.id
               JOIN sales s ON s.id = i.sale_id WHERE p.active = 1 AND s.status = 'done' AND s.date >= ?
               GROUP BY p.id ORDER BY SUM(i.qty) DESC LIMIT ?""", (since, limit)))


def _product_buttons(rows: list[dict]) -> list[list[tuple[str, str]]]:
    return [[(f"{p['name'][:40]} · موجودی {fa(p['stock'])}", f"p:{p['id']}")] for p in rows]


def _cart_text(items: list[dict]) -> str:
    lines = [f"• {fa(i['qty'])}× {i['name']} — {toman(i['qty'] * i['unit_price'])}" for i in items]
    return "\n".join(lines) + f"\nجمع: {toman(sum(i['qty'] * i['unit_price'] for i in items))}"


class SaleFlow:
    label = "🛍 ثبت فروش"

    def start(self, user, st) -> Reply:
        st.clear()
        st.update(step="product", items=[])
        pop = _popular()
        return Reply("🛍 ثبت فروش\nنام محصول را بنویسید (بخشی از نام کافی است)"
                     + ("، یا از پرفروش‌ها انتخاب کنید:" if pop else ":"), _product_buttons(pop))

    def handle(self, user, st, text=None, data=None) -> Reply:
        step = st.get("step")
        if step == "product":
            if data and data.startswith("p:"):
                return self._pick(st, int(data[2:]))
            hits = _search(text or "")
            if not hits:
                return Reply("محصولی با این نام پیدا نشد. یک کلمه دیگر از نامش را بنویسید:")
            if len(hits) == 1:
                return self._pick(st, hits[0]["id"])
            return Reply("کدام یکی؟", _product_buttons(hits))
        if step == "qty":
            qty = int(data[2:]) if data and data.startswith("q:") else parse_int(text)
            if not qty or qty < 1:
                return Reply("تعداد را با عدد بنویسید (مثلاً ۲):")
            st["cur"]["qty"] = qty
            warn = f"\n⚠️ موجودی فقط {fa(st['cur']['stock'])} عدد است." if qty > st["cur"]["stock"] else ""
            st["step"] = "price"
            p = st["cur"]["price"]
            return Reply(f"قیمت هر عدد؟{warn}\n(اگر فرق دارد، مبلغ را بنویسید؛ مثلاً ۴۸۰ هزار)",
                         [[(f"✅ همان {toman(p)}", "pr:default")]] if p else [])
        if step == "price":
            price = st["cur"]["price"] if data == "pr:default" else parse_amount(text)
            if price is None or price < 0:
                return Reply("مبلغ را با عدد بنویسید (مثلاً ۴۸۰۰۰۰ یا ۴۸۰ هزار):")
            cur = st.pop("cur")
            st["items"].append({"product_id": cur["id"], "name": cur["name"], "qty": cur["qty"], "unit_price": price})
            st["step"] = "more"
            return Reply(f"سبد:\n{_cart_text(st['items'])}", [[("➕ محصول دیگر", "more"), ("✔️ ادامه", "next")]])
        if step == "more":
            if data == "more":
                st["step"] = "product"
                return Reply("نام محصول بعدی را بنویسید:", _product_buttons(_popular()))
            st["step"] = "channel"
            return Reply("از کدام کانال فروخته شد؟",
                         [[(ledger.CHANNELS[c], f"ch:{c}") for c in SALE_CHANNELS[i:i + 2]] for i in range(0, len(SALE_CHANNELS), 2)])
        if step == "channel":
            if not (data and data.startswith("ch:")):
                return Reply("یکی از دکمه‌ها را بزنید.")
            st["channel"] = data[3:]
            st["step"] = "customer"
            return Reply("نام مشتری؟ (اختیاری)", [[("رد کردن", "skip")]])
        if step == "customer":
            st["customer"] = "" if data == "skip" else (text or "").strip()[:80]
            return self._confirm(st)
        if step == "discount":
            amount = parse_amount(text)
            if amount is None:
                return Reply("مبلغ تخفیف را با عدد بنویسید (مثلاً ۵۰ هزار):")
            st["discount"] = amount
            return self._confirm(st)
        if step == "confirm":
            if data == "discount":
                st["step"] = "discount"
                return Reply("مبلغ کل تخفیف این فروش؟")
            if data == "unpaid":
                st["paid"] = not st.get("paid", True)
                return self._confirm(st)
            if data == "save":
                return self._save(user, st)
        return Reply("یکی از دکمه‌ها را بزنید.")

    def _pick(self, st, pid: int) -> Reply:
        with db.read() as con:
            p = ledger.get_product(con, pid)
        st["cur"] = {"id": p["id"], "name": p["name"], "stock": p["stock"], "price": p["price"]}
        st["step"] = "qty"
        stock = f"موجودی: {fa(p['stock'])}" if p["stock"] > 0 else "⛔️ این محصول ناموجود است"
        return Reply(f"«{p['name']}»\n{stock}\nچند عدد؟", [[(fa(n), f"q:{n}") for n in range(1, 6)]])

    def _confirm(self, st) -> Reply:
        st["step"] = "confirm"
        st.setdefault("paid", True)
        subtotal = sum(i["qty"] * i["unit_price"] for i in st["items"])
        discount = st.get("discount", 0)
        lines = ["لطفاً بررسی کنید:", _cart_text(st["items"])]
        if discount:
            lines.append(f"تخفیف: −{toman(discount)}\nمبلغ نهایی: {toman(subtotal - discount)}")
        lines.append(f"کانال: {ledger.CHANNELS[st['channel']]}" + (f"\nمشتری: {st['customer']}" if st.get("customer") else ""))
        lines.append("پول دریافت شده ✅" if st["paid"] else "⏳ هنوز پرداخت نشده (نسیه)")
        return Reply("\n".join(lines), [[("✅ ثبت فروش", "save")],
                                        [("🏷 تخفیف", "discount"), ("💳 پرداخت شده/نسیه", "unpaid")]])

    def _save(self, user, st) -> Reply:
        u = _user(user)
        account = (db.get_setting("channel_accounts", {}) or {}).get(st["channel"])
        with db.tx() as con:
            sale_id = ledger.create_sale(con, {
                "channel": st["channel"], "customer_name": st.get("customer") or None, "items": st["items"],
                "discount": st.get("discount", 0), "paid": st.get("paid", True), "account_id": account,
                "note": "ثبت از ربات",
            }, u)
            sale = db.one(con.execute("SELECT code, total FROM sales WHERE id = ?", (sale_id,)))
            left = {r["id"]: r["stock"] for r in con.execute(
                f"SELECT id, stock FROM products WHERE id IN ({','.join('?' * len(st['items']))})",
                [i["product_id"] for i in st["items"]])}
        stock = "\n".join(f"• {i['name']}: مانده {fa(left.get(i['product_id'], 0))}" for i in st["items"])
        return Reply(f"✅ فروش {sale['code']} ثبت شد — {toman(sale['total'])}\n{stock}", done=True)


class ExpenseFlow:
    label = "💸 ثبت هزینه"

    def start(self, user, st) -> Reply:
        st.clear()
        st["step"] = "amount"
        return Reply("💸 ثبت هزینه\nمبلغ را بنویسید (مثلاً ۲۵۰ هزار یا ۲۵۰۰۰۰):")

    def handle(self, user, st, text=None, data=None) -> Reply:
        step = st.get("step")
        if step == "amount":
            amount = parse_amount(text)
            if not amount:
                return Reply("مبلغ را با عدد بنویسید (مثلاً ۲۵۰ هزار):")
            st["amount"] = amount
            st["step"] = "category"
            cats = db.get_setting("expense_categories", []) or ["سایر"]
            st["cats"] = cats
            return Reply("دسته هزینه؟", [[(c, f"c:{i}") for i, c in enumerate(cats[j:j + 2], j)] for j in range(0, len(cats), 2)])
        if step == "category":
            if not (data and data.startswith("c:")):
                return Reply("یکی از دسته‌ها را بزنید.")
            st["category"] = st["cats"][int(data[2:])]
            st["step"] = "desc"
            return Reply("توضیح کوتاه؟ (مثلاً «جعبه‌های بسته‌بندی»)", [[("رد کردن", "skip")]])
        if step == "desc":
            st["desc"] = "" if data == "skip" else (text or "").strip()[:120]
            st["step"] = "account"
            u = _user(user)
            with db.read() as con:
                accs = db.rows(con.execute("SELECT id, name FROM accounts WHERE active = 1 ORDER BY sort, id"))
            accs.sort(key=lambda a: a["id"] != u.get("account_id"))       # this owner's own card first
            return Reply("از کدام حساب پرداخت شد؟", [[(a["name"], f"a:{a['id']}")] for a in accs[:8]])
        if step == "account":
            if not (data and data.startswith("a:")):
                return Reply("یکی از حساب‌ها را بزنید.")
            st["account_id"] = int(data[2:])
            with db.read() as con:
                st["account_name"] = (db.one(con.execute("SELECT name FROM accounts WHERE id = ?", (st["account_id"],))) or {}).get("name", "")
            st["step"] = "confirm"
            return Reply(f"لطفاً بررسی کنید:\n💸 {toman(st['amount'])}\nدسته: {st['category']}"
                         + (f"\nتوضیح: {st['desc']}" if st["desc"] else "") + f"\nپرداخت از: {st['account_name']}",
                         [[("✅ ثبت هزینه", "save")]])
        if step == "confirm" and data == "save":
            u = _user(user)
            with db.tx() as con:
                eid = ledger.save_expense(con, {"amount": st["amount"], "category": st["category"],
                                                "description": st["desc"], "account_id": st["account_id"],
                                                "note": "ثبت از ربات"}, u)
                code = con.execute("SELECT code FROM expenses WHERE id = ?", (eid,)).fetchone()[0]
            return Reply(f"✅ هزینه {code} ثبت شد — {toman(st['amount'])} ({st['category']})", done=True)
        return Reply("یکی از دکمه‌ها را بزنید.")


FLOWS = {"sale": SaleFlow(), "expense": ExpenseFlow()}
