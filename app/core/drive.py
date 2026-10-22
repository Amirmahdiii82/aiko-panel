"""Receipts and invoices in the owners' Google Drive, in one tidy folder:

    پنل آیکو — رسیدها/
        ۱۴۰۵/
            ۰۷ مهر/
                خرید کالا/   ۳۰ — P-12 — بازار تهران — ۸۳۰٬۰۰۰ تومان.jpg
                فروش/        ۳۰ — S-41 — مریم الف — ۹۳۵٬۰۰۰ تومان.jpg
                فروش سایت/   ۳۰ — WEB-1234 — مریم الف — ۵۹۰٬۰۰۰ تومان.pdf
                هزینه‌ها/     ۲۹ — تبلیغات — ۲٬۰۰۰٬۰۰۰ تومان.jpg

* Connected once by an owner with their own Google account (OAuth). The panel asks only for `drive.file`: it can see
  and change only the files and folders it created itself, nothing else in the Drive. (A service account cannot
  store files in a personal Drive — it has no storage of its own — so the owner's account is the right way.)
* Google is filtered from Iran: every call goes through the outbound proxy (integrations.abroad_client).
* Modules hand files over with enqueue(); a background worker uploads them, retries failures, and when a record's
  receipt is replaced, the old file is moved to the Drive trash. Files always stay on the server too.
* Size stays under control: photos are shrunk when they are uploaded to the panel (router), invoices are tiny PDFs,
  and the panel never puts more than the cap (2 GB by default) in Drive: past it, files wait ("held") and the owners
  are told once, instead of filling the Drive.
"""
import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from . import activity, config, db, events, integrations, jalali
from .text import fa, toman

log = logging.getLogger("aiko.drive")

KEY = "gdrive"
ROOT_NAME = "پنل آیکو — رسیدها"
SCOPES = "https://www.googleapis.com/auth/drive.file openid email"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
DEFAULT_CAP_MB = 2048
MAX_ATTEMPTS = 6

_token: dict = {"value": "", "expires": 0.0}
_wake: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None


class DriveError(Exception):
    """A user-facing problem with Google Drive (message shown as-is)."""


# ---------------------------------------------------------------- settings
def settings(con=None) -> dict:
    return {"cap_mb": DEFAULT_CAP_MB, **(db.core.get_setting(KEY, {}, con) or {})}


def save(changes: dict) -> dict:
    with db.core.tx() as con:
        s = settings(con)
        s.update(changes)
        db.core.set_setting(KEY, s, con)
    return s


def connected(s: dict | None = None) -> bool:
    s = s or settings()
    return bool(s.get("client_id") and s.get("client_secret") and s.get("refresh_token"))


def usage(con=None) -> dict:
    def q(c):
        r = c.execute("""SELECT IFNULL(SUM(CASE WHEN status = 'done' THEN size END), 0),
                                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END),
                                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END),
                                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END),
                                SUM(CASE WHEN status = 'held' THEN 1 ELSE 0 END) FROM drive_files""").fetchone()
        return {"bytes": int(r[0] or 0), "files": r[1] or 0, "pending": r[2] or 0, "errors": r[3] or 0, "held": r[4] or 0}
    if con is not None:
        return q(con)
    with db.core.read() as c:
        return q(c)


def public_view(redirect_uri: str) -> dict:
    s = settings()
    return {"connected": connected(s), "client_id": s.get("client_id") or "", "secret_set": bool(s.get("client_secret")),
            "email": s.get("email") or "", "root_link": _link(s.get("root_id"), folder=True) if s.get("root_id") else "",
            "cap_mb": int(s.get("cap_mb") or DEFAULT_CAP_MB), "redirect_uri": redirect_uri, "proxy": bool(integrations.proxy_url()),
            "last_error": s.get("last_error") or "", "last_ok_at": s.get("last_ok_at") or "", "usage": usage(),
            "quota": s.get("quota") or {}}


def _link(drive_id: str | None, folder: bool = False) -> str:
    if not drive_id:
        return ""
    return f"https://drive.google.com/drive/folders/{drive_id}" if folder else f"https://drive.google.com/file/d/{drive_id}/view"


# ---------------------------------------------------------------- connecting (OAuth, once)
def auth_url(redirect_uri: str) -> str:
    s = settings()
    if not (s.get("client_id") and s.get("client_secret")):
        raise DriveError("اول Client ID و Client secret را ذخیره کنید")
    state = secrets.token_urlsafe(24)
    save({"oauth_state": state, "oauth_state_at": time.time()})
    return f"{AUTH_URL}?" + urlencode({"client_id": s["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
                                       "scope": SCOPES, "access_type": "offline", "prompt": "consent",
                                       "include_granted_scopes": "true", "state": state})


async def finish_connect(code: str, state: str, redirect_uri: str) -> dict:
    s = settings()
    if not state or state != s.get("oauth_state") or time.time() - float(s.get("oauth_state_at") or 0) > 900:
        raise DriveError("درخواست اتصال منقضی شده؛ دوباره «اتصال به گوگل درایو» را بزنید")
    async with integrations.abroad_client() as http:
        try:
            r = await http.post(TOKEN_URL, data={"code": code, "client_id": s["client_id"], "client_secret": s["client_secret"],
                                                 "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        except Exception as exc:
            raise DriveError(f"گوگل در دسترس نبود ({exc.__class__.__name__}). پروکسی خروجی را بررسی کنید.")
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or not data.get("refresh_token"):
            raise DriveError(f"گوگل اجازه نداد: {data.get('error_description') or data.get('error') or r.status_code}")
        email = ""
        try:
            info = await http.get("https://openidconnect.googleapis.com/v1/userinfo",
                                  headers={"Authorization": f"Bearer {data['access_token']}"})
            email = info.json().get("email") or ""
        except Exception:
            pass
    _token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in") or 3600) - 60)
    save({"refresh_token": data["refresh_token"], "email": email, "oauth_state": "", "connected_at": db.now(),
          "root_id": "", "last_error": ""})
    with db.core.tx() as con:
        con.execute("DELETE FROM drive_folders")             # a different account: folders are created again
        con.execute("UPDATE drive_files SET status = 'pending', attempts = 0 WHERE status IN ('error', 'held')")
    await ensure_folder([])
    wake()
    return {"email": email}


def disconnect() -> None:
    save({"refresh_token": "", "email": "", "root_id": ""})
    _token.update(value="", expires=0)


# ---------------------------------------------------------------- Drive API
async def _access_token(http) -> str:
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    s = settings()
    if not connected(s):
        raise DriveError("گوگل درایو وصل نیست")
    r = await http.post(TOKEN_URL, data={"client_id": s["client_id"], "client_secret": s["client_secret"],
                                         "refresh_token": s["refresh_token"], "grant_type": "refresh_token"})
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200:
        if data.get("error") == "invalid_grant":
            save({"refresh_token": ""})
            raise DriveError("اجازه گوگل درایو باطل شده؛ دوباره وصل کنید (اگر برنامه گوگل در حالت Testing است، آن را "
                             "روی In production بگذارید تا اجازه بعد از ۷ روز باطل نشود)")
        raise DriveError(f"گوگل اجازه نداد: {data.get('error_description') or r.status_code}")
    _token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in") or 3600) - 60)
    return _token["value"]


async def _call(method: str, url: str, **kw) -> dict:
    async with integrations.abroad_client(timeout=60) as http:
        token = await _access_token(http)
        try:
            r = await http.request(method, url, headers={"Authorization": f"Bearer {token}", **kw.pop("headers", {})}, **kw)
        except Exception as exc:
            raise DriveError(f"گوگل درایو در دسترس نبود ({exc.__class__.__name__}). پروکسی خروجی را بررسی کنید.")
    if r.status_code == 404:
        raise FileNotFoundError(url)
    data = r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        err = (data.get("error") or {}) if isinstance(data.get("error"), dict) else {}
        reason = ((err.get("errors") or [{}])[0]).get("reason", "")
        if reason == "storageQuotaExceeded":
            raise DriveError("فضای گوگل درایو پر است")
        raise DriveError(f"خطای گوگل درایو: {err.get('message') or r.status_code}")
    return data


async def _create_folder(name: str, parent: str | None) -> str:
    body = {"name": name, "mimeType": FOLDER, **({"parents": [parent]} if parent else {})}
    return (await _call("POST", f"{API}/files", params={"fields": "id"}, json=body))["id"]


async def _alive(drive_id: str) -> bool:
    try:
        f = await _call("GET", f"{API}/files/{drive_id}", params={"fields": "id,trashed"})
        return not f.get("trashed")
    except FileNotFoundError:
        return False


async def ensure_folder(parts: list[str]) -> str:
    """The id of the folder at this path under the root (created as needed; recreated if someone deleted it)."""
    s = settings()
    root = s.get("root_id")
    if not root or not await _alive(root):
        root = await _create_folder(ROOT_NAME, None)
        save({"root_id": root})
        with db.core.tx() as con:
            con.execute("DELETE FROM drive_folders")
    parent, path = root, ""
    for name in parts:
        path = f"{path}/{name}" if path else name
        with db.core.read() as con:
            row = con.execute("SELECT drive_id FROM drive_folders WHERE path = ?", (path,)).fetchone()
        if row:
            parent = row[0]
            continue
        parent = await _create_folder(name, parent)
        with db.core.tx() as con:
            con.execute("INSERT OR REPLACE INTO drive_folders (path, drive_id) VALUES (?, ?)", (path, parent))
    return parent


async def _upload(path: Path, name: str, folder_id: str) -> str:
    meta = {"name": name, "parents": [folder_id]}
    mime = "application/pdf" if path.suffix.lower() == ".pdf" else f"image/{'jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else path.suffix.lower().lstrip('.')}"
    boundary = secrets.token_hex(12)
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta, ensure_ascii=False)}\r\n"
            f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--".encode()
    data = await _call("POST", UPLOAD, params={"uploadType": "multipart", "fields": "id"}, content=body,
                       headers={"Content-Type": f"multipart/related; boundary={boundary}"})
    return data["id"]


async def quota() -> dict:
    data = await _call("GET", f"{API}/about", params={"fields": "storageQuota,user(emailAddress)"})
    q = {k: int(v) for k, v in (data.get("storageQuota") or {}).items() if str(v).isdigit()}
    save({"quota": q, "last_ok_at": db.now(), "last_error": ""})
    return q


# ---------------------------------------------------------------- the queue
def enqueue(ref: str, local_path: str, folder: list[str], name: str) -> None:
    """Copy this file (under data/uploads) to Drive in the background. A record has one current file: when its
    receipt changes, the previous one is moved to the Drive trash."""
    full = config.UPLOAD_DIR / local_path
    if not full.is_file():
        return
    name = _clean_name(name, full.suffix.lower())
    with db.core.tx() as con:
        con.execute("""UPDATE drive_files SET status = CASE WHEN status = 'done' THEN 'replaced' ELSE 'removed' END
                       WHERE ref = ? AND local_path != ? AND status NOT IN ('replaced', 'removed')""", (ref, local_path))
        con.execute("""INSERT INTO drive_files (ref, local_path, folder, name, size, created_at) VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(ref, local_path) DO UPDATE SET folder = excluded.folder, name = excluded.name,
                       status = CASE WHEN status IN ('done') THEN status ELSE 'pending' END""",
                    (ref, local_path, "/".join(folder), name, full.stat().st_size, db.now()))
    wake()


def forget(ref: str) -> None:
    """The record no longer has a file (or no longer exists): its file in Drive goes to the trash."""
    with db.core.tx() as con:
        con.execute("""UPDATE drive_files SET status = CASE WHEN status = 'done' THEN 'replaced' ELSE 'removed' END
                       WHERE ref = ? AND status NOT IN ('replaced', 'removed')""", (ref,))
    wake()


def link(ref: str) -> str:
    with db.core.read() as con:
        row = con.execute("SELECT drive_id FROM drive_files WHERE ref = ? AND status = 'done' ORDER BY id DESC LIMIT 1",
                          (ref,)).fetchone()
    return _link(row[0]) if row else ""


def retry() -> int:
    with db.core.tx() as con:
        n = con.execute("UPDATE drive_files SET status = 'pending', attempts = 0, error = NULL WHERE status IN ('error', 'held')").rowcount
    save({"cap_warned": False})
    wake()
    return n


def _clean_name(name: str, ext: str) -> str:
    name = "".join(ch for ch in name if ch not in '/\\:*?"<>|\n\r\t').strip(" .—-")[:150] or "رسید"
    return name if name.lower().endswith(ext) else f"{name}{ext}"


def month_folder(iso_date: str, kind: str) -> list[str]:
    """["۱۴۰۵", "۰۷ مهر", kind] for a date."""
    jy, jm, _ = jalali.iso_to_jalali(iso_date[:10])
    return [fa(jy), f"{fa(f'{jm:02d}')} {jalali.MONTHS[jm - 1]}", kind]


def file_name(iso_date: str, *parts) -> str:
    """"۳۰ — P-12 — بازار تهران — ۸۳۰٬۰۰۰ تومان": the day first, so a month folder sorts by date."""
    _, _, jd = jalali.iso_to_jalali(iso_date[:10])
    shown = [toman(p) if isinstance(p, int) else str(p) for p in parts if p not in (None, "")]
    return " — ".join([fa(f"{jd:02d}"), *shown])


# ---------------------------------------------------------------- background worker
def wake() -> None:
    if _loop and _wake:
        _loop.call_soon_threadsafe(_wake.set)


async def _step() -> bool:
    """Handle one queued file. Returns False when there is nothing (more) to do now."""
    s = settings()
    with db.core.read() as con:
        row = db.one(con.execute("""SELECT * FROM drive_files WHERE status IN ('replaced', 'pending')
                                    AND attempts < ? ORDER BY CASE status WHEN 'replaced' THEN 0 ELSE 1 END, id LIMIT 1""",
                                 (MAX_ATTEMPTS,)))
        used = usage(con)["bytes"]
    if not row:
        return False
    if row["status"] == "replaced":
        try:
            await _call("PATCH", f"{API}/files/{row['drive_id']}", json={"trashed": True})
        except FileNotFoundError:
            pass
        with db.core.tx() as con:
            con.execute("UPDATE drive_files SET status = 'removed' WHERE id = ?", (row["id"],))
        return True
    path = config.UPLOAD_DIR / row["local_path"]
    if not path.is_file():
        with db.core.tx() as con:
            con.execute("UPDATE drive_files SET status = 'removed', error = 'فایل روی سرور نیست' WHERE id = ?", (row["id"],))
        return True
    cap = int(s["cap_mb"] if s.get("cap_mb") is not None else DEFAULT_CAP_MB) * 1024 * 1024
    if used + row["size"] > cap:
        with db.core.tx() as con:
            con.execute("UPDATE drive_files SET status = 'held' WHERE status = 'pending'")
        if not s.get("cap_warned"):
            save({"cap_warned": True})
            activity.record(None, "core", "drive", "⚠️ سقف فضای رسیدها در گوگل درایو پر شد",
                            f"{fa(round(used / 1024 / 1024))} مگابایت از {fa(round(cap / 1024 / 1024))} مگابایت. رسیدهای تازه "
                            "روی سرور می‌مانند و به درایو نمی‌روند تا سقف را در «تنظیمات ← گوگل درایو» بیشتر کنید.",
                            level="warning", link="#/settings", notify=True)
        return False
    try:
        folder_id = await ensure_folder([p for p in row["folder"].split("/") if p])
        try:
            drive_id = await _upload(path, row["name"], folder_id)
        except FileNotFoundError:               # the folder was deleted in Drive meanwhile
            with db.core.tx() as con:
                con.execute("DELETE FROM drive_folders")
            raise DriveError("پوشه در درایو پیدا نشد؛ دوباره ساخته می‌شود")
    except DriveError as exc:
        with db.core.tx() as con:
            con.execute("UPDATE drive_files SET attempts = attempts + 1, error = ?, status = CASE WHEN attempts + 1 >= ? "
                        "THEN 'error' ELSE status END WHERE id = ?", (str(exc), MAX_ATTEMPTS, row["id"]))
        save({"last_error": str(exc)})
        raise
    with db.core.tx() as con:
        con.execute("UPDATE drive_files SET status = 'done', drive_id = ?, error = NULL, done_at = ? WHERE id = ?",
                    (drive_id, db.now(), row["id"]))
    save({"last_ok_at": db.now(), "last_error": ""})
    return True


async def worker() -> None:
    global _loop, _wake
    _loop = asyncio.get_running_loop()
    _wake = asyncio.Event()
    while True:
        try:
            await asyncio.wait_for(_wake.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
        _wake.clear()
        if not connected():
            continue
        try:
            for _ in range(200):                # a burst at most; the rest on the next round
                if not await _step():
                    break
        except DriveError as exc:
            log.warning("drive upload paused: %s", exc)
            await asyncio.sleep(120)            # Google or the proxy is unreachable: try again in a while
        except Exception:
            log.exception("drive worker error")
            await asyncio.sleep(60)


def backfill() -> int:
    """Send everything modules already have (receipts recorded before Drive was connected)."""
    before = usage()["pending"]
    events.emit("drive.backfill")
    wake()
    return usage()["pending"] - before
