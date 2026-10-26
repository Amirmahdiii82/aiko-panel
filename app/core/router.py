"""Core HTTP API: login, the signed-in user, team & permissions, unified home, activity feed,
live stream, notification settings, system/backup and file uploads."""
import asyncio
import logging
import platform
import shutil
import sqlite3
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

from . import activity, auth, backup, bot, config, db, drive, events, integrations, jobs
from .modules import loaded as modules

log = logging.getLogger("aiko.core")
router = APIRouter()
User = Depends(auth.current_user)
Admin = Depends(auth.admin_user)
ALLOWED_UPLOADS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf", ".gif"}


# ---------------------------------------------------------------- auth
@router.post("/api/login")
async def login(request: Request):
    body = await request.json()
    ip = auth.client_ip(request)
    auth.check_rate_limit(ip)
    with db.core.read() as con:
        user = db.one(con.execute("SELECT * FROM users WHERE username = ? AND active = 1",
                                  ((body.get("username") or "").strip(),)))
    if not user or not auth.verify_password(body.get("password") or "", user["password_hash"]):
        auth.record_failure(ip)
        raise HTTPException(401, "نام کاربری یا رمز عبور اشتباه است")
    token = auth.create_session(user["id"], request)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=config.COOKIE_SECURE)
    return resp


@router.post("/api/logout")
def logout(request: Request):
    token = request.cookies.get(auth.COOKIE)
    if token:
        auth.delete_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE)
    return resp


def _module_info(user: dict) -> list[dict]:
    return [{"id": m.id, "name": m.name, "short": m.short or m.name, "icon": m.icon, "description": m.description,
             "role": user["modules"][m.id], "roles": m.roles, "settings": m.may_configure(user, user["modules"][m.id]),
             "web": f"/m/{m.id}/index.js" if m.web_dir else None}
            for m in modules.values() if m.id in user["modules"]]


@router.get("/api/me")
def me(user=User):
    return {"user": user, "modules": _module_info(user), "unread": _unread(user), "app": {"name": config.APP_NAME},
            "today": db.today()}


@router.post("/api/me/password")
async def change_password(request: Request, user=User):
    body = await request.json()
    new = body.get("new") or ""
    auth.check_password_strength(new)
    with db.core.tx() as con:
        row = con.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not auth.verify_password(body.get("current") or "", row[0]):
            raise HTTPException(400, "رمز فعلی اشتباه است")
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(new), user["id"]))
        # sign out every other device
        token = request.cookies.get(auth.COOKIE) or ""
        con.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user["id"], auth._hash_token(token)))
    return {"ok": True}


# ---------------------------------------------------------------- unified home
@router.get("/api/home")
async def home(user=User):
    out = {}
    for mid, role in user["modules"].items():
        mod = modules[mid]
        if not mod.summary:
            continue
        try:
            out[mid] = await run_in_threadpool(mod.summary, {**user, "role": role})
        except Exception as exc:     # one broken module must not blank the home page
            log.exception("home summary failed for %s", mid)
            out[mid] = {"error": str(exc)}
    return out


# ---------------------------------------------------------------- activity, bell, live stream
def visible(event: dict, user: dict) -> bool:
    mid = event.get("module") or "core"
    if mid == "core":
        return user["is_admin"] or event.get("type") != "activity" or (event.get("item") or {}).get("user_id") == user["id"]
    role = user["modules"].get(mid)
    if role is None:
        return False
    mod = modules[mid]
    return mod.event_filter({**event}, {**user, "role": role}) if mod.event_filter else True


def _visible_rows(sql: str, args: list, user: dict, limit: int) -> list[dict]:
    """Fetch activity rows newest first, keeping only those this user may see."""
    out, before = [], None
    with db.core.read() as con:
        while len(out) < limit:
            q, a = sql, list(args)
            if before:
                q += " AND a.id < ?"
                a.append(before)
            batch = db.rows(con.execute(q + " ORDER BY a.id DESC LIMIT 200", a))
            if not batch:
                break
            for r in batch:
                if visible({"type": "activity", "module": r["module"], "item": r}, user):
                    out.append(r)
                    if len(out) >= limit:
                        break
            before = batch[-1]["id"]
            if len(batch) < 200:
                break
    return out


def _unread(user: dict) -> int:
    rows = _visible_rows("SELECT a.* FROM activity a WHERE a.notify = 1 AND a.id > ? AND IFNULL(a.user_id, 0) != ?",
                         [user["notif_seen"], user["id"]], user, 100)
    return len(rows)


@router.get("/api/activity")
def activity_list(before: int | None = None, limit: int = 40, only_notify: bool = False, module: str = "", user=User):
    sql = "SELECT a.*, u.name AS user_name FROM activity a LEFT JOIN users u ON u.id = a.user_id WHERE 1 = 1"
    args: list = []
    if before:
        sql += " AND a.id < ?"
        args.append(before)
    if only_notify:
        sql += " AND a.notify = 1"
    if module:
        sql += " AND a.module = ?"
        args.append(module)
    return _visible_rows(sql, args, user, min(limit, 200))


@router.post("/api/activity/seen")
async def activity_seen(request: Request, user=User):
    body = await request.json()
    with db.core.tx() as con:
        con.execute("UPDATE users SET notif_seen = MAX(notif_seen, ?) WHERE id = ?", (int(body.get("id") or 0), user["id"]))
    return {"ok": True}


@router.get("/api/stream")
async def stream(request: Request):
    user = auth.user_from_token(request.cookies.get(auth.COOKIE))
    if not user:
        raise HTTPException(401, "ابتدا وارد شوید")
    q = events.subscribe()

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if visible(event, user):
                    yield f"data: {events.encode(event)}\n\n"
        finally:
            events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- team & permissions
def _team_rows(con) -> list[dict]:
    users = db.rows(con.execute(
        "SELECT id, username, name, is_admin, active, created_at, last_login_at FROM users ORDER BY active DESC, id"))
    grants: dict[int, dict] = {}
    for r in con.execute("SELECT user_id, module, role FROM user_modules"):
        grants.setdefault(r["user_id"], {})[r["module"]] = r["role"]
    sessions = {r[0]: r[1] for r in con.execute(
        "SELECT user_id, MAX(last_seen_at) FROM sessions WHERE expires_at > ? GROUP BY user_id", (db.now(),))}
    for u in users:
        u["is_admin"] = bool(u["is_admin"])
        u["grants"] = grants.get(u["id"], {})
        u["access"] = auth.module_access(u["is_admin"], u["grants"])
        u["last_seen_at"] = sessions.get(u["id"])
    return users


@router.get("/api/team")
def team(user=Admin):
    with db.core.read() as con:
        users = _team_rows(con)
    return {"users": users, "modules": [{"id": m.id, "name": m.name, "icon": m.icon, "roles": m.roles}
                                        for m in modules.values()]}


def _clean_grants(raw) -> dict[str, str]:
    grants = {}
    for mid, role in (raw or {}).items():
        mod = modules.get(mid)
        if mod and role in mod.roles:
            grants[mid] = role
    return grants


def _save_grants(con, user_id: int, grants: dict[str, str]) -> None:
    # grants for modules that are switched off right now are kept untouched
    for mid in modules:
        con.execute("DELETE FROM user_modules WHERE user_id = ? AND module = ?", (user_id, mid))
    for mid, role in grants.items():
        con.execute("INSERT INTO user_modules (user_id, module, role) VALUES (?, ?, ?)", (user_id, mid, role))


def _ensure_an_admin_remains(con) -> None:
    if not con.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND active = 1").fetchone()[0]:
        raise HTTPException(400, "حداقل یک مدیر کل فعال باید بماند")


@router.post("/api/team")
async def team_create(request: Request, user=Admin):
    body = await request.json()
    username, name = (body.get("username") or "").strip(), (body.get("name") or "").strip()
    password = body.get("password") or ""
    if not username or not name:
        raise HTTPException(400, "نام و نام کاربری را وارد کنید")
    auth.check_password_strength(password)
    grants = _clean_grants(body.get("grants"))
    is_admin = bool(body.get("is_admin"))
    if not is_admin and not grants:
        raise HTTPException(400, "حداقل یک بخش را برای این کاربر فعال کنید")
    try:
        with db.core.tx() as con:
            cur = con.execute("INSERT INTO users (username, name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
                              (username, name, auth.hash_password(password), int(is_admin), db.now()))
            uid = cur.lastrowid
            _save_grants(con, uid, grants)
            activity.record(con, "core", "user", f"کاربر جدید: {name}", f"توسط {user['name']}", user_id=user["id"])
    except sqlite3.IntegrityError:
        raise HTTPException(400, "این نام کاربری قبلاً استفاده شده")
    saved = {"id": uid, "username": username, "name": name, "is_admin": is_admin, "active": True,
             "access": auth.module_access(is_admin, grants)}
    try:
        events.emit("user.saved", strict=True, user=saved, profile=body.get("profile") or {}, created=True)
    except Exception as exc:
        log.exception("module hook failed for new user %s", uid)
        raise HTTPException(500, f"کاربر ساخته شد ولی تنظیم یکی از بخش‌ها ناموفق بود: {exc}")
    return {"id": uid}


@router.put("/api/team/{user_id}")
async def team_update(user_id: int, request: Request, user=Admin):
    body = await request.json()
    with db.core.tx() as con:
        u = db.one(con.execute("SELECT * FROM users WHERE id = ?", (user_id,)))
        if not u:
            raise HTTPException(404, "کاربر پیدا نشد")
        is_admin = bool(body.get("is_admin", u["is_admin"]))
        active = bool(body.get("active", u["active"]))
        if user_id == user["id"] and (not active or not is_admin):
            raise HTTPException(400, "نمی‌توانید دسترسی مدیر یا حساب خودتان را غیرفعال کنید")
        con.execute("UPDATE users SET name = ?, is_admin = ?, active = ? WHERE id = ?",
                    ((body.get("name") or u["name"]).strip(), int(is_admin), int(active), user_id))
        if "grants" in body:
            _save_grants(con, user_id, _clean_grants(body["grants"]))
        if body.get("password"):
            auth.check_password_strength(body["password"])
            con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body["password"]), user_id))
            auth.delete_user_sessions(con, user_id)
        if not active:
            auth.delete_user_sessions(con, user_id)
        _ensure_an_admin_remains(con)
        grants = {r["module"]: r["role"] for r in con.execute("SELECT module, role FROM user_modules WHERE user_id = ?", (user_id,))}
        name = (body.get("name") or u["name"]).strip()
    saved = {"id": user_id, "username": u["username"], "name": name, "is_admin": is_admin, "active": active,
             "access": auth.module_access(is_admin, grants)}
    try:
        events.emit("user.saved", strict=True, user=saved, profile=body.get("profile") or {}, created=False)
    except Exception as exc:
        log.exception("module hook failed for user %s", user_id)
        raise HTTPException(500, f"ذخیره شد ولی تنظیم یکی از بخش‌ها ناموفق بود: {exc}")
    return {"ok": True}


@router.delete("/api/team/{user_id}/sessions")
def team_logout(user_id: int, user=Admin):
    with db.core.tx() as con:
        auth.delete_user_sessions(con, user_id)
    return {"ok": True}


# ---------------------------------------------------------------- notifications (Bale / Telegram)
@router.get("/api/notify")
def notify_get(user=Admin):
    s = activity.notify_settings()
    return {"bot": s.get("bot"), "chat_ids": s.get("chat_ids"), "token_set": bool(s.get("token")),
            "kinds": activity.notify_kinds()}


@router.put("/api/notify")
async def notify_save(request: Request, user=Admin):
    body = await request.json()
    with db.core.tx() as con:
        s = activity.notify_settings(con)
        for k in ("bot", "chat_ids"):
            if k in body:
                s[k] = (body[k] or "").strip() if isinstance(body[k], str) else body[k]
        if body.get("token"):
            s["token"] = body["token"].strip()
        if isinstance(body.get("kinds"), dict):
            s["kinds"] = {**(s.get("kinds") or {}), **{k: bool(v) for k, v in body["kinds"].items()}}
        db.core.set_setting("notify", s, con)
    return {"ok": True}


@router.post("/api/notify/test")
async def notify_test(user=Admin):
    ok, msg = await activity.send_bot(f"✅ پیام آزمایشی از {config.APP_NAME}\nارسال‌کننده: {user['name']}")
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True}


@router.get("/api/notify/chats")
async def notify_chats(user=Admin):
    s = activity.notify_settings()
    seen = bot.chats_for((s.get("token") or "").strip(), s.get("bot") or "bale")
    return [c for c in seen if c["type"] == "private"] if seen is not None else await activity.bot_updates(s)


# ---------------------------------------------------------------- setup status (home page checklist)
@router.get("/api/setup")
def setup_status(user=Admin):
    """Everything shared by the whole app in one look: what is set up, what is missing, last backup."""
    n = activity.notify_settings()
    t = _telegram_view()
    key = integrations.openrouter_key()
    w = integrations.woo_public()
    return {
        "woo": {"ok": w["configured"], "url": w["url"], "currency": w["currency"]},
        "proxy": {"ok": bool(integrations.proxy_url()), "url": integrations.proxy_url()},
        "bot": {"ok": bool(n.get("token") and n.get("chat_ids")), "bot": n.get("bot") or "bale",
                "chat_ids": n.get("chat_ids") or ""},
        "backup": {"ok": bool(t["enabled"] and t["chat_id"] and t["last_ok"] is not False), **t},
        "openrouter": {"ok": bool(key), "key_hint": f"…{key[-4:]}" if key else ""},
        "drive": {"ok": drive.connected(), "email": drive.settings().get("email") or "", "usage": drive.usage()},
    }


# ---------------------------------------------------------------- connections shared by every module
def _integrations_view() -> dict:
    key = integrations.openrouter_key()
    return {"woo": integrations.woo_public(), "proxy_url": integrations.proxy_url(),
            "openrouter": {"key_set": bool(key), "key_hint": f"…{key[-4:]}" if key else ""}}


@router.get("/api/integrations")
def integrations_get(user=Admin):
    return _integrations_view()


@router.put("/api/integrations")
async def integrations_save(request: Request, user=Admin):
    body = await request.json()
    try:
        if isinstance(body.get("woo"), dict):
            integrations.save_woo(body["woo"])
        if "proxy_url" in body:
            integrations.save_proxy(body["proxy_url"] or "")
        if body.get("openrouter_key"):
            integrations.save_openrouter_key(body["openrouter_key"])
        if body.get("clear_openrouter_key"):
            integrations.save_openrouter_key("")
    except integrations.IntegrationError as exc:
        raise HTTPException(400, str(exc))
    events.emit("integrations.saved", keys=sorted(k for k in body if k != "openrouter_key"))
    activity.record(None, "core", "integrations", "تنظیمات اتصال‌ها تغییر کرد", f"توسط {user['name']}", user_id=user["id"])
    return _integrations_view()


@router.post("/api/integrations/woo/test")
async def integrations_woo_test(user=Admin):
    try:
        return await integrations.test_woo()
    except integrations.IntegrationError as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/integrations/proxy/test")
async def integrations_proxy_test(user=Admin):
    return await integrations.test_proxy()


# ---------------------------------------------------------------- receipts in Google Drive
def _drive_redirect(request: Request) -> str:
    return f"{config.PUBLIC_URL or str(request.base_url).rstrip('/')}/api/drive/callback"


def _drive_call(fn):
    try:
        return fn()
    except drive.DriveError as exc:
        raise HTTPException(400, str(exc))


@router.get("/api/drive")
def drive_get(request: Request, user=Admin):
    return drive.public_view(_drive_redirect(request))


@router.put("/api/drive")
async def drive_save(request: Request, user=Admin):
    body = await request.json()
    changes = {}
    if "client_id" in body:
        changes["client_id"] = (body["client_id"] or "").strip()
    if (body.get("client_secret") or "").strip():
        changes["client_secret"] = body["client_secret"].strip()
    if "cap_mb" in body:
        changes["cap_mb"] = max(100, min(200_000, int(body["cap_mb"] or drive.DEFAULT_CAP_MB)))
        changes["cap_warned"] = False
    drive.save(changes)
    if "cap_mb" in body:
        drive.retry()
    return drive.public_view(_drive_redirect(request))


@router.get("/api/drive/connect", include_in_schema=False)
def drive_connect(request: Request, user=Admin):
    """Opened in the browser: goes to Google's consent page, which comes back to /api/drive/callback."""
    return RedirectResponse(_drive_call(lambda: drive.auth_url(_drive_redirect(request))))


@router.get("/api/drive/callback", include_in_schema=False)
async def drive_callback(request: Request, user=Admin):
    q = request.query_params
    if q.get("error"):
        drive.save({"last_error": f"اجازه داده نشد ({q.get('error')})"})
        return RedirectResponse("/#/settings/drive")
    try:
        r = await drive.finish_connect(q.get("code") or "", q.get("state") or "", _drive_redirect(request))
    except drive.DriveError as exc:
        drive.save({"last_error": str(exc)})
        return RedirectResponse("/#/settings/drive")
    activity.record(None, "core", "drive", "گوگل درایو برای رسیدها وصل شد", f"{r['email']} — توسط {user['name']}",
                    user_id=user["id"], level="success")
    return RedirectResponse("/#/settings/drive")


@router.post("/api/drive/test")
async def drive_test(user=Admin):
    try:
        await drive.ensure_folder([])
        return {"quota": await drive.quota()}
    except drive.DriveError as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/drive/backfill")
def drive_backfill(user=Admin):
    """Send receipts recorded before Drive was connected (and invoices of recent website orders)."""
    if not drive.connected():
        raise HTTPException(400, "اول گوگل درایو را وصل کنید")
    return {"queued": drive.backfill()}


@router.post("/api/drive/retry")
def drive_retry(user=Admin):
    return {"queued": drive.retry()}


@router.post("/api/drive/disconnect")
def drive_disconnect(user=Admin):
    drive.disconnect()
    activity.record(None, "core", "drive", "اتصال گوگل درایو قطع شد", f"توسط {user['name']}", user_id=user["id"], level="warning")
    return {"ok": True}


# ---------------------------------------------------------------- off-site backups in a Telegram channel
def _telegram_view() -> dict:
    s = backup.telegram_settings()
    return {"enabled": bool(s["enabled"]), "chat_id": s["chat_id"], "hours": int(s["hours"] or 1),
            "token_set": bool((s.get("token") or "").strip()), "uses_notify_token": not (s.get("token") or "").strip()
            and bool(backup.telegram_token(s)), "last_at": s["last_at"], "last_ok": s["last_ok"],
            "last_error": s["last_error"], "last_size": s["last_size"], "proxy": bool(integrations.proxy_url())}


@router.get("/api/backup/telegram")
def backup_telegram_get(user=Admin):
    return _telegram_view()


@router.put("/api/backup/telegram")
async def backup_telegram_save(request: Request, user=Admin):
    body = await request.json()
    changes = {}
    if "enabled" in body:
        changes["enabled"] = bool(body["enabled"])
    if "chat_id" in body:
        changes["chat_id"] = str(body["chat_id"] or "").strip()
    if "hours" in body:
        try:
            changes["hours"] = min(24, max(1, int(body["hours"] or 1)))
        except (TypeError, ValueError):
            raise HTTPException(400, "فاصله پشتیبان‌گیری باید عدد (ساعت) باشد")
    if body.get("token"):
        changes["token"] = str(body["token"]).strip()
    if body.get("clear_token"):
        changes["token"] = ""
    backup._save_telegram(changes)
    return _telegram_view()


@router.get("/api/backup/telegram/chats")
async def backup_telegram_chats(user=Admin):
    """Channels/groups the backup bot has seen, so the owner can pick the channel id of a private channel."""
    token = backup.telegram_token()
    if not token:
        raise HTTPException(400, "اول توکن ربات تلگرام را ذخیره کنید")
    seen = bot.chats_for(token, "telegram")
    if seen is not None:
        return [c for c in seen if c["type"] in ("channel", "supergroup", "group")]
    try:
        return await activity.bot_updates({"bot": "telegram", "token": token})
    except Exception as exc:
        raise HTTPException(400, f"ارتباط با تلگرام برقرار نشد ({exc.__class__.__name__}) — پروکسی را بررسی کنید")


@router.post("/api/backup/telegram/send")
async def backup_telegram_send(user=Admin):
    result = await backup.send_to_telegram(manual=True)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    activity.record(None, "core", "backup", "پشتیبان به کانال تلگرام فرستاده شد", f"توسط {user['name']}",
                    user_id=user["id"])
    return result


# ---------------------------------------------------------------- system
@router.get("/api/system")
def system(user=Admin):
    dbs = []
    for database in db.registry.values():
        size = database.path.stat().st_size if database.path.exists() else 0
        wal = database.path.with_name(database.path.name + "-wal")
        dbs.append({"name": database.name, "size": size + (wal.stat().st_size if wal.exists() else 0),
                    "version": database.version() if database.path.exists() else 0})
    next_backup = jobs.next_runs("core.backup")
    return {"version": config.VERSION or "dev", "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "modules": [{"id": m.id, "name": m.name} for m in modules.values()], "databases": dbs,
            "backups": backup.list_snapshots()[:15], "backup_keep_days": config.BACKUP_KEEP_DAYS,
            "next_backup": next_backup[0].isoformat() if next_backup else None, "public_url": config.PUBLIC_URL,
            "telegram": _telegram_view()}


@router.post("/api/system/backup")
async def system_backup_now(user=Admin):
    dest = await run_in_threadpool(backup.snapshot)
    await run_in_threadpool(backup.prune)
    activity.record(None, "core", "backup", "پشتیبان‌گیری دستی انجام شد", dest.name, user_id=user["id"])
    return {"ok": True, "name": dest.name}


@router.get("/api/system/backup.zip")
async def system_backup_zip(user=Admin):
    path = await run_in_threadpool(backup.databases_zip)
    # the zip and the database copies next to it live in a temp folder: remove it once the download is sent
    return FileResponse(path, filename=path.name, media_type="application/zip",
                        background=BackgroundTask(shutil.rmtree, path.parent, ignore_errors=True))


# ---------------------------------------------------------------- uploads (receipts, invoices, ...)
@router.post("/api/uploads")
async def upload(file: UploadFile = File(...), user=User):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise HTTPException(400, "فقط عکس یا PDF")
    today = date.fromisoformat(db.today())
    rel = Path(f"{today.year}/{today.month:02d}/{uuid.uuid4().hex}{ext}")
    dest = config.UPLOAD_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"حداکثر حجم فایل {config.MAX_UPLOAD_MB} مگابایت است")
            out.write(chunk)
    if ext == ".pdf" and size > PDF_MAX_MB * 1024 * 1024:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"فایل PDF حداکثر {PDF_MAX_MB} مگابایت؛ از رسید عکس بگیرید یا PDF کوچک‌تری بفرستید")
    dest = await run_in_threadpool(_shrink_photo, dest)
    return {"path": dest.relative_to(config.UPLOAD_DIR).as_posix()}


PDF_MAX_MB = 5
PHOTO_EDGE, PHOTO_QUALITY, PHOTO_KEEP_BELOW = 1600, 80, 350 * 1024


def _shrink_photo(path: Path) -> Path:
    """A receipt photo needs to be readable, not 12 megapixels: longest side 1600px, JPEG quality 80 (usually
    150–400 KB). Keeps every receipt small on the server and in Google Drive. Unreadable formats stay as they are."""
    if path.suffix.lower() == ".pdf" or path.stat().st_size <= PHOTO_KEEP_BELOW and path.suffix.lower() in (".jpg", ".jpeg"):
        return path
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.thumbnail((PHOTO_EDGE, PHOTO_EDGE))
            out = path.with_suffix(".jpg")
            tmp = out.with_name(out.stem + ".tmp.jpg")
            im.save(tmp, "JPEG", quality=PHOTO_QUALITY, optimize=True, progressive=True)
    except Exception:
        return path
    if tmp.stat().st_size >= path.stat().st_size and path.suffix.lower() in (".jpg", ".jpeg"):
        tmp.unlink()
        return path
    tmp.replace(out)
    if out != path:
        path.unlink(missing_ok=True)
    return out


@router.get("/uploads/{path:path}", include_in_schema=False)
def uploaded(path: str, request: Request):
    if not auth.user_from_token(request.cookies.get(auth.COOKIE)):
        raise HTTPException(401)
    target = (config.UPLOAD_DIR / path).resolve()
    if not target.is_file() or config.UPLOAD_DIR.resolve() not in target.parents:
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/healthz", include_in_schema=False)
def healthz():
    status = {}
    for name, database in db.registry.items():
        try:
            database.check()
            status[name] = "ok"
        except Exception as exc:
            status[name] = f"error: {exc}"
    ok = all(v == "ok" for v in status.values())
    return JSONResponse({"ok": ok, "version": config.VERSION or "dev", "databases": status}, status_code=200 if ok else 503)
