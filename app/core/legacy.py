"""One-time move from the old separate apps into the panel.

    python -m app import-legacy --erp /opt/aiko-erp/data/aiko.db --pricing /opt/price-checker/data/prices.db \
                                --uploads /opt/aiko-erp/data/uploads

Run it on a fresh data directory, before the first `serve`:
* ERP: users → core (same ids, same passwords; old admins become owners, sellers get the ERP "seller" role),
  their commission/partner/account → ERP staff profiles, the activity feed → core feed, bot settings → core
  notification settings, every business table copied as-is.
* Pricing: the database is adopted unchanged (same schema) and brought to the latest migration.
* Media: the old studio kept history only in the browser, so there is nothing to move.
Old databases are opened read-only and never modified.
"""
import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from . import config, db
from .modules import loaded as modules

ERP_TABLES = ["settings", "partners", "accounts", "products", "stock_moves", "sales", "sale_items", "purchases",
              "purchase_items", "expenses", "capital", "transfers", "woo_log"]
FLAG_TO_KIND = {"on_sale": "sale", "on_web_order": "web_order", "on_stock_out": "stock_out", "on_low_stock": "low_stock",
                "on_sync_error": "sync_error"}


def _ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _cols(con, schema: str, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA {schema}.table_info({table})")]


def import_erp(path: Path, *, force: bool = False) -> dict:
    erp = modules.get("erp")
    if not erp:
        raise SystemExit("ERP module is not enabled (MODULES)")
    erp_db = erp.databases[0]
    old = _ro(path)
    report: dict = {}
    with db.core.tx() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] and not force:
            raise SystemExit("core.db already has users — run on a fresh data directory (or pass --force)")
        users = [dict(r) for r in old.execute("SELECT * FROM users ORDER BY id")]
        for u in users:
            con.execute("INSERT OR REPLACE INTO users (id, username, name, password_hash, is_admin, active, notif_seen, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (u["id"], u["username"], u["name"], u["password_hash"], 1 if u["role"] == "admin" else 0,
                         u["active"], u.get("notif_seen") or 0, u["created_at"]))
            if u["role"] != "admin":
                con.execute("INSERT OR REPLACE INTO user_modules (user_id, module, role) VALUES (?, 'erp', ?)", (u["id"], u["role"]))
        report["users"] = len(users)
        acts = old.execute("SELECT * FROM activity ORDER BY id").fetchall()
        for a in acts:
            link = (a["link"] or "").replace("#/", "#/erp/", 1) if (a["link"] or "").startswith("#/") else a["link"]
            con.execute("INSERT INTO activity (created_at, module, user_id, kind, level, title, body, link, notify) "
                        "VALUES (?, 'erp', ?, ?, ?, ?, ?, ?, ?)",
                        (a["created_at"], a["user_id"], a["kind"], a["level"], a["title"], a["body"], link, a["notify"]))
        report["activity"] = len(acts)
        row = old.execute("SELECT value FROM settings WHERE key = 'notify'").fetchone()
        if row and row[0]:
            n = json.loads(row[0])
            db.core.set_setting("notify", {"bot": n.get("bot") or "bale", "token": n.get("token") or "",
                                           "chat_ids": n.get("chat_ids") or "",
                                           "kinds": {f"erp.{k}": bool(n.get(f, True)) for f, k in FLAG_TO_KIND.items()}}, con)
    old.close()

    con = erp_db.connect()
    try:
        con.execute("ATTACH DATABASE ? AS legacy", (f"{path.resolve().as_uri()}?mode=ro",))
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT COUNT(*) FROM main.products").fetchone()[0] and not force:
            raise SystemExit("erp.db already has products — run on a fresh data directory (or pass --force)")
        for table in ERP_TABLES:
            if table not in {r[0] for r in con.execute("SELECT name FROM legacy.sqlite_master WHERE type = 'table'")}:
                continue
            cols = [c for c in _cols(con, "main", table) if c in set(_cols(con, "legacy", table))]
            col_sql = ", ".join(cols)
            con.execute(f"DELETE FROM main.{table}")
            where = " WHERE key != 'notify'" if table == "settings" else ""
            n = con.execute(f"INSERT INTO main.{table} ({col_sql}) SELECT {col_sql} FROM legacy.{table}{where}").rowcount
            report[table] = n
        n = con.execute("""INSERT OR REPLACE INTO main.staff (user_id, partner_id, account_id, commission_pct)
                           SELECT id, partner_id, account_id, IFNULL(commission_pct, 0) FROM legacy.users""").rowcount
        report["staff"] = n
        problems = con.execute("PRAGMA main.foreign_key_check").fetchall()
        if problems:
            raise SystemExit(f"foreign key problems after import: {problems[:5]}")
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return report


def import_pricing(path: Path, *, force: bool = False) -> dict:
    pricing = modules.get("pricing")
    if not pricing:
        raise SystemExit("pricing module is not enabled (MODULES)")
    target = pricing.databases[0]
    if target.path.exists():
        with target.read() as con:
            if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] and not force:
                raise SystemExit("pricing.db already has products — run on a fresh data directory (or pass --force)")
    for suffix in ("", "-wal", "-shm"):
        Path(str(target.path) + suffix).unlink(missing_ok=True)
    src = _ro(path)
    dst = sqlite3.connect(target.path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with sqlite3.connect(target.path) as con:
        con.execute("PRAGMA user_version = 0")      # let the migrations adopt it (all IF NOT EXISTS)
    target.migrate()
    with target.read() as con:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("products", "offers", "crawls", "new_products")}


def copy_uploads(src: Path) -> int:
    n = 0
    for f in src.rglob("*"):
        if f.is_file():
            dest = config.UPLOAD_DIR / f.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(f, dest)
                n += 1
    return n


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="python -m app import-legacy")
    p.add_argument("--erp", type=Path, help="old ERP database (aiko.db)")
    p.add_argument("--pricing", type=Path, help="old price checker database (prices.db)")
    p.add_argument("--uploads", type=Path, help="old ERP uploads folder (receipt photos)")
    p.add_argument("--force", action="store_true", help="overwrite data that already exists")
    a = p.parse_args(argv)
    if not (a.erp or a.pricing or a.uploads):
        p.print_help()
        sys.exit(1)
    out = {}
    if a.erp:
        out["erp"] = import_erp(a.erp, force=a.force)
    if a.pricing:
        out["pricing"] = import_pricing(a.pricing, force=a.force)
    if a.uploads:
        out["uploads"] = copy_uploads(a.uploads)
    print(json.dumps(out, ensure_ascii=False, indent=2))
