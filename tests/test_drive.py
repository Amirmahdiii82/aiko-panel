"""Receipts in Google Drive: connecting, tidy folders, replacing a receipt, the size cap, small photos, website
invoices — against a fake Google."""
import asyncio
import io
import json
import re

import httpx
import pytest

from app.core import config, db as core_db, drive, integrations
from app.modules.erp import db, ledger, receipts
from app.modules.erp.site import orders

from .conftest import H


class FakeGoogle:
    def __init__(self):
        self.files: dict[str, dict] = {}
        self.n = 0

    def _id(self):
        self.n += 1
        return f"f{self.n}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, method = str(request.url), request.method
        if url.startswith(drive.TOKEN_URL):
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600, "refresh_token": "rt"})
        if "userinfo" in url:
            return httpx.Response(200, json={"email": "owner@gmail.com"})
        if url.startswith(drive.UPLOAD):
            body = request.content
            meta = json.loads(re.search(rb"\r\n\r\n(\{.*?\})\r\n", body, re.S).group(1))
            fid = self._id()
            self.files[fid] = {**meta, "size": len(body), "trashed": False, "folder": False}
            return httpx.Response(200, json={"id": fid})
        m = re.search(r"/drive/v3/files/(\w+)", url)
        if m:
            f = self.files.get(m.group(1))
            if not f:
                return httpx.Response(404, json={})
            if method == "PATCH":
                f.update(json.loads(request.content))
            return httpx.Response(200, json={"id": m.group(1), "trashed": f["trashed"]})
        if url.startswith(f"{drive.API}/files") and method == "POST":
            meta = json.loads(request.content)
            fid = self._id()
            self.files[fid] = {**meta, "trashed": False, "folder": True}
            return httpx.Response(200, json={"id": fid})
        if url.startswith(f"{drive.API}/about"):
            return httpx.Response(200, json={"storageQuota": {"limit": "16106127360", "usage": "1000"}})
        raise AssertionError(url)

    def path_of(self, fid: str) -> str:
        parts, f = [], self.files[fid]
        while True:
            parts.append(f["name"])
            parent = (f.get("parents") or [None])[0]
            if not parent:
                return "/".join(reversed(parts))
            f = self.files[parent]

    def live_uploads(self):
        return {fid: f for fid, f in self.files.items() if not f["folder"] and not f["trashed"]}


STEP = drive._step


@pytest.fixture
def google(owner, monkeypatch):
    fake = FakeGoogle()

    async def idle():                       # the app's own background worker stays out of the way
        return False
    monkeypatch.setattr(drive, "_step", idle)
    monkeypatch.setattr(integrations, "abroad_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    drive._token.update(value="", expires=0)
    r = owner.put("/api/drive", json={"client_id": "cid", "client_secret": "csecret"}, headers=H)
    assert r.status_code == 200, r.text
    r = owner.get("/api/drive/connect", follow_redirects=False)
    state = re.search(r"state=([^&]+)", r.headers["location"]).group(1)
    assert "drive.file" in r.headers["location"].replace("%2F", "/")
    r = owner.get(f"/api/drive/callback?code=abc&state={state}", follow_redirects=False)
    assert r.headers["location"].endswith("/#/settings/drive") and drive.connected()
    return fake


def pump():
    async def go():
        while await STEP():
            pass
    asyncio.run(go())


def upload(owner, name="receipt.jpg", size=(3000, 2000)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 120, 90)).save(buf, "PNG")
    r = owner.post("/api/uploads", files={"file": (name.replace(".jpg", ".png"), buf.getvalue(), "image/png")}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["path"], len(buf.getvalue())


def test_connecting_creates_one_tidy_root_folder(google):
    assert drive.connected() and drive.settings()["email"] == "owner@gmail.com"
    roots = [f for f in google.files.values() if f["folder"] and not f.get("parents")]
    assert [f["name"] for f in roots] == [drive.ROOT_NAME]


def test_a_purchase_receipt_lands_in_its_month_and_kind_folder(google, owner):
    path, raw = upload(owner)
    assert path.endswith(".jpg") and (config.UPLOAD_DIR / path).stat().st_size < raw     # the photo was shrunk
    with db.tx() as con:
        pid = ledger.create_product(con, {"name": "رژ لب"}, None, quiet=True)
    r = owner.post("/api/erp/purchases", json={"date": "2026-10-22", "supplier": "بازار تهران", "receipt": path,
                                               "items": [{"product_id": pid, "qty": 2, "unit_cost": 415_000}]}, headers=H)
    assert r.status_code == 200, r.text
    pump()
    (fid, f), = google.live_uploads().items()
    assert google.path_of(fid) == f"{drive.ROOT_NAME}/۱۴۰۵/۰۷ مهر/خرید کالا/۳۰ — P-{r.json()['id']} — بازار تهران — ۸۳۰٬۰۰۰ تومان.jpg"
    detail = owner.get(f"/api/erp/purchases/{r.json()['id']}").json()
    assert detail["drive"] == f"https://drive.google.com/file/d/{fid}/view"


def test_replacing_a_receipt_trashes_the_old_file(google, owner):
    first, _ = upload(owner)
    with db.tx() as con:
        sale_id = ledger.create_sale(con, {"date": "2026-10-22", "customer_name": "مریم", "receipt": first,
                                           "items": [{"name": "کالا", "qty": 1, "unit_price": 100_000}]}, None, quiet=True)
    receipts.send("sale", sale_id)
    pump()
    second, _ = upload(owner)
    r = owner.put(f"/api/erp/sales/{sale_id}/receipt", json={"receipt": second}, headers=H)
    assert r.status_code == 200, r.text
    pump()
    live = google.live_uploads()
    assert len(live) == 1 and "/فروش/" in google.path_of(next(iter(live)))
    assert sum(1 for f in google.files.values() if f["trashed"]) == 1


def test_the_size_cap_holds_files_back_instead_of_filling_the_drive(google, owner):
    drive.save({"cap_mb": 0})
    path, _ = upload(owner)
    with db.tx() as con:
        eid = ledger.save_expense(con, {"date": "2026-10-22", "category": "تبلیغات", "amount": 2_000_000, "receipt": path},
                                  {"id": None, "name": "امیر"})
    receipts.send("expense", eid)
    pump()
    assert google.live_uploads() == {} and drive.usage()["held"] == 1
    with core_db.core.read() as con:
        assert con.execute("SELECT COUNT(*) FROM activity WHERE kind = 'drive' AND title LIKE '%سقف%'").fetchone()[0] == 1
    owner.put("/api/drive", json={"cap_mb": 500}, headers=H)                       # more room: it goes now
    pump()
    assert len(google.live_uploads()) == 1


def test_every_website_order_gets_a_small_invoice_pdf_in_drive(google):
    order = {"id": 900, "number": "900", "status": "processing", "currency": "IRT", "date_created": "2026-10-22T11:20:00",
             "line_items": [{"product_id": 0, "variation_id": 0, "name": "رژگونه استیکی شیگلم Buttery Bliss", "quantity": 2,
                             "subtotal": "970000", "total": "970000"}],
             "shipping_total": "60000", "discount_total": "0", "total": "1030000", "total_tax": "0", "fee_lines": [],
             "refunds": [], "billing": {"first_name": "مریم", "last_name": "الف", "phone": "0912"},
             "payment_method_title": "زرین‌پال"}
    assert orders.process_order(order) == "created"
    with db.read() as con:
        sale = db.one(con.execute("SELECT * FROM sales WHERE woo_order_id = 900"))
    pdf = config.UPLOAD_DIR / sale["receipt"]
    assert pdf.read_bytes()[:4] == b"%PDF" and pdf.stat().st_size < 60_000
    pump()
    (fid, f), = google.live_uploads().items()
    assert google.path_of(fid).endswith("۱۴۰۵/۰۷ مهر/فروش سایت/۳۰ — WEB-900 — مریم الف — ۱٬۰۳۰٬۰۰۰ تومان.pdf")
    order["refunds"] = [{"id": 1, "total": "-60000"}]          # a refund: a new invoice replaces the old one
    assert orders.process_order(order) == "updated"
    pump()
    assert len(google.live_uploads()) == 1 and "۹۷۰٬۰۰۰" in google.path_of(next(iter(google.live_uploads())))


def test_old_receipts_can_be_sent_once_drive_is_connected(google, owner):
    path, _ = upload(owner)
    with db.tx() as con:
        con.execute("""INSERT INTO expenses (date, category, amount, receipt, created_at) VALUES
                       ('2026-09-01', 'ارسال و پست', 50000, ?, '2026-09-01')""", (path,))
    r = owner.post("/api/drive/backfill", headers=H)
    assert r.status_code == 200 and r.json()["queued"] == 1
    pump()
    assert "/۱۴۰۵/۰۶ شهریور/هزینه‌ها/" in google.path_of(next(iter(google.live_uploads())))
