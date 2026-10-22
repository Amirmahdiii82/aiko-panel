"""ERP HTTP API (mounted at /api/erp). Login, users, uploads and the live stream are core endpoints."""
import asyncio
import secrets
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from ...core import drive, events
from . import config, db, exporter, importer, ledger, notify, receipts, reports, statements
from .site import client, history, matching, orders, stock
from .deps import Admin, User

router = APIRouter()


# ---------------------------------------------------------------- boot data for the ERP screens

@router.get("/me")
def me(user=User):
    with db.read() as con:
        accounts = db.rows(con.execute("SELECT id, name, kind, partner_id, user_id, active FROM accounts ORDER BY sort, id"))
        partners = db.rows(con.execute("SELECT * FROM partners ORDER BY id"))
        users = db.rows(con.execute("SELECT id, name, role, active FROM users WHERE role != '' ORDER BY id"))
        settings = {k: db.get_setting(k, None, con) for k in
                    ("shop", "product_categories", "expense_categories", "channel_accounts")}
        brands = [r[0] for r in con.execute("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL ORDER BY brand")]
        suppliers = [r[0] for r in con.execute(
            "SELECT DISTINCT supplier FROM purchases WHERE supplier IS NOT NULL ORDER BY supplier")]
    woo_s = client.settings()
    if user["role"] != "admin":
        accounts = [a for a in accounts if a["id"] == user["account_id"]]
        users = [u for u in users if u["id"] == user["id"]]
    return {"user": user, "accounts": accounts, "partners": partners, "users": users,
            "channels": ledger.CHANNELS, "settings": settings, "brands": brands, "suppliers": suppliers,
            "today": db.today(), "site": {"configured": client.configured(woo_s), "started": stock.started(woo_s),
                                          "url": woo_s.get("url")}}


# ---------------------------------------------------------------- staff profiles (commission, partner, default account)

@router.get("/staff")
def staff(user=Admin):
    with db.read() as con:
        return db.rows(con.execute(
            """SELECT u.id, u.username, u.name, u.role, u.active, u.partner_id, u.account_id, u.commission_pct,
                      a.name AS account_name FROM users u LEFT JOIN accounts a ON a.id = u.account_id
               WHERE u.role != '' ORDER BY u.active DESC, u.id"""))


@router.put("/staff/{user_id}")
async def staff_update(user_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        u = db.one(con.execute("SELECT * FROM users WHERE id = ?", (user_id,)))
        if not u or not u["role"]:
            raise HTTPException(404, "این کاربر به حسابداری دسترسی ندارد")
        ledger_profile(con, user_id, u["name"], u["role"], body)
    return {"ok": True}


def ledger_profile(con, user_id: int, name: str, role: str, profile: dict) -> None:
    """Create/update the ERP profile of a user. Sellers always get their own "money held by" account."""
    row = db.one(con.execute("SELECT * FROM staff WHERE user_id = ?", (user_id,))) or {}
    partner_id = profile.get("partner_id", row.get("partner_id"))
    commission = float(profile.get("commission_pct", row.get("commission_pct") or 0) or 0)
    account_id = profile.get("account_id", row.get("account_id"))
    if role == "seller":
        account_id = ledger.ensure_agent_account(con, user_id, name)
        partner_id = None
    con.execute("""INSERT INTO staff (user_id, partner_id, account_id, commission_pct) VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET partner_id = excluded.partner_id, account_id = excluded.account_id,
                   commission_pct = excluded.commission_pct""",
                (user_id, partner_id or None, account_id or None, commission))
    con.execute("UPDATE accounts SET name = ? WHERE kind = 'agent' AND user_id = ?", (f"پول نزد {name}", user_id))





# ---------------------------------------------------------------- dashboard, activity, live stream


@router.get("/dashboard")
def dashboard(user=User):
    with db.read() as con:
        if user["role"] != "admin":
            return seller_home(con, user)
        return reports.dashboard(con, user)


def seller_home(con, user) -> dict:
    today = db.today()
    start = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    sales = db.rows(con.execute(
        """SELECT id, code, date, total, channel, customer_name, status FROM sales
           WHERE seller_id = ? AND date >= ? ORDER BY id DESC LIMIT 30""", (user["id"], start)))
    held = 0
    if user["account_id"]:
        held = con.execute("SELECT IFNULL(SUM(amount), 0) FROM money_flows WHERE account_id = ?",
                           (user["account_id"],)).fetchone()[0]
    month = sum(s["total"] for s in sales if s["status"] == "done")
    commission = con.execute("SELECT IFNULL(SUM(commission), 0) FROM sales WHERE seller_id = ? AND status = 'done' AND date >= ?",
                             (user["id"], start)).fetchone()[0]
    return {"seller": True, "sales": sales, "held": int(held), "month_total": month, "commission": int(commission)}


# ---------------------------------------------------------------- products

SELLER_PRODUCT_FIELDS = ("id", "sku", "name", "brand", "category", "price", "stock", "low_stock", "image", "woo_id",
                         "woo_state", "woo_in_stock", "active", "sold_30")


@router.get("/products")
def products(q: str = "", include_inactive: bool = False, user=User):
    sql = """SELECT p.*,
                    (SELECT IFNULL(SUM(i.qty), 0) FROM sale_items i JOIN sales s ON s.id = i.sale_id
                      WHERE i.product_id = p.id AND s.status = 'done' AND s.date >= date('now', '-30 day')) AS sold_30,
                    (SELECT IFNULL(SUM(i.qty), 0) FROM sale_items i JOIN sales s ON s.id = i.sale_id
                      WHERE i.product_id = p.id AND s.status = 'done') AS sold_total
             FROM products p WHERE 1 = 1"""
    args: list = []
    if not include_inactive:
        sql += " AND p.active = 1"
    if q.strip():
        sql += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.brand LIKE ?)"
        like = f"%{q.strip()}%"
        args += [like, like, like]
    sql += " ORDER BY p.active DESC, p.name"
    with db.read() as con:
        rows = db.rows(con.execute(sql, args))
    if user["role"] != "admin":
        rows = [{k: r[k] for k in SELLER_PRODUCT_FIELDS} for r in rows]
    return rows


@router.get("/products/{product_id}")
def product_detail(product_id: int, user=User):
    with db.read() as con:
        p = ledger.get_product(con, product_id)
        moves = db.rows(con.execute(
            """SELECT m.*, u.name AS user_name,
                      CASE m.ref_type WHEN 'sale' THEN (SELECT code FROM sales WHERE id = m.ref_id)
                                      WHEN 'purchase' THEN (SELECT code FROM purchases WHERE id = m.ref_id) END AS ref_code
               FROM stock_moves m LEFT JOIN users u ON u.id = m.user_id
               WHERE m.product_id = ? ORDER BY m.id DESC LIMIT 150""", (product_id,)))
        stats = db.one(con.execute(
            """SELECT IFNULL(SUM(i.qty), 0) AS qty, IFNULL(SUM(i.line_total), 0) AS revenue,
                      IFNULL(SUM(i.line_total - i.discount - i.qty * i.unit_cost), 0) AS profit, MAX(s.date) AS last_sale
               FROM sale_items i JOIN sales s ON s.id = i.sale_id WHERE i.product_id = ? AND s.status = 'done'""",
            (product_id,)))
    if user["role"] != "admin":
        return {"product": {k: p[k] for k in SELLER_PRODUCT_FIELDS}, "moves": [], "stats": None}
    return {"product": p, "moves": moves, "stats": stats}


@router.post("/products")
async def create_product(request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        pid = ledger.create_product(con, body, user["id"])
    return {"id": pid}


@router.put("/products/{product_id}")
async def update_product(product_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        ledger.update_product(con, product_id, body, user["id"])
    return {"ok": True}


@router.post("/products/{product_id}/adjust")
async def adjust(product_id: int, request: Request, user=Admin):
    body = await request.json()
    set_to = body.get("set_to")
    with db.tx() as con:
        p = ledger.adjust_stock(con, product_id, set_to=int(set_to) if set_to is not None else None,
                                delta=int(body.get("delta") or 0), reason=body.get("reason") or "", user=user)
    return {"stock": p["stock"]}


@router.post("/products/{product_id}/split")
async def split(product_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        ids = ledger.split_product(con, product_id, body.get("variants") or [], user)
    return {"ids": ids}


@router.post("/products/{product_id}/push")
def push_product(product_id: int, user=Admin):
    """Send this product's stock to the site again (after an error)."""
    with db.tx() as con:
        p = ledger.get_product(con, product_id)
        if not p["woo_id"]:
            raise ledger.LedgerError("این محصول به سایت وصل نیست")
        con.execute("UPDATE products SET woo_state = 'pending' WHERE id = ?", (product_id,))
    _push_soon()
    return {"ok": True}


def _push_soon() -> None:
    """Push pending stock now (an explicit user action)."""
    async def run():
        try:
            async with client.sync_lock():
                await stock.push_pending()
        except Exception as exc:  # shown in the site log
            client.wlog("push_stock", False, str(exc))
    events.run_soon(run)


# ---------------------------------------------------------------- sales


@router.get("/sales")
def sales(start: str = "", end: str = "", channel: str = "", q: str = "", status: str = "", seller_id: int = 0,
          unpaid: bool = False, limit: int = 300, user=User):
    sql = """SELECT s.*, u.name AS seller_name, a.name AS account_name,
                    (SELECT GROUP_CONCAT(i.qty || '× ' || i.name, ' ، ') FROM sale_items i WHERE i.sale_id = s.id) AS items_text,
                    (SELECT SUM(i.qty) FROM sale_items i WHERE i.sale_id = s.id) AS items_count
             FROM sales s LEFT JOIN users u ON u.id = s.seller_id LEFT JOIN accounts a ON a.id = s.account_id WHERE 1 = 1"""
    args: list = []
    if start:
        sql += " AND s.date >= ?"
        args.append(start)
    if end:
        sql += " AND s.date <= ?"
        args.append(end)
    if channel:
        sql += " AND s.channel = ?"
        args.append(channel)
    if status:
        sql += " AND s.status = ?"
        args.append(status)
    if unpaid:
        sql += " AND s.paid = 0 AND s.status = 'done'"
    if user["role"] != "admin":
        sql += " AND s.seller_id = ?"
        args.append(user["id"])
    elif seller_id:
        sql += " AND s.seller_id = ?"
        args.append(seller_id)
    if q.strip():
        like = f"%{q.strip()}%"
        sql += """ AND (s.code LIKE ? OR s.customer_name LIKE ? OR s.customer_phone LIKE ? OR s.note LIKE ?
                   OR EXISTS (SELECT 1 FROM sale_items i WHERE i.sale_id = s.id AND i.name LIKE ?))"""
        args += [like] * 5
    sql += " ORDER BY s.date DESC, s.id DESC LIMIT ?"
    args.append(min(limit, 2000))
    with db.read() as con:
        rows = db.rows(con.execute(sql, args))
    if user["role"] != "admin":
        for r in rows:
            r.pop("cogs", None)
    return rows


@router.get("/sales/{sale_id}")
def sale_detail(sale_id: int, user=User):
    with db.read() as con:
        sale = db.one(con.execute(
            """SELECT s.*, u.name AS seller_name, a.name AS account_name, c.name AS created_by_name
               FROM sales s LEFT JOIN users u ON u.id = s.seller_id LEFT JOIN accounts a ON a.id = s.account_id
               LEFT JOIN users c ON c.id = s.created_by WHERE s.id = ?""", (sale_id,)))
        if not sale or (user["role"] != "admin" and sale["seller_id"] != user["id"]):
            raise HTTPException(404, "فروش پیدا نشد")
        items = db.rows(con.execute(
            """SELECT i.*, p.image, p.sku, p.stock FROM sale_items i LEFT JOIN products p ON p.id = i.product_id
               WHERE i.sale_id = ? ORDER BY i.id""", (sale_id,)))
    if user["role"] != "admin":
        sale.pop("cogs", None)
        for i in items:
            i.pop("unit_cost", None)
    return {"sale": sale, "items": items, "drive": drive.link(receipts.ref("sale", sale_id))}


@router.post("/sales")
async def create_sale(request: Request, user=User):
    body = await request.json()
    if user["role"] != "admin":
        today = date.fromisoformat(db.today())
        day = body.get("date") or today.isoformat()
        if not (today - timedelta(days=3)).isoformat() <= day[:10] <= today.isoformat():
            raise HTTPException(400, "فقط فروش‌های سه روز اخیر را می‌توانید ثبت کنید")
        body.update(seller_id=user["id"], account_id=user["account_id"])
        if body.get("channel") not in ("in_person", "instagram", "agent", "other"):
            body["channel"] = "agent"
        body.pop("code", None)
        body.pop("total", None)
        body.pop("woo_order_id", None)
    else:
        body.pop("woo_order_id", None)
        if not body.get("account_id"):
            body["account_id"] = (db.get_setting("channel_accounts", {}) or {}).get(body.get("channel") or "in_person")
    with db.tx() as con:
        sale_id = ledger.create_sale(con, body, user)
    receipts.send("sale", sale_id)
    return {"id": sale_id}


@router.put("/sales/{sale_id}")
async def update_sale(sale_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        ledger.update_sale(con, sale_id, body, user)
    return {"ok": True}


@router.post("/sales/{sale_id}/void")
async def void_sale(sale_id: int, request: Request, user=User):
    body = await request.json()
    with db.tx() as con:
        sale = db.one(con.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)))
        if not sale:
            raise HTTPException(404, "فروش پیدا نشد")
        if user["role"] != "admin":
            # a seller can undo their own sale for 15 minutes (typo, wrong product, ...)
            from datetime import datetime
            age = datetime.now(db.TZ) - datetime.fromisoformat(sale["created_at"])
            if sale["seller_id"] != user["id"] or age > timedelta(minutes=15):
                raise HTTPException(403, "برای ابطال این فروش با مدیر هماهنگ کنید")
        ledger.void_sale(con, sale_id, user, body.get("reason") or "")
    return {"ok": True}


# ---------------------------------------------------------------- purchases


@router.get("/purchases")
def purchases(start: str = "", end: str = "", q: str = "", user=Admin):
    sql = """SELECT p.*, a.name AS account_name,
                    (SELECT GROUP_CONCAT(i.qty || '× ' || pr.name, ' ، ') FROM purchase_items i
                       JOIN products pr ON pr.id = i.product_id WHERE i.purchase_id = p.id) AS items_text,
                    (SELECT SUM(i.qty) FROM purchase_items i WHERE i.purchase_id = p.id) AS items_count
             FROM purchases p LEFT JOIN accounts a ON a.id = p.account_id WHERE 1 = 1"""
    args: list = []
    if start:
        sql += " AND p.date >= ?"
        args.append(start)
    if end:
        sql += " AND p.date <= ?"
        args.append(end)
    if q.strip():
        like = f"%{q.strip()}%"
        sql += """ AND (p.code LIKE ? OR p.supplier LIKE ? OR p.note LIKE ? OR EXISTS (SELECT 1 FROM purchase_items i
                   JOIN products pr ON pr.id = i.product_id WHERE i.purchase_id = p.id AND pr.name LIKE ?))"""
        args += [like] * 4
    sql += " ORDER BY p.date DESC, p.id DESC LIMIT 1000"
    with db.read() as con:
        return db.rows(con.execute(sql, args))


@router.get("/purchases/{purchase_id}")
def purchase_detail(purchase_id: int, user=Admin):
    with db.read() as con:
        pur = db.one(con.execute("""SELECT p.*, a.name AS account_name, u.name AS created_by_name FROM purchases p
                                    LEFT JOIN accounts a ON a.id = p.account_id LEFT JOIN users u ON u.id = p.created_by
                                    WHERE p.id = ?""", (purchase_id,)))
        if not pur:
            raise HTTPException(404, "خرید پیدا نشد")
        items = db.rows(con.execute("""SELECT i.*, pr.name, pr.image, pr.sku FROM purchase_items i
                                       JOIN products pr ON pr.id = i.product_id WHERE i.purchase_id = ?""", (purchase_id,)))
    return {"purchase": pur, "items": items, "drive": drive.link(receipts.ref("purchase", purchase_id))}


@router.post("/purchases")
async def create_purchase(request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        pid = ledger.create_purchase(con, body, user)
    receipts.send("purchase", pid)
    return {"id": pid}


@router.post("/purchases/{purchase_id}/void")
def void_purchase(purchase_id: int, user=Admin):
    with db.tx() as con:
        ledger.void_purchase(con, purchase_id, user)
    return {"ok": True}


# ---------------------------------------------------------------- expenses


@router.get("/expenses")
def expenses(start: str = "", end: str = "", category: str = "", account_id: int = 0, q: str = "",
             include_inventory: bool = True, user=Admin):
    sql = """SELECT e.*, a.name AS account_name, u.name AS created_by_name FROM expenses e
             LEFT JOIN accounts a ON a.id = e.account_id LEFT JOIN users u ON u.id = e.created_by WHERE 1 = 1"""
    args: list = []
    for cond, val in (("e.date >= ?", start), ("e.date <= ?", end), ("e.category = ?", category)):
        if val:
            sql += f" AND {cond}"
            args.append(val)
    if account_id:
        sql += " AND e.account_id = ?"
        args.append(account_id)
    if not include_inventory:
        sql += " AND e.is_inventory = 0"
    if q.strip():
        like = f"%{q.strip()}%"
        sql += " AND (e.description LIKE ? OR e.note LIKE ? OR e.category LIKE ? OR e.code LIKE ?)"
        args += [like] * 4
    sql += " ORDER BY e.date DESC, e.id DESC LIMIT 2000"
    with db.read() as con:
        return db.rows(con.execute(sql, args))


@router.post("/expenses")
async def create_expense(request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        eid = ledger.save_expense(con, body, user)
    receipts.send("expense", eid)
    return {"id": eid}


@router.put("/expenses/{expense_id}")
async def update_expense(expense_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        ledger.save_expense(con, body, user, expense_id)
    receipts.send("expense", expense_id)
    return {"ok": True}


@router.put("/{kind}/{rec_id}/receipt")
async def set_receipt(kind: str, rec_id: int, request: Request, user=Admin):
    """Add, replace or remove the receipt of a purchase, sale or expense after it was recorded."""
    kinds = {"purchases": "purchase", "sales": "sale", "expenses": "expense"}
    if kind not in kinds:
        raise HTTPException(404)
    receipts.attach(kinds[kind], rec_id, (await request.json()).get("receipt"), user)
    return {"ok": True, "drive": drive.link(receipts.ref(kinds[kind], rec_id))}


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, user=Admin):
    with db.tx() as con:
        e = db.one(con.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)))
        if not e:
            raise HTTPException(404, "هزینه پیدا نشد")
        if e["sale_id"]:
            raise ledger.LedgerError("این پورسانت خودکار است؛ با ابطال فروش حذف می‌شود")
        con.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        notify.activity(con, "expense_delete", f"هزینه حذف شد: {e['category']}",
                        f"{ledger.toman(e['amount'])} — {e['description'] or ''} ({user['name']})", user_id=user["id"],
                        level="warning")
        notify.publish_after(con, {"type": "refresh", "scope": "expenses"})
    drive.forget(receipts.ref("expense", expense_id))
    return {"ok": True}


# ---------------------------------------------------------------- money


@router.get("/money")
def money(user=Admin):
    with db.read() as con:
        return {
            **ledger.summary_money(con),
            "partners": ledger.partner_positions(con),
            "capital": db.rows(con.execute("""SELECT c.*, p.name AS partner_name, a.name AS account_name FROM capital c
                                              JOIN partners p ON p.id = c.partner_id LEFT JOIN accounts a ON a.id = c.account_id
                                              ORDER BY c.date DESC, c.id DESC LIMIT 200""")),
            "transfers": db.rows(con.execute("""SELECT t.*, fa.name AS from_name, ta.name AS to_name FROM transfers t
                                                JOIN accounts fa ON fa.id = t.from_account JOIN accounts ta ON ta.id = t.to_account
                                                ORDER BY t.date DESC, t.id DESC LIMIT 200""")),
        }


@router.get("/accounts/{account_id}/flows")
def account_flows(account_id: int, user=Admin):
    with db.read() as con:
        rows = db.rows(con.execute(
            """SELECT f.*,
                 CASE f.src
                   WHEN 'sale' THEN (SELECT code || ' — ' || IFNULL(customer_name, '') FROM sales WHERE id = f.ref_id)
                   WHEN 'purchase' THEN (SELECT code || ' — ' || IFNULL(supplier, '') FROM purchases WHERE id = f.ref_id)
                   WHEN 'expense' THEN (SELECT category || ' — ' || IFNULL(description, '') FROM expenses WHERE id = f.ref_id)
                   WHEN 'capital' THEN (SELECT CASE kind WHEN 'in' THEN 'آورده ' ELSE 'برداشت ' END || p.name
                                        FROM capital c JOIN partners p ON p.id = c.partner_id WHERE c.id = f.ref_id)
                   WHEN 'transfer' THEN (SELECT fa.name || ' ← ' || ta.name || IFNULL(' — ' || t.note, '') FROM transfers t
                                         JOIN accounts fa ON fa.id = t.from_account JOIN accounts ta ON ta.id = t.to_account
                                         WHERE t.id = f.ref_id)
                 END AS label
               FROM money_flows f WHERE f.account_id = ? ORDER BY f.date, f.src, f.ref_id""", (account_id,)))
    running = 0
    for r in rows:
        running += r["amount"]
        r["running"] = running
    rows.reverse()
    return rows


@router.post("/accounts")
async def create_account(request: Request, user=Admin):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name or body.get("kind") not in ("shop", "partner"):
        raise ledger.LedgerError("نام و نوع حساب را وارد کنید")
    with db.tx() as con:
        cur = con.execute("INSERT INTO accounts (name, kind, partner_id, note, sort) VALUES (?, ?, ?, ?, 20)",
                          (name, body["kind"], body.get("partner_id") if body["kind"] == "partner" else None,
                           (body.get("note") or "").strip() or None))
    return {"id": cur.lastrowid}


@router.put("/accounts/{account_id}")
async def update_account(account_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        acc = db.one(con.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)))
        if not acc:
            raise HTTPException(404, "حساب پیدا نشد")
        kind = body.get("kind", acc["kind"])
        if acc["kind"] == "agent":
            kind = "agent"
        con.execute("UPDATE accounts SET name = ?, kind = ?, partner_id = ?, note = ?, active = ? WHERE id = ?",
                    ((body.get("name") or acc["name"]).strip(), kind,
                     body.get("partner_id", acc["partner_id"]) if kind == "partner" else None,
                     body.get("note", acc["note"]), 1 if body.get("active", acc["active"]) else 0, account_id))
        notify.publish_after(con, {"type": "refresh", "scope": "money"})
    return {"ok": True}


@router.post("/capital")
async def create_capital(request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        cid = ledger.save_capital(con, body, user)
    return {"id": cid}


@router.delete("/capital/{capital_id}")
def delete_capital(capital_id: int, user=Admin):
    with db.tx() as con:
        con.execute("DELETE FROM capital WHERE id = ?", (capital_id,))
        notify.activity(con, "capital_delete", "یک ردیف آورده/برداشت حذف شد", f"توسط {user['name']}",
                        user_id=user["id"], level="warning")
        notify.publish_after(con, {"type": "refresh", "scope": "money"})
    return {"ok": True}


@router.post("/transfers")
async def create_transfer(request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        tid = ledger.save_transfer(con, body, user)
    return {"id": tid}


@router.delete("/transfers/{transfer_id}")
def delete_transfer(transfer_id: int, user=Admin):
    with db.tx() as con:
        con.execute("DELETE FROM transfers WHERE id = ?", (transfer_id,))
        notify.activity(con, "transfer_delete", "یک انتقال/تسویه حذف شد", f"توسط {user['name']}",
                        user_id=user["id"], level="warning")
        notify.publish_after(con, {"type": "refresh", "scope": "money"})
    return {"ok": True}


# ---------------------------------------------------------------- reports


@router.get("/reports")
def report(period: str = "month", start: str = "", end: str = "", user=Admin):
    s, e, label = reports.period_bounds(period, start, end)
    with db.read() as con:
        return reports.report(con, s, e, label)


@router.get("/statements")
def financial_statements(period: str = "month", start: str = "", end: str = "", user=Admin):
    """Balance sheet (at the end of the period), income statement and cash flow for the period."""
    s, e, label = reports.period_bounds(period, start, end)
    with db.read() as con:
        return statements.statements(con, s, e, label)


@router.get("/statements.xlsx")
def financial_statements_xlsx(period: str = "month", start: str = "", end: str = "", user=Admin):
    s, e, label = reports.period_bounds(period, start, end)
    with db.read() as con:
        data = statements.statements(con, s, e, label)
    return Response(statements.workbook_bytes(data),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="aiko-statements-{s}-{e}.xlsx"'})


# ---------------------------------------------------------------- WooCommerce


def _woo_public(s: dict) -> dict:
    out = {k: v for k, v in s.items() if k not in ("secret", "webhook_secret", "key")}
    out["secret_set"] = bool(s.get("secret"))
    out["key_set"] = bool(s.get("key"))
    out["webhook_secret"] = s.get("webhook_secret") or ""
    return out


@router.get("/woo")
def woo_status(request: Request, user=Admin):
    s = client.settings()
    with db.read() as con:
        counts = db.one(con.execute(
            """SELECT COUNT(*) AS products, SUM(CASE WHEN woo_id IS NOT NULL THEN 1 ELSE 0 END) AS linked,
                      SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'ok' THEN 1 ELSE 0 END) AS ok,
                      SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'pending' THEN 1 ELSE 0 END) AS pending,
                      SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'error' THEN 1 ELSE 0 END) AS errors,
                      SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'differ' THEN 1 ELSE 0 END) AS differ,
                      SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'nocount' THEN 1 ELSE 0 END) AS nocount,
                      SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'whole' THEN 1 ELSE 0 END) AS whole,
                      SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'gone' THEN 1 ELSE 0 END) AS gone,
                      MAX(woo_checked_at) AS checked_at
               FROM products WHERE active = 1"""))
        sales = db.one(con.execute(
            """SELECT SUM(CASE WHEN source = 'site' THEN 1 ELSE 0 END) AS site,
                      SUM(CASE WHEN channel = 'website' AND woo_order_id IS NULL THEN 1 ELSE 0 END) AS manual_web
               FROM sales WHERE status = 'done'"""))
        logs = db.rows(con.execute("SELECT * FROM woo_log ORDER BY id DESC LIMIT 40"))
        review = history.review(con)
    catalog = db.get_setting("woo_catalog", {}) or {}
    return {"settings": _woo_public(s), "configured": client.configured(s), "counts": counts, "sales": sales, "log": logs,
            "webhook_url": _webhook_url(request), "catalog_fetched_at": catalog.get("fetched_at"),
            "catalog_source": catalog.get("source"), "full_sync": history.state(), "review": review,
            "missing_codes": len(stock.missing_codes()),
            "busy": client.sync_lock().locked()}


def _webhook_url(request: Request) -> str:
    return f"{config.PUBLIC_URL or str(request.base_url).rstrip('/')}/api/erp/woo/webhook"


@router.put("/woo")
async def woo_save(request: Request, user=Admin):
    """Sync options only. The site address and keys are the shared connection (PUT /api/integrations)."""
    body = await request.json()
    if any(k in body for k in ("url", "key", "secret", "query_auth")):
        from ...core import integrations
        integrations.save_woo({k: body[k] for k in ("url", "key", "secret", "query_auth") if k in body})
    with db.tx() as con:
        s = db.get_setting("woo", {}, con) or {}
        for key in ("pull_minutes", "webhook_secret"):
            if key in body:
                s[key] = body[key].strip() if isinstance(body[key], str) else body[key]
        if not s.get("webhook_secret"):
            s["webhook_secret"] = secrets.token_urlsafe(24)
        db.set_setting("woo", s, con)
    stock.wake()
    return _woo_public(client.settings())


@router.post("/woo/sync-now")
async def woo_sync_now(request: Request, user=Admin):
    """Orders, every product's stock, and what is waiting to be sent — right now."""
    if client.sync_lock().locked():
        raise client.WooError("یک همگام‌سازی همین الان در حال انجام است؛ چند لحظه دیگر دوباره بزنید")
    return await stock.sync_now(_webhook_url(request))


@router.post("/woo/start")
async def woo_start(request: Request, user=Admin):
    """The one-time start of stock sync: which numbers are right today, the site's or the panel's."""
    if client.sync_lock().locked():
        raise client.WooError("یک همگام‌سازی همین الان در حال انجام است؛ چند لحظه دیگر دوباره بزنید")
    body = await request.json()
    return await stock.start(body.get("side"), user, _webhook_url(request))


@router.post("/woo/codes")
async def woo_codes(user=Admin):
    """Write the panel's product codes (SKU) on the site where the site has none, now and for new products."""
    if client.sync_lock().locked():
        raise client.WooError("یک همگام‌سازی همین الان در حال انجام است؛ چند لحظه دیگر دوباره بزنید")
    return await stock.start_codes()


@router.post("/woo/count")
async def woo_count(request: Request, user=Admin):
    """An item the site sells without counting, counted here: both get this number."""
    body = await request.json()
    stock.count(int(body["product_id"]), ledger._int(body.get("qty"), "تعداد"), user)
    return {"ok": True}


@router.post("/woo/webhooks")
async def woo_webhooks(request: Request, user=Admin):
    """Create the site's webhooks to this panel (orders and product changes arrive instantly)."""
    return await client.ensure_webhooks(_webhook_url(request))


@router.post("/woo/full-sync")
async def woo_full_sync(user=Admin):
    history.start(user)
    return {"ok": True, "state": history.state()}


@router.post("/products/{product_id}/merge")
async def merge_product(product_id: int, request: Request, user=Admin):
    """Merge this product into another one (the same item recorded twice)."""
    body = await request.json()
    with db.tx() as con:
        ledger.merge_products(con, product_id, int(body["into"]), user)
    return {"ok": True}


@router.get("/woo/catalog")
def woo_catalog(user=Admin):
    catalog = db.get_setting("woo_catalog", {}) or {}
    with db.read() as con:
        linked = db.rows(con.execute(
            """SELECT id, sku, name, stock, price, image, woo_id, woo_variation_id, woo_name, woo_url, woo_state,
                      woo_error, woo_stock, woo_synced_at, woo_manage, woo_in_stock, woo_checked_at
               FROM products WHERE active = 1 AND woo_id IS NOT NULL
               ORDER BY CASE woo_state WHEN 'error' THEN 0 WHEN 'gone' THEN 1 WHEN 'differ' THEN 2 WHEN 'nocount' THEN 3
                        WHEN 'whole' THEN 4 WHEN 'pending' THEN 5 ELSE 6 END, name"""))
        sugg = matching.suggestions(con, catalog) if catalog.get("items") else []
    used = {(p["woo_id"], p["woo_variation_id"]) for p in linked}
    whole_linked = {w for w, v in used if v is None}          # product linked as a whole: its colors are covered
    color_linked = {w for w, v in used if v is not None}      # some colors linked: the whole product is not offered
    items = catalog.get("items") or []
    unlinked_site = [e for e in items if (e["woo_id"], e["variation_id"]) not in used
                     and not (e["variation_id"] and e["woo_id"] in whole_linked)
                     and not (e["variation_id"] is None and e["woo_id"] in color_linked)]
    return {"fetched_at": catalog.get("fetched_at"), "source": catalog.get("source"), "items": items,
            "linked": linked, "suggestions": sugg, "unlinked_site": unlinked_site}


@router.post("/woo/link")
async def woo_link(request: Request, user=Admin):
    body = await request.json()
    links = body.get("links") or [body]
    catalog = db.get_setting("woo_catalog", {}) or {}
    done, skipped = 0, []
    with db.tx() as con:
        for link in links:
            try:
                matching.link_product(con, int(link["product_id"]), int(link["woo_id"]),
                                 int(link["variation_id"]) if link.get("variation_id") else None, catalog)
                done += 1
            except ledger.LedgerError as exc:
                if len(links) == 1:
                    raise
                skipped.append(str(exc))
        notify.activity(con, "woo_link", f"{ledger.fa(done)} محصول به سایت وصل شد", f"توسط {user['name']}",
                        user_id=user["id"])
    stock.touch([link.get("woo_id") for link in links])
    return {"ok": True, "count": done, "skipped": skipped}


@router.post("/woo/unlink")
async def woo_unlink(request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        con.execute("""UPDATE products SET woo_id = NULL, woo_variation_id = NULL, woo_name = NULL, woo_state = NULL,
                       woo_error = NULL, woo_stock = NULL WHERE id = ?""", (int(body["product_id"]),))
        notify.publish_after(con, {"type": "refresh", "scope": "products"})
    return {"ok": True}


@router.post("/woo/pull")
async def woo_pull(request: Request, user=Admin):
    body = await request.json()
    since = body.get("since")
    if since:
        result = await orders.pull_orders(f"{since}T00:00:00+00:00")
    else:
        result = await orders.pull_orders()
    return result


@router.post("/woo/webhook", include_in_schema=False)
async def woo_webhook(request: Request):
    body = await request.body()
    if not request.headers.get("x-wc-webhook-topic"):
        return {"ok": True}          # WooCommerce "ping" when the webhook is saved
    if not client.verify_webhook(body, request.headers.get("x-wc-webhook-signature")):
        client.wlog("webhook", False, "امضای وب‌هوک نامعتبر بود (Secret را چک کنید)")
        raise HTTPException(401, "bad signature")
    topic = request.headers.get("x-wc-webhook-topic", "")
    import json
    data = json.loads(body or b"{}")
    if topic.startswith("order."):
        result = await asyncio.to_thread(orders.process_order, data)
        client.wlog("webhook", True, f"{topic} #{data.get('number') or data.get('id')} ({data.get('status')}): {result}")
    elif topic.startswith("product."):
        # stock, price or a new color changed on the site: read that product again within seconds
        stock.touch([data.get("parent_id") or data.get("id")])
    return {"ok": True}


# ---------------------------------------------------------------- settings, users, partners

EDITABLE_SETTINGS = {"shop", "product_categories", "expense_categories", "channel_accounts"}


@router.put("/settings/{key}")
async def save_setting(key: str, request: Request, user=Admin):
    if key not in EDITABLE_SETTINGS:
        raise HTTPException(404, "تنظیم ناشناخته")
    db.set_setting(key, await request.json())
    return {"ok": True}


@router.put("/partners")
async def partners_bulk(request: Request, user=Admin):
    """Save all partners at once (shares must add up to 100, so they cannot be changed one by one)."""
    body = await request.json()
    with db.tx() as con:
        for p in body:
            con.execute("UPDATE partners SET name = ?, share = ? WHERE id = ?",
                        ((p.get("name") or "").strip() or "شریک", float(p.get("share") or 0), int(p["id"])))
        total = con.execute("SELECT SUM(share) FROM partners WHERE active = 1").fetchone()[0]
        if abs((total or 0) - 100) > 0.01:
            raise ledger.LedgerError(f"جمع سهم شرکا باید ۱۰۰ باشد (الان {ledger.fa(round(total or 0, 2))})")
        notify.activity(con, "partners", "سهم شرکا تغییر کرد",
                        "، ".join(f"{p.get('name')}: {ledger.fa(p.get('share'))}٪" for p in body), user_id=user["id"])
        notify.publish_after(con, {"type": "refresh", "scope": "money"})
    return {"ok": True}


@router.put("/partners/{partner_id}")
async def partners_update(partner_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.tx() as con:
        p = db.one(con.execute("SELECT * FROM partners WHERE id = ?", (partner_id,)))
        if not p:
            raise HTTPException(404, "شریک پیدا نشد")
        con.execute("UPDATE partners SET name = ?, share = ? WHERE id = ?",
                    ((body.get("name") or p["name"]).strip(), float(body.get("share", p["share"])), partner_id))
        total = con.execute("SELECT SUM(share) FROM partners WHERE active = 1").fetchone()[0]
        if abs((total or 0) - 100) > 0.01:
            raise ledger.LedgerError(f"جمع سهم شرکا باید ۱۰۰ باشد (الان {ledger.fa(round(total, 2))})")
        notify.publish_after(con, {"type": "refresh", "scope": "money"})
    return {"ok": True}


# ---------------------------------------------------------------- files, import, export, backup


@router.post("/import-excel")
async def import_excel(file: UploadFile = File(...), user=Admin):
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        return await asyncio.to_thread(importer.run, tmp.name, user)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@router.get("/export.xlsx")
def export_xlsx(user=Admin):
    data = exporter.workbook_bytes()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="aiko-{db.today()}.xlsx"'})
