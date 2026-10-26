"""Numbers for the dashboard and the reports page.

Revenue = what customers paid (after discount, including shipping they paid).
Gross profit = revenue - cost of the goods sold (average landed cost at the time of the sale).
Net profit = gross profit - running expenses (packaging, ads, hosting, commissions, ...).
Money spent on stock is not an expense here: it becomes cost of goods when the item sells.
"""
from datetime import date, timedelta

from ...core import jalali
from . import db, ledger


def _jalali_today() -> tuple[int, int, int]:
    return jalali.iso_to_jalali(db.today())


def period_bounds(period: str, start: str | None = None, end: str | None = None) -> tuple[str, str, str]:
    jy, jm, _ = _jalali_today()
    if period == "custom" and start and end:
        return start, end, "بازه دلخواه"
    if period == "30d":
        s, e, _, _ = recent_bounds(30)
        return s, e, RECENT_LABEL
    if period == "last_month":
        y, m = (jy, jm - 1) if jm > 1 else (jy - 1, 12)
        s, e = jalali.month_bounds(y, m)
        return s, e, f"{jalali.MONTHS[m - 1]} {ledger.fa(y)}"
    if period == "3m":
        y, m = jy, jm - 2
        while m < 1:
            y, m = y - 1, m + 12
        s, _ = jalali.month_bounds(y, m)
        return s, jalali.month_bounds(jy, jm)[1], "سه ماه اخیر"
    if period == "year":
        s, _ = jalali.month_bounds(jy, 1)
        _, e = jalali.month_bounds(jy, 12)
        return s, e, f"سال {ledger.fa(jy)}"
    if period == "all":
        return "2000-01-01", "2100-01-01", "از ابتدا"
    s, e = jalali.month_bounds(jy, jm)
    return s, e, f"{jalali.MONTHS[jm - 1]} {ledger.fa(jy)}"


def _chan(channel: str, col: str = "channel") -> tuple[str, tuple]:
    """The SQL and arguments that narrow a sales query to one channel ("" = every channel)."""
    return (f" AND {col} = ?", (channel,)) if channel else ("", ())


def _sales_totals(con, start: str, end: str, channel: str = "") -> dict:
    """Sales of a date range (one channel, or all). Running expenses belong to the whole shop, so a single channel's
    net profit is its gross profit minus nothing: the caller shows gross for a channel."""
    only, extra = _chan(channel)
    r = con.execute(
        f"""SELECT COUNT(*) AS orders, IFNULL(SUM(total), 0) AS revenue, IFNULL(SUM(cogs), 0) AS cogs,
                  IFNULL(SUM(discount), 0) AS discount, IFNULL(SUM(shipping), 0) AS shipping,
                  IFNULL(SUM(CASE WHEN paid = 0 THEN total ELSE 0 END), 0) AS unpaid
           FROM sales WHERE status = 'done' AND date BETWEEN ? AND ?{only}""", (start, end, *extra)).fetchone()
    s_only, _ = _chan(channel, "s.channel")
    items = con.execute(f"""SELECT IFNULL(SUM(i.qty), 0) FROM sale_items i JOIN sales s ON s.id = i.sale_id
                           WHERE s.status = 'done' AND s.date BETWEEN ? AND ?{s_only}""",
                        (start, end, *extra)).fetchone()[0]
    expenses = 0 if channel else con.execute("""SELECT IFNULL(SUM(amount), 0) FROM expenses
                              WHERE is_inventory = 0 AND date BETWEEN ? AND ?""", (start, end)).fetchone()[0]
    revenue, cogs = int(r["revenue"]), float(r["cogs"])
    gross = revenue - cogs
    return {
        "orders": r["orders"], "items": int(items), "revenue": revenue, "cogs": int(round(cogs)),
        "gross": int(round(gross)), "margin": (gross / revenue) if revenue else 0,
        "expenses": int(expenses), "net": int(round(gross - expenses)),
        "discount": int(r["discount"]), "shipping": int(r["shipping"]), "unpaid": int(r["unpaid"]),
        "avg_order": int(revenue / r["orders"]) if r["orders"] else 0,
    }


def _previous_range(start: str, end: str) -> tuple[str, str]:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    length = (e - s).days + 1
    return (s - timedelta(days=length)).isoformat(), (s - timedelta(days=1)).isoformat()


def monthly_series(con, start: str, end: str, max_months: int = 12, channel: str = "") -> list[dict]:
    months: dict[str, dict] = {}
    only, extra = _chan(channel)
    for r in con.execute(f"""SELECT date, total, cogs FROM sales WHERE status = 'done' AND date BETWEEN ? AND ?{only}""",
                         (start, end, *extra)):
        m = months.setdefault(jalali.jalali_month_key(r["date"]), {"revenue": 0, "cogs": 0.0, "expenses": 0})
        m["revenue"] += r["total"]
        m["cogs"] += r["cogs"]
    for r in con.execute("""SELECT date, amount FROM expenses WHERE is_inventory = 0 AND date BETWEEN ? AND ?""",
                         (start, end)):
        m = months.setdefault(jalali.jalali_month_key(r["date"]), {"revenue": 0, "cogs": 0.0, "expenses": 0})
        m["expenses"] += r["amount"]
    out = []
    for key in sorted(months)[-max_months:]:
        m = months[key]
        gross = m["revenue"] - m["cogs"]
        out.append({"key": key, "label": jalali.month_label(key), "revenue": m["revenue"], "gross": int(round(gross)),
                    "expenses": m["expenses"], "net": int(round(gross - m["expenses"]))})
    return out


def daily_series(con, start: str, end: str, channel: str = "") -> list[dict]:
    only, extra = _chan(channel)
    days = {r["date"]: r for r in con.execute(
        f"""SELECT date, SUM(total) AS revenue, COUNT(*) AS orders FROM sales
           WHERE status = 'done' AND date BETWEEN ? AND ?{only} GROUP BY date""", (start, end, *extra))}
    s, e = date.fromisoformat(start), min(date.fromisoformat(end), date.fromisoformat(db.today()))
    out = []
    while s <= e:
        iso = s.isoformat()
        r = days.get(iso)
        out.append({"date": iso, "revenue": int(r["revenue"]) if r else 0, "orders": r["orders"] if r else 0})
        s += timedelta(days=1)
    return out


def product_sales(con, start: str, end: str, channel: str = "", *, order: str = "profit DESC",
                  limit: int | None = None) -> list[dict]:
    """What each product sold in a date range: units, revenue after discounts, profit and margin."""
    only, extra = _chan(channel, "s.channel")
    rows = db.rows(con.execute(
        f"""SELECT i.product_id, IFNULL(p.name, i.name) AS name, p.image, SUM(i.qty) AS qty,
                   SUM(i.line_total - i.discount) AS revenue, SUM(i.line_total - i.discount - i.qty * i.unit_cost) AS profit
            FROM sale_items i JOIN sales s ON s.id = i.sale_id LEFT JOIN products p ON p.id = i.product_id
            WHERE s.status = 'done' AND s.date BETWEEN ? AND ?{only}
            GROUP BY IFNULL(i.product_id, i.name) ORDER BY {order}{f" LIMIT {int(limit)}" if limit else ""}""",
        (start, end, *extra)))
    for p in rows:
        p["profit"] = int(round(p["profit"] or 0))
        p["margin"] = (p["profit"] / p["revenue"]) if p["revenue"] else 0
    return rows


def report(con, start: str, end: str, label: str = "") -> dict:
    totals = _sales_totals(con, start, end)
    ps, pe = _previous_range(start, end) if start > "2000-01-01" else (start, start)
    previous = _sales_totals(con, ps, pe) if start > "2000-01-01" else None

    channels = db.rows(con.execute(
        """SELECT channel, COUNT(*) AS orders, SUM(total) AS revenue, SUM(total - cogs) AS gross
           FROM sales WHERE status = 'done' AND date BETWEEN ? AND ? GROUP BY channel ORDER BY revenue DESC""",
        (start, end)))
    for c in channels:
        c["label"] = ledger.CHANNELS.get(c["channel"], c["channel"])
        c["gross"] = int(round(c["gross"] or 0))

    sellers = db.rows(con.execute(
        """SELECT CASE WHEN s.seller_id IS NOT NULL THEN u.name
                       WHEN s.channel = 'website' THEN 'سایت' ELSE 'ثبت نشده' END AS name,
                  COUNT(*) AS orders, SUM(s.total) AS revenue, SUM(s.commission) AS commission
           FROM sales s LEFT JOIN users u ON u.id = s.seller_id
           WHERE s.status = 'done' AND s.date BETWEEN ? AND ? GROUP BY 1 ORDER BY revenue DESC""",
        (start, end)))

    products = product_sales(con, start, end)

    expense_cats = db.rows(con.execute(
        """SELECT category, SUM(amount) AS amount, COUNT(*) AS n FROM expenses
           WHERE is_inventory = 0 AND date BETWEEN ? AND ? GROUP BY category ORDER BY amount DESC""", (start, end)))

    purchases = con.execute("""SELECT IFNULL(SUM(total), 0) FROM purchases
                               WHERE status = 'done' AND date BETWEEN ? AND ?""", (start, end)).fetchone()[0]
    inventory_spend = con.execute("""SELECT IFNULL(SUM(amount), 0) FROM expenses
                                     WHERE is_inventory = 1 AND date BETWEEN ? AND ?""", (start, end)).fetchone()[0]

    first = con.execute("""SELECT MIN(d) FROM (SELECT MIN(date) AS d FROM sales WHERE status = 'done'
                           UNION ALL SELECT MIN(date) FROM expenses WHERE is_inventory = 0)""").fetchone()[0]
    series_start = max(start, first or start)
    span_days = (date.fromisoformat(min(end, db.today())) - date.fromisoformat(series_start)).days
    return {
        "start": start, "end": end, "label": label,
        "totals": totals, "previous": previous,
        "channels": channels, "sellers": sellers,
        "top_products": products[:10], "worst_products": sorted(products, key=lambda p: p["margin"])[:5],
        "expense_categories": expense_cats,
        "stock_spend": int(purchases) + int(inventory_spend),
        "monthly": monthly_series(con, series_start, end),
        "daily": daily_series(con, series_start, end) if 0 <= span_days <= 62 else [],
        "inventory": inventory_stats(con),
        "missing_cost": ledger.missing_costs(con, start, end),
    }


def inventory_stats(con, *, slow: bool = True) -> dict:
    r = con.execute(
        """SELECT IFNULL(SUM(CASE WHEN stock > 0 THEN stock * avg_cost END), 0) AS cost_value,
                  IFNULL(SUM(CASE WHEN stock > 0 THEN stock * price END), 0) AS retail_value,
                  IFNULL(SUM(CASE WHEN stock > 0 THEN stock END), 0) AS units,
                  SUM(CASE WHEN stock <= 0 THEN 1 ELSE 0 END) AS out_count,
                  SUM(CASE WHEN stock > 0 AND stock <= low_stock THEN 1 ELSE 0 END) AS low_count,
                  COUNT(*) AS products
           FROM products WHERE active = 1""").fetchone()
    cost_value, retail = float(r["cost_value"]), float(r["retail_value"])
    stats = {"cost_value": int(round(cost_value)), "retail_value": int(round(retail)),
             "potential_profit": int(round(retail - cost_value)), "units": int(r["units"]),
             "out_count": r["out_count"] or 0, "low_count": r["low_count"] or 0, "products": r["products"]}
    if not slow:                                   # products that stopped selling (reports page only)
        return stats
    cutoff = (date.fromisoformat(db.today()) - timedelta(days=45)).isoformat()
    stats["slow"] = db.rows(con.execute(
        """SELECT p.id, p.name, p.stock, p.avg_cost, p.image, p.stock * p.avg_cost AS tied,
                  (SELECT MAX(s.date) FROM sale_items i JOIN sales s ON s.id = i.sale_id
                    WHERE i.product_id = p.id AND s.status = 'done') AS last_sale
           FROM products p WHERE p.active = 1 AND p.stock > 0
             AND p.created_at < ?
             AND NOT EXISTS (SELECT 1 FROM sale_items i JOIN sales s ON s.id = i.sale_id
                             WHERE i.product_id = p.id AND s.status = 'done' AND s.date >= ?)
           ORDER BY tied DESC LIMIT 8""", (cutoff + "T23:59:59", cutoff)))
    return stats


DASHBOARD_PERIODS = {7: "۷ روز اخیر", 30: "۳۰ روز اخیر", 90: "۹۰ روز اخیر", 365: "۱۲ ماه اخیر"}
RECENT_LABEL = DASHBOARD_PERIODS[30]


def recent_bounds(days: int = 30) -> tuple[str, str, str, str]:
    """The last `days` days up to today and the same length just before: a calendar month reads zero on its first day."""
    today = date.fromisoformat(db.today())
    start = today - timedelta(days=days - 1)
    return (start.isoformat(), today.isoformat(),
            (start - timedelta(days=days)).isoformat(), (start - timedelta(days=1)).isoformat())


def _months_back(n: int) -> list[tuple[int, int]]:
    """The last `n` Jalali months up to this one, oldest first."""
    jy, jm, _ = _jalali_today()
    last = jy * 12 + jm - 1
    return [(k // 12, k % 12 + 1) for k in range(last - n + 1, last + 1)]


def dashboard_bounds(days: int) -> tuple[str, str, str, str]:
    """This period and the one before. A year is the last 12 Jalali months (this one so far) against the 12 before,
    so the numbers and the monthly chart cover exactly the same days; shorter periods are rolling days."""
    if days < 365:
        return recent_bounds(days)
    months = _months_back(24)
    return (jalali.month_bounds(*months[12])[0], db.today(), jalali.month_bounds(*months[0])[0],
            jalali.month_bounds(*months[11])[1])


def trend(con, days: int, channel: str = "") -> dict:
    """Revenue over the period next to the period before it, point by point: days for up to 90 days, Jalali months
    for a year."""
    s, e, ps, pe = dashboard_bounds(days)
    if days >= 365:
        revenue = {m["key"]: m["revenue"] for m in monthly_series(con, ps, e, 24, channel)}
        months = [jalali.jalali_month_key(jalali.month_bounds(y, m)[0]) for y, m in _months_back(24)]
        return {"unit": "month", "labels": [jalali.MONTHS[m - 1] for _, m in _months_back(12)],
                "current": [revenue.get(k, 0) for k in months[12:]], "previous": [revenue.get(k, 0) for k in months[:12]]}
    cur, prev = daily_series(con, s, e, channel), daily_series(con, ps, pe, channel)
    return {"unit": "day", "labels": [d["date"] for d in cur], "current": [d["revenue"] for d in cur],
            "previous": [d["revenue"] for d in prev][:len(cur)]}


def dashboard(con, user: dict, days: int = 30, channel: str = "") -> dict:
    days = days if days in DASHBOARD_PERIODS else 30
    channel = channel if channel in ledger.CHANNELS else ""
    today = db.today()
    ms, me, prev_s, prev_e = dashboard_bounds(days)
    today_sales = daily_series(con, today, today, channel)[0]
    site = con.execute(
        """SELECT SUM(CASE WHEN woo_id IS NOT NULL AND woo_state IN ('error', 'gone') THEN 1 ELSE 0 END),
                  SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'nocount' THEN 1 ELSE 0 END),
                  SUM(CASE WHEN woo_id IS NOT NULL AND woo_state = 'whole' THEN 1 ELSE 0 END),
                  SUM(CASE WHEN woo_id IS NULL THEN 1 ELSE 0 END)
           FROM products WHERE active = 1""").fetchone()
    channels = db.rows(con.execute(
        """SELECT channel, COUNT(*) AS orders, SUM(total) AS revenue FROM sales
           WHERE status = 'done' AND date BETWEEN ? AND ? GROUP BY channel ORDER BY revenue DESC""", (ms, me)))
    for c in channels:
        c["label"] = ledger.CHANNELS.get(c["channel"], c["channel"])
    from .site import client
    return {
        "days": days, "channel": channel, "periods": DASHBOARD_PERIODS, "channel_names": ledger.CHANNELS,
        "today": {"orders": today_sales["orders"], "revenue": today_sales["revenue"]},
        "period": _sales_totals(con, ms, me, channel), "period_label": DASHBOARD_PERIODS[days],
        "prev_period": _sales_totals(con, prev_s, prev_e, channel),
        "trend": trend(con, days, channel),
        "channels": channels, "top_products": product_sales(con, ms, me, channel, order="qty DESC, revenue DESC", limit=5),
        "inventory": inventory_stats(con, slow=False),
        "money": ledger.summary_money(con),
        "partners": ledger.partner_positions(con),
        "site": {"configured": client.configured(), "errors": site[0] or 0, "nocount": site[1] or 0,
                 "whole": site[2] or 0, "unlinked": site[3] or 0},
    }
