"""Website orders → sales with the site's exact figures (line prices, coupons, shipping, fees, refunds).
Webhooks deliver them instantly; pull_orders() reads recently changed orders as a safety net. Idempotent: one order is
one sale (by order id); later changes update or void it.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from .. import db, ledger, notify, receipts
from . import client, matching


COUNTED = {"processing", "completed", "on-hold"}       # WooCommerce has already taken these out of stock


CANCELLED = {"cancelled", "refunded", "failed"}


TEHRAN_OFFSET = "+03:30"


def _map_line(con, product_id: int, variation_id: int | None) -> dict | None:
    if variation_id:
        row = db.one(con.execute("""SELECT id, avg_cost FROM products WHERE active = 1 AND woo_id = ?
                                    AND woo_variation_id = ?""", (product_id, variation_id)))
        if row:
            return row
    return db.one(con.execute("""SELECT id, avg_cost FROM products WHERE active = 1 AND woo_id = ?
                                 AND woo_variation_id IS NULL""", (product_id,)))


def order_figures(order: dict) -> dict:
    """The money of one order exactly as the site has it, in Toman. Line amounts are the site's own
    (not qty × a rounded unit price); `discount` is the coupon share of each line; refunds are taken off."""
    currency = order.get("currency") or client.settings().get("currency") or "IRT"
    lines = []
    for li in order.get("line_items") or []:
        qty = int(li.get("quantity") or 0)
        if qty <= 0:
            continue
        before = client.to_toman(li.get("subtotal"), currency)        # after sale price, before coupons
        after = client.to_toman(li.get("total"), currency)            # after coupons
        lines.append({"woo_id": li.get("product_id") or None, "variation_id": li.get("variation_id") or None,
                      "name": client._clean(li.get("name")), "sku": li.get("sku") or "", "qty": qty,
                      "line_total": before, "discount": max(0, before - after),
                      "unit_price": int(round(before / qty))})
    refunded = sum(abs(client.to_toman(r.get("total"), currency)) for r in order.get("refunds") or [])
    gross = client.to_toman(order.get("total"), currency)
    return {"lines": lines, "gross": gross, "refunded": refunded, "total": max(0, gross - refunded),
            "shipping": client.to_toman(order.get("shipping_total"), currency),
            "fees": sum(client.to_toman(f.get("total"), currency) for f in order.get("fee_lines") or []),
            "tax": client.to_toman(order.get("total_tax"), currency),
            "discount": client.to_toman(order.get("discount_total"), currency)}


def _local_ts(order: dict) -> str:
    raw = (order.get("date_created") or "")[:19]
    return f"{raw}{TEHRAN_OFFSET}" if len(raw) == 19 else db.now()


def process_order(order: dict, *, quiet: bool = False, catalog: dict | None = None) -> str:
    """Create, update or void the sale that mirrors one WooCommerce order. Returns what happened.
    `quiet` (history import): no bot messages or stock alerts, and the sale keeps the order's own time."""
    oid, status = order.get("id"), order.get("status")
    if not oid or not status:
        return "ignored"
    fig = order_figures(order)
    with db.tx() as con:
        existing = db.one(con.execute("SELECT * FROM sales WHERE woo_order_id = ?", (oid,)))
        if status in COUNTED and not existing:
            items, created_products = [], 0
            for li in fig["lines"]:
                mapped = _map_line(con, li["woo_id"], li["variation_id"]) if li["woo_id"] else None
                if mapped:
                    pid = mapped["id"]
                elif li["woo_id"]:
                    pid = matching.ensure_product(con, li, catalog)
                    created_products += 1
                else:
                    pid = None          # a custom line added by hand in the order
                items.append({"product_id": pid, "name": li["name"], "keep_name": True, "qty": li["qty"],
                              "unit_price": li["unit_price"], "line_total": li["line_total"], "discount": li["discount"]})
            if not items:
                return "empty"
            created = (order.get("date_created") or db.today())[:10]
            amount = sum(i["line_total"] - i["discount"] for i in items)
            twin = matching.find_twin(con, created, {i["product_id"] for i in items if i["product_id"]}, amount)
            replaced = None
            if twin:
                # keep the purchase cost the sheet knew for each product; everything else comes from the site
                old = ledger.delete_sale(con, twin["id"])
                costs = {i["product_id"]: i["unit_cost"] for i in old if i["product_id"] and i["unit_cost"]}
                for it in items:
                    if it["product_id"] in costs:
                        it["unit_cost"] = costs[it["product_id"]]
                replaced = twin["code"]
            billing = order.get("billing") or {}
            account = (db.get_setting("channel_accounts", {}, con) or {}).get("website")
            number = order.get("number") or oid
            note = f"سفارش سایت #{number} — {order.get('payment_method_title') or ''}".strip(" —")
            if replaced:
                note += f" (جایگزین {replaced} که دستی/از اکسل ثبت شده بود)"
            sale_id = ledger.create_sale(con, {
                "code": f"WEB-{number}", "date": created, "channel": "website", "source": "site",
                "customer_name": " ".join(filter(None, [billing.get("first_name"), billing.get("last_name")])),
                "customer_phone": billing.get("phone"), "items": items,
                "discount": fig["discount"], "shipping": fig["shipping"], "total": fig["total"],
                "refunded": fig["refunded"], "fees": fig["fees"], "tax": fig["tax"],
                "paid": status != "on-hold", "account_id": account, "woo_order_id": oid, "woo_status": status,
                "note": note,
            }, None, quiet=quiet)
            if quiet:
                ts = _local_ts(order)
                con.execute("UPDATE sales SET created_at = ?, updated_at = ? WHERE id = ?", (ts, ts, sale_id))
                con.execute("UPDATE stock_moves SET created_at = ? WHERE ref_type = 'sale' AND ref_id = ?", (ts, sale_id))
            elif created_products:
                notify.activity(con, "sync_warning", "سفارش سایت محصول تازه‌ای داشت که در انبار ساخته شد",
                                "قیمت خرید این محصول را در انبار وارد کنید تا سود این فروش درست حساب شود.",
                                level="warning", link=f"#/erp/sales/{sale_id}", notify=True)
            if not quiet:            # past orders get theirs from "send old receipts" (Settings → Google Drive)
                con.after_commit.append(lambda: receipts.website_invoice(sale_id))
            return "replaced" if replaced else "created"
        if not existing:
            return "ignored"
        if status in CANCELLED and existing["status"] == "done":
            ledger.void_sale(con, existing["id"], None, f"سفارش در سایت «{status}» شد")
            con.execute("UPDATE sales SET woo_status = ? WHERE id = ?", (status, existing["id"]))
            return "voided"
        if status in COUNTED and existing["status"] == "void":
            if not quiet:
                notify.activity(con, "sync_warning", f"سفارش لغوشده {existing['code']} در سایت دوباره فعال شد",
                                "موجودی خودکار کم نشد؛ لطفاً بررسی کنید و در صورت نیاز فروش را دوباره ثبت کنید.",
                                level="warning", link=f"#/erp/sales/{existing['id']}", notify=True)
        paid = 1 if status in ("processing", "completed") else existing["paid"]
        changed_money = existing["status"] == "done" and (fig["total"], fig["refunded"]) != (existing["total"], existing["refunded"])
        con.execute("""UPDATE sales SET woo_status = ?, paid = ?, total = ?, refunded = ?, shipping = ?, fees = ?, tax = ?,
                       updated_at = ? WHERE id = ?""",
                    (status, paid, fig["total"] if existing["status"] == "done" else existing["total"], fig["refunded"],
                     fig["shipping"], fig["fees"], fig["tax"], db.now(), existing["id"]))
        if changed_money and not quiet:
            notify.activity(con, "sync_warning", f"مبلغ سفارش سایت {existing['code']} تغییر کرد",
                            f"{ledger.toman(existing['total'])} ← {ledger.toman(fig['total'])}"
                            + (f" (برگشت وجه {ledger.toman(fig['refunded'])})" if fig["refunded"] else ""),
                            level="warning", link=f"#/erp/sales/{existing['id']}", notify=True)
        if changed_money:            # a refund or a changed order: a new invoice replaces the old one
            con.after_commit.append(lambda: receipts.website_invoice(existing["id"]))
        notify.publish_after(con, {"type": "refresh", "scope": "sales"})
        return "updated"


async def pull_orders(since_iso: str | None = None) -> dict:
    s = client.settings()
    if not client.configured(s):
        return {"created": 0}
    since = since_iso or s.get("last_order_sync")
    if not since:
        since = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        client._save_woo({"last_order_sync": since})
        return {"created": 0, "note": "از این لحظه به بعد سفارش‌ها خوانده می‌شوند"}
    started = datetime.now(timezone.utc).replace(microsecond=0)
    # a small overlap so an order modified during the previous request is never missed
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) - timedelta(minutes=2)
    counts: dict[str, int] = {}
    async with client.Woo(s) as woo:
        orders = await woo.paged("orders", {"modified_after": since_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                                            "dates_are_gmt": "true", "orderby": "date", "order": "asc"}, limit_pages=100)
    quiet = since_iso is not None            # reading history by hand: no message per old order
    for order in orders:
        result = await asyncio.to_thread(process_order, order, quiet=quiet)
        counts[result] = counts.get(result, 0) + 1
    client._save_woo({"last_order_sync": started.isoformat()})
    if orders:
        client.wlog("pull_orders", True, f"{len(orders)} سفارش بررسی شد: {counts}")
    return counts
