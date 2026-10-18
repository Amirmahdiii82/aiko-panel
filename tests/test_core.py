"""Core: login, sessions, CSRF, team & permissions, health, backups, storage boundaries."""
import sqlite3

import pytest

from app.core import db

from .conftest import H, as_user, login, make_user


def test_shell_is_served_with_version_and_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "__V__" not in r.text and "/static/js/app.js?v=" in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert r.headers["x-frame-options"] == "DENY"


def test_health_reports_every_module_database(client):
    r = client.get("/healthz").json()
    assert r["ok"] and set(r["databases"]) == {"core", "erp", "pricing", "media"}


def test_login_logout_and_wrong_password(client):
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"username": "amir", "password": "nope"}).status_code == 401
    login(client)
    me = client.get("/api/me").json()
    assert me["user"]["is_admin"] and set(me["user"]["modules"]) == {"erp", "pricing", "media"}
    client.post("/api/logout", headers=H)
    assert client.get("/api/me").status_code == 401


def test_session_tokens_are_stored_hashed(owner):
    token = owner.cookies.get("aiko_session")
    with db.core.read() as con:
        stored = [r[0] for r in con.execute("SELECT token_hash FROM sessions")]
    assert stored and token not in stored and all(len(s) == 64 for s in stored)


def test_state_changes_need_the_csrf_header(owner):
    assert owner.post("/api/erp/products", json={"name": "x"}).status_code == 403
    assert owner.post("/api/erp/products", json={"name": "x"}, headers=H).status_code == 200


def test_login_is_rate_limited(client):
    for _ in range(8):
        client.post("/api/login", json={"username": "amir", "password": "bad"})
    assert client.post("/api/login", json={"username": "amir", "password": "owner-pass"}).status_code == 429


def test_password_change_signs_out_other_devices(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as a, TestClient(app) as b:
        login(a)
        login(b)
        assert a.post("/api/me/password", json={"current": "owner-pass", "new": "newpass1"}, headers=H).status_code == 200
        assert a.get("/api/me").status_code == 200
        assert b.get("/api/me").status_code == 401


def test_module_roles_are_enforced_server_side(owner):
    make_user(owner, "sara", {"erp": "seller"})
    make_user(owner, "neda", {"pricing": "viewer", "media": "viewer"})
    make_user(owner, "omid", {"media": "creator"})

    as_user(owner, "sara")
    assert owner.get("/api/me").json()["user"]["modules"] == {"erp": "seller"}
    assert owner.get("/api/erp/products").status_code == 200
    assert owner.get("/api/erp/money").status_code == 403          # ERP admin only
    assert owner.get("/api/pricing/meta").status_code == 403       # no pricing access at all
    assert owner.get("/api/team").status_code == 403               # owners only

    as_user(owner, "neda")
    assert owner.get("/api/pricing/summary").status_code == 200
    assert owner.post("/api/pricing/crawl", json={}, headers=H).status_code == 403
    assert owner.post("/api/media/generate", json={}, headers=H).status_code == 403
    assert owner.get("/api/erp/me").status_code == 403

    as_user(owner, "omid")
    assert owner.get("/api/media/config").json()["can_create"] is True
    assert owner.get("/api/media/settings").status_code == 403     # key/budget: owners only


def test_home_only_summarises_modules_the_user_can_open(owner):
    make_user(owner, "neda", {"pricing": "viewer"})
    assert set(owner.get("/api/home").json()) == {"erp", "pricing", "media"}
    as_user(owner, "neda")
    assert set(owner.get("/api/home").json()) == {"pricing"}


def test_deactivating_a_user_ends_their_sessions(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as boss, TestClient(app) as staff:
        login(boss)
        uid = make_user(boss, "sara", {"erp": "seller"})
        login(staff, "sara", "secret1")
        assert boss.put(f"/api/team/{uid}", json={"active": False}, headers=H).status_code == 200
        assert staff.get("/api/me").status_code == 401
        assert staff.post("/api/login", json={"username": "sara", "password": "secret1"}).status_code == 401


def test_owner_cannot_lock_themselves_out(owner):
    me = owner.get("/api/me").json()["user"]["id"]
    assert owner.put(f"/api/team/{me}", json={"is_admin": False}, headers=H).status_code == 400
    assert owner.put(f"/api/team/{me}", json={"active": False}, headers=H).status_code == 400


def test_duplicate_usernames_are_rejected(owner):
    make_user(owner, "sara", {"erp": "seller"})
    r = owner.post("/api/team", json={"username": "SARA", "name": "x", "password": "secret1", "grants": {"erp": "seller"}}, headers=H)
    assert r.status_code == 400


def test_activity_feed_is_filtered_per_user(owner):
    owner.post("/api/erp/products", json={"name": "رژ لب", "price": 100, "stock": 3}, headers=H)
    make_user(owner, "neda", {"pricing": "viewer"})
    assert any(a["module"] == "erp" for a in owner.get("/api/activity").json())
    as_user(owner, "neda")
    assert all(a["module"] != "erp" for a in owner.get("/api/activity").json())


def test_module_connections_cannot_write_identity(app):
    erp_db = db.registry["erp"]
    with erp_db.read() as con:
        assert con.execute("SELECT COUNT(*) FROM core.users").fetchone()[0] >= 0   # reading names is allowed
        with pytest.raises(sqlite3.OperationalError):
            con.execute("UPDATE core.users SET is_admin = 1")


def test_migrations_are_idempotent(app):
    for database in db.registry.values():
        before = database.version()
        assert database.migrate() == []
        assert database.version() == before > 0


def test_backup_snapshot_has_every_database(owner, data_dir):
    r = owner.post("/api/system/backup", headers=H)
    assert r.status_code == 200
    folder = data_dir / "backups" / r.json()["name"]
    assert {p.name for p in folder.glob("*.db")} == {"core.db", "erp.db", "pricing.db", "media.db"}
    z = owner.get("/api/system/backup.zip")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"


def test_uploads_require_login_and_stay_inside_the_folder(owner):
    r = owner.post("/api/uploads", files={"file": ("receipt.png", b"\x89PNGdata", "image/png")}, headers=H)
    path = r.json()["path"]
    assert owner.get(f"/uploads/{path}").status_code == 200
    assert owner.get("/uploads/../core.db").status_code == 404
    assert owner.post("/api/uploads", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=H).status_code == 400
    owner.post("/api/logout", headers=H)
    owner.cookies.clear()
    assert owner.get(f"/uploads/{path}").status_code == 401


def test_unknown_api_paths_are_json_404(owner):
    r = owner.get("/api/does-not-exist")
    assert r.status_code == 404 and "detail" in r.json()


def test_scripts_are_revalidated_so_a_deploy_is_never_hidden_by_the_browser_cache(client):
    assert client.get("/static/js/widgets.js").headers["cache-control"] == "no-cache"
    assert client.get("/m/erp/index.js").headers["cache-control"] == "no-cache"
    assert "max-age" in client.get("/static/js/app.js?v=abc").headers["cache-control"]
