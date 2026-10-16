"""Pricing API on its own database, and the one-time import from the old standalone apps."""
import json
import sqlite3
from pathlib import Path

from app.core import auth, db, legacy, modules

from .conftest import H

ROOT = Path(__file__).resolve().parents[1] / "app" / "modules"


def test_pricing_api_on_an_empty_database(owner):
    meta = owner.get("/api/pricing/meta").json()
    assert len(meta["sites"]) >= 5 and meta["running"] is False
    s = owner.get("/api/pricing/summary").json()
    assert s["products"] == 0 and s["pending_reviews"] == 0
    assert owner.get("/api/pricing/products").json()["total"] == 0
    assert owner.get("/api/pricing/export.csv").status_code == 200
    assert owner.post("/api/pricing/sites/digikala", json={"in_stats": False}, headers=H).status_code == 200
    assert next(x for x in owner.get("/api/pricing/meta").json()["sites"] if x["key"] == "digikala")["in_stats"] is False


def test_offer_review_flow(owner):
    pricing_db = modules.loaded["pricing"].databases[0]
    with pricing_db.tx() as con:
        con.execute("INSERT INTO products (id, name, price, in_stock, active, tracked) VALUES (1, 'ریمل', 300000, 1, 1, 1)")
        con.execute("""INSERT INTO offers (product_id, site, external_id, title, score, status, price, in_stock, reasons, extra, last_seen)
                       VALUES (1, 'digikala', 'dkp-1', 'ریمل مشابه', 0.6, 'pending', 290000, 1, '[]', '{}', ?)""", (db.utcnow(),))
    q = owner.get("/api/pricing/review").json()
    assert q["total"] == 1
    oid = q["items"][0]["id"]
    assert owner.post(f"/api/pricing/offers/{oid}/status", json={"status": "confirmed"}, headers=H).status_code == 200
    assert owner.get("/api/pricing/review").json()["total"] == 0
    detail = owner.get("/api/pricing/products/1").json()
    assert detail["offers"][0]["status"] == "confirmed"


def _old_erp_db(path: Path) -> None:
    """An old standalone ERP database: today's ERP tables plus its own users / sessions / activity."""
    con = sqlite3.connect(path)
    con.executescript((ROOT / "erp" / "migrations" / "0001_init.sql").read_text())
    con.executescript("""
      DROP TABLE staff;
      CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, name TEXT, password_hash TEXT, role TEXT, partner_id INTEGER,
        account_id INTEGER, commission_pct REAL DEFAULT 0, active INTEGER DEFAULT 1, notif_seen INTEGER DEFAULT 0, created_at TEXT);
      CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, expires_at TEXT);
      CREATE TABLE activity (id INTEGER PRIMARY KEY, created_at TEXT, user_id INTEGER, kind TEXT, level TEXT, title TEXT, body TEXT,
        link TEXT, notify INTEGER);
      INSERT INTO partners (id, name, share) VALUES (1, 'امیر', 50), (2, 'تینا', 50);
      INSERT INTO accounts (id, name, kind, partner_id) VALUES (1, 'کارت امیر', 'partner', 1), (2, 'کارت تینا', 'partner', 2);
      INSERT INTO accounts (id, name, kind, user_id) VALUES (3, 'پول نزد سارا', 'agent', 3);
      INSERT INTO products (id, name, price, stock, created_at, updated_at) VALUES (1, 'رژ', 100000, 4, '2026-01-01', '2026-01-01');
      INSERT INTO activity (created_at, user_id, kind, level, title, link, notify) VALUES ('2026-01-01T10:00:00+03:30', 1, 'sale', 'success', 'فروش', '#/sales/1', 1);
      INSERT INTO settings (key, value) VALUES ('notify', '{"bot": "bale", "token": "123:abc", "chat_ids": "42", "on_sale": false}');
      INSERT INTO settings (key, value) VALUES ('shop', '{"name": "آیکو", "low_stock": 3}');
    """)
    pw = auth.hash_password("old-pass")
    con.execute("INSERT INTO users VALUES (1, 'amir', 'امیر', ?, 'admin', 1, 1, 0, 1, 0, '2026-01-01')", (pw,))
    con.execute("INSERT INTO users VALUES (3, 'sara', 'سارا', ?, 'seller', NULL, 3, 12.5, 1, 0, '2026-01-01')", (pw,))
    con.commit()
    con.close()


def test_import_legacy_erp_and_pricing(app, data_dir, tmp_path_factory):
    src = tmp_path_factory.mktemp("legacy")
    _old_erp_db(src / "aiko.db")
    prices = src / "prices.db"
    con = sqlite3.connect(prices)
    con.executescript((ROOT / "pricing" / "migrations" / "0001_init.sql").read_text().replace("    size_hint       TEXT,                          -- size from product attributes when the title has none\n", ""))
    con.execute("INSERT INTO products (id, name, price) VALUES (7, 'کرم', 50000)")
    con.commit()
    con.close()

    # the app fixture already bootstrapped nothing (no lifespan ran), so core is empty
    out = {"erp": legacy.import_erp(src / "aiko.db"), "pricing": legacy.import_pricing(prices)}
    assert out["erp"]["users"] == 2 and out["erp"]["products"] == 1 and out["erp"]["staff"] == 2
    assert out["pricing"]["products"] == 1

    with db.core.read() as con:
        users = {r["username"]: dict(r) for r in con.execute("SELECT * FROM users")}
        grants = [tuple(r) for r in con.execute("SELECT user_id, module, role FROM user_modules")]
        act = con.execute("SELECT module, link FROM activity").fetchone()
    assert users["amir"]["is_admin"] == 1 and users["sara"]["is_admin"] == 0
    assert grants == [(3, "erp", "seller")]
    assert tuple(act) == ("erp", "#/erp/sales/1")
    assert auth.verify_password("old-pass", users["sara"]["password_hash"])          # passwords carried over
    notify = db.core.get_setting("notify")
    assert notify["token"] == "123:abc" and notify["kinds"]["erp.sale"] is False

    erp_db = modules.loaded["erp"].databases[0]
    with erp_db.read() as con:
        sara = dict(con.execute("SELECT * FROM users WHERE username = 'sara'").fetchone())      # the ERP view of core identity
        assert sara["role"] == "seller" and sara["account_id"] == 3 and sara["commission_pct"] == 12.5
        assert con.execute("SELECT COUNT(*) FROM settings WHERE key = 'notify'").fetchone()[0] == 0
        assert json.loads(con.execute("SELECT value FROM settings WHERE key = 'shop'").fetchone()[0])["low_stock"] == 3

    pricing_db = modules.loaded["pricing"].databases[0]
    assert pricing_db.version() == 2
    with pricing_db.read() as con:
        assert "size_hint" in {r[1] for r in con.execute("PRAGMA table_info(products)")}
