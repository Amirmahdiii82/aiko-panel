"""Shop reports for the owners' bot: short, phone-sized texts built from the same numbers as the dashboard."""
from ...core.botkit import Report
from ...core.text import fa, toman
from . import db, ledger, reports


def today() -> str:
    day = db.today()
    with db.read() as con:
        t = reports._sales_totals(con, day, day)
        rows = db.rows(con.execute(
            """SELECT code, channel, total, customer_name FROM sales WHERE status = 'done' AND date = ?
               ORDER BY id DESC LIMIT 8""", (day,)))
        by_channel = db.rows(con.execute(
            """SELECT channel, COUNT(*) AS n, SUM(total) AS total FROM sales WHERE status = 'done' AND date = ?
               GROUP BY channel ORDER BY total DESC""", (day,)))
    if not t["orders"]:
        return "📊 امروز هنوز فروشی ثبت نشده."
    lines = [f"📊 فروش امروز: {toman(t['revenue'])}", f"{fa(t['orders'])} سفارش، {fa(t['items'])} عدد کالا",
             f"سود ناخالص: {toman(t['gross'])}"]
    lines += [f"• {ledger.CHANNELS.get(c['channel'], c['channel'])}: {fa(c['n'])} سفارش — {toman(c['total'])}" for c in by_channel]
    lines.append("\nآخرین‌ها:")
    lines += [f"  {r['code']} — {toman(r['total'])}{' — ' + r['customer_name'] if r['customer_name'] else ''}" for r in rows]
    return "\n".join(lines)


def month() -> str:
    start, end, label = reports.period_bounds("month")
    with db.read() as con:
        t = reports._sales_totals(con, start, end)
        missing = ledger.missing_costs(con, start, end)
        money = ledger.summary_money(con)
    lines = [f"📈 {label}",
             f"فروش: {toman(t['revenue'])} ({fa(t['orders'])} سفارش)",
             f"سود ناخالص: {toman(t['gross'])} (حاشیه {fa(round(t['margin'] * 100, 1))}٪)",
             f"هزینه‌های جاری: {toman(t['expenses'])}",
             f"سود خالص: {toman(t['net'])}",
             f"پول در حساب‌های فروشگاه: {toman(money['shop_cash'])}"]
    if t["unpaid"]:
        lines.append(f"نسیه (پرداخت‌نشده): {toman(t['unpaid'])}")
    if missing["lines"]:
        lines.append(f"\n⚠️ {fa(missing['lines'])} ردیف فروش قیمت خرید ندارد؛ سود واقعی کمتر است.")
    return "\n".join(lines)


def low_stock() -> str:
    with db.read() as con:
        rows = db.rows(con.execute(
            """SELECT name, stock FROM products WHERE active = 1 AND stock <= low_stock
               ORDER BY stock, name LIMIT 40"""))
    if not rows:
        return "✅ هیچ محصولی رو به اتمام نیست."
    out = [r for r in rows if r["stock"] <= 0]
    low = [r for r in rows if r["stock"] > 0]
    lines = []
    if out:
        lines.append(f"⛔️ ناموجود ({fa(len(out))}):")
        lines += [f"• {r['name']}" for r in out]
    if low:
        lines.append(f"\n⚠️ رو به اتمام ({fa(len(low))}):")
        lines += [f"• {r['name']} — {fa(r['stock'])} عدد" for r in low]
    return "\n".join(lines).strip()


COMMANDS = {
    "today": Report("📊 فروش امروز", today),
    "month": Report("📈 گزارش این ماه", month),
    "low": Report("⚠️ موجودی کم", low_stock),
}
