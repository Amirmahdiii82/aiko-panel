"""Which panel product is which site product: exact matches (SKU, same name), suggestions for a person, a panel
product for every site product that has none, and likely duplicates to merge.
"""
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from ....core.text import fold
from .. import db, ledger, notify


_STOP = {"مدل", "شماره", "رنگ", "کد", "و", "با", "|", "-", "—", "–"}


def normalize(text: str) -> str:
    text = fold(text)
    text = re.sub(r"[()\[\]|،,:;/\\\-–—_+&#.!?\"']", " ", text)
    return " ".join(t for t in text.split() if t not in _STOP)


def score(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    ratio = SequenceMatcher(None, na, nb).ratio()
    return round(0.7 * overlap + 0.3 * ratio, 3)


def _price_factor(ours: int, theirs: int) -> float:
    if not ours or not theirs:
        return 0.0
    r = max(ours, theirs) / min(ours, theirs)
    return 0.05 if r <= 1.15 else (-0.1 if r >= 2 else 0.0)


def suggestions(con, catalog: dict) -> list[dict]:
    """For every unlinked product, up to 3 different site products whose names look most alike.
    Colors of one site product are not offered as separate rivals: the whole product is suggested,
    unless one color clearly matches better (its name is in our product name)."""
    items = catalog.get("items") or []
    linked = {(r[0], r[1]) for r in con.execute(
        "SELECT woo_id, woo_variation_id FROM products WHERE active = 1 AND woo_id IS NOT NULL")}
    whole_linked = {w for w, v in linked if v is None}
    out = []
    for p in con.execute("SELECT id, name, brand, stock, price FROM products WHERE active = 1 AND woo_id IS NULL"):
        name = f"{p['name']} {p['brand'] or ''}"
        best: dict[int, tuple[float, dict]] = {}
        for e in items:
            if (e["woo_id"], e["variation_id"]) in linked or (e["variation_id"] and e["woo_id"] in whole_linked):
                continue
            sc = score(name, e["name"]) + _price_factor(p["price"], e.get("price") or 0)
            if e["variation_id"]:
                sc -= 0.06          # prefer the whole product unless the color is clearly meant
            cur = best.get(e["woo_id"])
            if cur is None or sc > cur[0]:
                best[e["woo_id"]] = (sc, e)
        ranked = sorted(best.values(), key=lambda x: -x[0])[:3]
        out.append({"product": dict(p), "candidates": [{**e, "score": round(min(sc, 1.0), 3)} for sc, e in ranked if sc >= 0.3]})
    return out


def link_product(con, product_id: int, woo_id: int, variation_id: int | None, catalog: dict | None) -> None:
    clash = con.execute("""SELECT name FROM products WHERE active = 1 AND id != ? AND woo_id = ?
                           AND IFNULL(woo_variation_id, 0) = ?""", (product_id, woo_id, variation_id or 0)).fetchone()
    if clash:
        raise ledger.LedgerError(f"این محصول سایت قبلاً به «{clash[0]}» وصل شده")
    entry = next((e for e in (catalog or {}).get("items", [])
                  if e["woo_id"] == woo_id and e["variation_id"] == variation_id), {})
    con.execute("""UPDATE products SET woo_id = ?, woo_variation_id = ?, woo_name = ?, woo_url = ?,
                   image = COALESCE(?, image), woo_stock = ?, woo_state = NULL, woo_error = NULL, woo_price = NULL,
                   woo_manage = NULL, woo_counted = 0, updated_at = ? WHERE id = ?""",
                (woo_id, variation_id, entry.get("name"), entry.get("url"), entry.get("image"), entry.get("stock"),
                 db.now(), product_id))
    notify.publish_after(con, {"type": "refresh", "scope": "products"})


def ensure_product(con, line: dict, catalog: dict | None = None) -> int:
    """A warehouse product for a site order line that has none yet. Every site product must exist here,
    otherwise its sale would not reduce stock and would have no cost. Reuses a panel product with the same
    SKU or the same name (linking it); otherwise creates one, linked to the site product/color."""
    items = (catalog or db.get_setting("woo_catalog", {}) or {}).get("items") or []
    key = (line["woo_id"], line["variation_id"])
    entry = next((e for e in items if (e["woo_id"], e["variation_id"]) == key), None)
    parent = next((e for e in items if e["woo_id"] == line["woo_id"] and e["variation_id"] is None), None)
    on_site = entry is not None or not items      # no catalogue read yet: the order itself proves it is on the site
    name = (entry or {}).get("name") or line["name"]
    sku = (line.get("sku") or (entry or {}).get("sku") or "").strip()
    unlinked = db.rows(con.execute("SELECT id, sku, name FROM products WHERE active = 1 AND woo_id IS NULL"))
    match = next((p for p in unlinked if sku and p["sku"] == sku), None) or \
        next((p for p in unlinked if normalize(p["name"]) in (normalize(name), normalize(line["name"]))), None)
    if match and on_site:
        link_product(con, match["id"], line["woo_id"], line["variation_id"], catalog)
        return match["id"]
    if match:
        return match["id"]
    if sku and con.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone():
        sku = ""
    info = entry or parent or {}
    pid = ledger.create_product(con, {
        "name": name, "sku": sku, "price": (entry or {}).get("price") or line["unit_price"],
        "category": _category(con, info.get("categories") or []), "brand": info.get("brand") or None,
        "image": info.get("image"), "woo_id": line["woo_id"] if on_site else None,
        "woo_variation_id": line["variation_id"] if on_site else None, "woo_name": name if on_site else None,
        "woo_url": info.get("url"), "notes": None if on_site else "از سفارش‌های قدیمی سایت (این محصول دیگر در سایت نیست)",
    }, None, quiet=True)
    con.execute("UPDATE products SET site_created = 1, woo_stock = ? WHERE id = ?", ((entry or {}).get("stock"), pid))
    return pid


def _category(con, site_categories: list[str]) -> str | None:
    """The site's category, mapped to one of the shop's own categories when the names are close."""
    if not site_categories:
        return None
    ours = db.get_setting("product_categories", [], con) or []
    for c in site_categories:
        for o in ours:
            if normalize(o) and (normalize(o) in normalize(c) or normalize(c) in normalize(o)):
                return o
    return site_categories[0]


def find_twin(con, day: str, product_ids: set[int], amount: int, exclude: set[int] | None = None) -> dict | None:
    """A website sale typed in by hand or imported from the sheet that is the same purchase as a site order:
    within 3 days and with the same products or the same item amount. The site's figures replace it."""
    d = datetime.fromisoformat(day[:10]).date()
    rows = db.rows(con.execute(
        """SELECT id, code, date, subtotal, discount FROM sales WHERE status = 'done' AND channel = 'website'
           AND woo_order_id IS NULL AND date BETWEEN ? AND ?""",
        ((d - timedelta(days=3)).isoformat(), (d + timedelta(days=3)).isoformat())))
    best, best_key = None, None
    for r in rows:
        if exclude and r["id"] in exclude:
            continue
        theirs = {x[0] for x in con.execute("SELECT product_id FROM sale_items WHERE sale_id = ? AND product_id IS NOT NULL",
                                            (r["id"],))}
        union = product_ids | theirs
        overlap = len(product_ids & theirs) / len(union) if union else 0
        amt = r["subtotal"] - r["discount"]
        amount_ok = amount > 0 and abs(amt - amount) <= max(1000, amount * 0.02)
        if overlap < 0.5 and not amount_ok:
            continue
        key = (overlap >= 0.5 and amount_ok, overlap, amount_ok, -abs((datetime.fromisoformat(r["date"]).date() - d).days))
        if best_key is None or key > best_key:
            best, best_key = r, key
    return best


def _linked_keys(con) -> tuple[set, set]:
    linked = {(r[0], r[1]) for r in con.execute(
        "SELECT woo_id, woo_variation_id FROM products WHERE active = 1 AND woo_id IS NOT NULL")}
    return linked, {w for w, v in linked if v is None}


def link_certain(con, catalog: dict) -> int:
    """Same SKU, or the same name once spacing/Arabic letters/punctuation are evened out."""
    entries = catalog.get("items") or []
    done = 0
    for p in db.rows(con.execute("SELECT id, sku, name FROM products WHERE active = 1 AND woo_id IS NULL")):
        linked, whole = _linked_keys(con)
        free = [e for e in entries if (e["woo_id"], e["variation_id"]) not in linked
                and not (e["variation_id"] and e["woo_id"] in whole)]
        hit = [e for e in free if p["sku"] and e.get("sku") and e["sku"].strip() == p["sku"].strip()]
        if not hit:
            name = normalize(p["name"])
            hit = [e for e in free if name and normalize(e["name"]) == name]
        if len(hit) == 1:
            link_product(con, p["id"], hit[0]["woo_id"], hit[0]["variation_id"], catalog)
            done += 1
    return done


def create_missing(con, catalog: dict) -> int:
    """One panel product for every site product (simple products) or every color (variable products) that has none."""
    entries = catalog.get("items") or []
    has_variations = {e["woo_id"] for e in entries if e["variation_id"]}
    created = 0
    for e in entries:
        linked, whole = _linked_keys(con)
        key = (e["woo_id"], e["variation_id"])
        if key in linked:
            continue
        if e["variation_id"] is None and e["woo_id"] in has_variations:
            continue                                  # a variable product: its colors are the stock items
        if e["variation_id"] and (e["woo_id"] in whole):
            continue                                  # tracked as one product with all its colors
        if e.get("status") in ("trash",):
            continue
        ensure_product(con, {"woo_id": e["woo_id"], "variation_id": e["variation_id"], "name": e["name"],
                                 "sku": e.get("sku") or "", "unit_price": e.get("price") or 0}, catalog)
        created += 1
    return created


def settle_openings(con, entries: list[dict]) -> int:
    """Products created from the site start with the site's stock (their past sales are already recorded,
    so the opening is site stock + what was sold). Without a stock number on the site, stock is set to 0."""
    by_key = {(e["woo_id"], e["variation_id"]): e for e in entries}
    n = 0
    for p in db.rows(con.execute("SELECT * FROM products WHERE active = 1 AND site_created = 1")):
        e = by_key.get((p["woo_id"], p["woo_variation_id"])) if p["woo_id"] else None
        site_stock = e.get("stock") if e and e.get("manage_stock") and isinstance(e.get("stock"), int) else None
        target = max(0, site_stock) if site_stock is not None else max(0, p["stock"])
        delta = target - p["stock"]
        if delta:
            ledger.add_move(con, p["id"], delta, "opening", ref_type="site", quiet=True,
                            note="موجودی اولیه (هماهنگ با سایت)" if site_stock is not None
                            else "موجودی اولیه (سایت عدد موجودی ندارد)")
            first = con.execute("""SELECT MIN(created_at) FROM stock_moves WHERE product_id = ? AND kind != 'opening'""",
                                (p["id"],)).fetchone()[0]
            if first:
                con.execute("""UPDATE stock_moves SET created_at = ? WHERE id = (SELECT MAX(id) FROM stock_moves
                               WHERE product_id = ? AND kind = 'opening')""", (first, p["id"]))
            n += 1
        con.execute("UPDATE products SET site_created = 0, woo_stock = ? WHERE id = ?",
                    (site_stock if site_stock is not None else p["woo_stock"], p["id"]))
    return n


def duplicates(con, limit: int = 40) -> list[dict]:
    """Panel products that are not on the site next to a site product with a similar name: probably the same
    item recorded twice (e.g. once in the sheet, once on the site). Offered for merging, never merged alone."""
    loose = db.rows(con.execute(
        """SELECT p.id, p.sku, p.name, p.stock, p.image,
                  (SELECT COUNT(*) FROM sale_items i WHERE i.product_id = p.id) AS sales
           FROM products p WHERE p.active = 1 AND p.woo_id IS NULL"""))
    linked = db.rows(con.execute(
        "SELECT id, sku, name, stock, image, woo_name FROM products WHERE active = 1 AND woo_id IS NOT NULL"))
    out = []
    for p in loose:
        best, best_score = None, 0.0
        for q in linked:
            sc = max(score(p["name"], q["name"]), score(p["name"], q["woo_name"] or ""))
            if sc > best_score:
                best, best_score = q, sc
        if best and best_score >= 0.6:
            out.append({"product": p, "site_product": best, "strong": best_score >= 0.8})
    out.sort(key=lambda d: (not d["strong"], d["product"]["name"]))
    return out[:limit]
