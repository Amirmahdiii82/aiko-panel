"""Receipts of purchases, sales and expenses — and an invoice PDF for every website order — copied to the owners'
Google Drive (core/drive.py) in one folder per month and kind:

    ۱۴۰۵/۰۷ مهر/خرید کالا/۳۰ — P-12 — بازار تهران — ۸۳۰٬۰۰۰ تومان.jpg

Nothing here runs inside a database transaction: callers send a record after it is committed.
"""
import logging
from pathlib import Path

from ...core import config, drive, jalali
from ...core.text import fa, toman
from . import db, ledger

log = logging.getLogger("aiko.erp.receipts")

FOLDER = {"purchase": "خرید کالا", "sale": "فروش", "website": "فروش سایت", "expense": "هزینه‌ها"}
TABLE = {"purchase": "purchases", "sale": "sales", "expense": "expenses"}
FONTS = Path(__file__).resolve().parents[2] / "core" / "assets"


def ref(kind: str, rec_id: int) -> str:
    return f"erp:{kind}:{rec_id}"


def _name(kind: str, r: dict) -> str:
    if kind == "purchase":
        return drive.file_name(r["date"], r["code"], r["supplier"], r["total"])
    if kind == "expense":
        return drive.file_name(r["date"], r["category"], r["description"], r["amount"])
    who = r["customer_name"] or ledger.CHANNELS.get(r["channel"], "")
    return drive.file_name(r["date"], r["code"], who, r["total"])


def send(kind: str, rec_id: int) -> None:
    """Queue this record's receipt for Drive (or take its old file out if the receipt was removed)."""
    if kind not in TABLE or not drive.connected():
        return
    with db.read() as con:
        r = db.one(con.execute(f"SELECT * FROM {TABLE[kind]} WHERE id = ?", (rec_id,)))
    if not r:
        return
    folder_kind = "website" if kind == "sale" and r.get("woo_order_id") else kind
    if not r.get("receipt"):
        drive.forget(ref(kind, rec_id))
        return
    drive.enqueue(ref(kind, rec_id), r["receipt"], drive.month_folder(r["date"], FOLDER[folder_kind]), _name(kind, r))


def attach(kind: str, rec_id: int, path: str | None, user: dict) -> None:
    """Add, replace or remove the receipt of an existing purchase, sale or expense."""
    if kind not in TABLE:
        raise ledger.LedgerError("نوع نامعتبر")
    with db.tx() as con:
        if not con.execute(f"SELECT 1 FROM {TABLE[kind]} WHERE id = ?", (rec_id,)).fetchone():
            raise ledger.LedgerError("پیدا نشد")
        con.execute(f"UPDATE {TABLE[kind]} SET receipt = ? WHERE id = ?", ((path or "").strip() or None, rec_id))
    send(kind, rec_id)


# ---------------------------------------------------------------- website order invoices

def website_invoice(sale_id: int) -> None:
    """An invoice PDF for a website order, kept as the sale's receipt and sent to Drive. Its file name carries the
    amount, so a refund or a changed order gets a new invoice (the old one goes to the Drive trash)."""
    if not drive.connected():
        return
    with db.read() as con:
        sale = db.one(con.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)))
        items = db.rows(con.execute("SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id", (sale_id,)))
        shop = (db.get_setting("shop", {}, con) or {}).get("name") or "آیکو"
    if not sale or not sale["woo_order_id"] or sale["status"] != "done":
        return
    jy, jm, _ = jalali.iso_to_jalali(sale["date"])
    rel = Path("invoices") / f"{jy}" / f"{jm:02d}" / f"{sale['code']}-{sale['total']}.pdf"
    path = config.UPLOAD_DIR / rel
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(invoice_pdf(sale, items, shop))
        except Exception:
            log.exception("invoice for %s failed", sale["code"])
            return
    with db.tx() as con:
        con.execute("UPDATE sales SET receipt = ? WHERE id = ?", (rel.as_posix(), sale_id))
    send("sale", sale_id)


def invoice_pdf(sale: dict, items: list[dict], shop: str) -> bytes:
    """A one-page A5 invoice, right-to-left, Vazirmatn (Persian shaping by HarfBuzz). Usually 15–25 KB."""
    from fpdf import FPDF

    pdf = FPDF(format="A5")
    pdf.set_auto_page_break(True, margin=12)
    pdf.add_page()
    pdf.add_font("vz", "", str(FONTS / "Vazirmatn-Regular.ttf"))
    pdf.add_font("vz", "B", str(FONTS / "Vazirmatn-Bold.ttf"))
    pdf.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="fas")
    jy, jm, jd = jalali.iso_to_jalali(sale["date"])
    line = dict(new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("vz", "B", 15)
    pdf.cell(0, 9, shop, align="R", **line)
    pdf.set_font("vz", "", 10)
    pdf.set_text_color(110, 104, 127)
    pdf.cell(0, 6, f"فاکتور سفارش سایت {fa(sale['code'].replace('WEB-', ''))} — {fa(jd)} {jalali.MONTHS[jm - 1]} {fa(jy)}", align="R", **line)
    customer = " — ".join(x for x in (sale["customer_name"], fa(sale["customer_phone"] or "")) if x)
    if customer:
        pdf.cell(0, 6, f"مشتری: {customer}", align="R", **line)
    pdf.set_text_color(42, 39, 51)
    pdf.ln(3)

    pdf.set_font("vz", "", 9)
    pdf.set_draw_color(220, 214, 230)
    with pdf.table(text_align=("LEFT", "CENTER", "LEFT", "RIGHT"), col_widths=(26, 26, 12, 64), line_height=7,
                   headings_style=None, first_row_as_headings=False) as table:
        head = table.row()
        pdf.set_font("vz", "B", 9)
        for h in ("جمع (تومان)", "قیمت واحد", "تعداد", "کالا"):
            head.cell(h)
        pdf.set_font("vz", "", 9)
        for it in items:
            row = table.row()
            for v in (fa(f"{it['line_total'] - (it['discount'] or 0):,}"), fa(f"{it['unit_price']:,}"), fa(it["qty"]), it["name"]):
                row.cell(v)
    pdf.ln(3)

    def total_row(label: str, amount: int, bold: bool = False) -> None:
        pdf.set_font("vz", "B" if bold else "", 11 if bold else 9.5)
        pdf.cell(0, 7 if bold else 6, f"{label}: {toman(amount)}", align="R", **line)

    total_row("جمع کالاها", sale["subtotal"])
    if sale["discount"]:
        total_row("تخفیف", -sale["discount"])
    if sale["shipping"]:
        total_row("ارسال", sale["shipping"])
    if sale["fees"]:
        total_row("کارمزد / سایر", sale["fees"])
    if sale["refunded"]:
        total_row("برگشت وجه", -sale["refunded"])
    total_row("مبلغ نهایی", sale["total"], bold=True)
    if sale["note"]:
        pdf.ln(2)
        pdf.set_font("vz", "", 8.5)
        pdf.set_text_color(110, 104, 127)
        pdf.multi_cell(0, 5, sale["note"], align="R")
    return bytes(pdf.output())


# ---------------------------------------------------------------- backfill (receipts recorded before Drive was connected)

def backfill(days: int = 90) -> None:
    """Everything with a receipt, plus invoices for website orders of the last `days`."""
    with db.read() as con:
        rows = {k: [r[0] for r in con.execute(f"SELECT id FROM {t} WHERE receipt IS NOT NULL AND receipt != ''")]
                for k, t in TABLE.items()}
        web = [r[0] for r in con.execute(
            """SELECT id FROM sales WHERE woo_order_id IS NOT NULL AND status = 'done'
               AND (receipt IS NULL OR receipt = '') AND date >= date('now', ?)""", (f"-{int(days)} day",))]
    for kind, ids in rows.items():
        for rec_id in ids:
            send(kind, rec_id)
    for sale_id in web:
        website_invoice(sale_id)
