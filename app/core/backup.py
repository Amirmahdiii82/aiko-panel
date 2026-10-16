"""Backups of every module database plus uploaded files.

* Daily, inside the app (BACKUP_TIME, default 03:15): `data/backups/YYYY-MM-DD/` with one consistent
  copy per database (SQLite online backup API — safe while the app writes) and a tar of uploads.
  Snapshots older than BACKUP_KEEP_DAYS are removed.
* On demand: owners can download a zip of all databases from the System page.
* deploy.sh takes a snapshot before every release so a failed deploy can be rolled back with its data.
* Off the server, every hour by default: a zip of every database is sent to a Telegram channel
  (Settings → Backups). Telegram is filtered in Iran, so this goes through the outbound proxy.
"""
import logging
import shutil
import tarfile
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, db, integrations, jalali

log = logging.getLogger("aiko.backup")


def snapshot(dest: Path | None = None, *, files: bool = True) -> Path:
    dest = dest or (config.BACKUP_DIR / db.today())
    dest.mkdir(parents=True, exist_ok=True)
    for database in db.registry.values():
        if database.path.exists():
            database.backup_to(dest / f"{database.name}.db")
    if files:
        for folder in _file_dirs():
            if folder.exists() and any(folder.iterdir()):
                with tarfile.open(dest / f"{folder.name}.tgz", "w:gz") as tar:
                    tar.add(folder, arcname=folder.name)
    log.info("backup written to %s", dest)
    return dest


def _file_dirs() -> list[Path]:
    dirs = [config.UPLOAD_DIR]
    media = config.DATA_DIR / "media"
    if media.exists():
        dirs.append(media)
    return dirs


def prune(keep_days: int | None = None) -> int:
    keep_days = config.BACKUP_KEEP_DAYS if keep_days is None else keep_days
    if not config.BACKUP_DIR.exists():
        return 0
    cutoff = (date.fromisoformat(db.today()) - timedelta(days=keep_days)).isoformat()
    removed = 0
    for child in config.BACKUP_DIR.iterdir():
        if child.is_dir() and len(child.name) == 10 and child.name < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    # snapshots taken before each full site sync (one a night): keep the last week
    for child in sorted(p for p in config.BACKUP_DIR.iterdir() if p.is_dir() and p.name.startswith("presync-"))[:-7]:
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return removed


def daily_job() -> None:
    try:
        snapshot()
        prune()
    except Exception:
        log.exception("daily backup failed")


def databases_zip(name: str | None = None) -> Path:
    """A zip of every database (no media files — they can be large), for download."""
    tmp = Path(tempfile.mkdtemp())
    for database in db.registry.values():
        if database.path.exists():
            database.backup_to(tmp / f"{database.name}.db")
    out = tmp / (name or f"aiko-backup-{db.today()}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in tmp.glob("*.db"):
            z.write(f, f.name)
    return out


def list_snapshots() -> list[dict]:
    if not config.BACKUP_DIR.exists():
        return []
    out = []
    for child in sorted(config.BACKUP_DIR.iterdir(), reverse=True):
        if child.is_dir():
            size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
            out.append({"name": child.name, "size": size, "files": sorted(f.name for f in child.iterdir())})
    return out


# ---------------------------------------------------------------- off-site copy in a Telegram channel
TELEGRAM_API = "https://api.telegram.org/bot{token}/"
TELEGRAM_PART = 45 * 1024 * 1024          # bots may upload up to 50 MB per file
DEFAULT_TELEGRAM = {"enabled": False, "token": "", "chat_id": "", "hours": 1, "last_at": "", "last_ok": None,
                    "last_error": "", "last_size": 0}


def telegram_settings(con=None) -> dict:
    return {**DEFAULT_TELEGRAM, **(db.core.get_setting("backup_telegram", {}, con) or {})}


def telegram_token(s: dict | None = None) -> str:
    """Its own bot token, or the notification bot's when that one is a Telegram bot."""
    s = s or telegram_settings()
    if (s.get("token") or "").strip():
        return s["token"].strip()
    notify = db.core.get_setting("notify", {}) or {}
    return (notify.get("token") or "").strip() if notify.get("bot") == "telegram" else ""


def _save_telegram(changes: dict) -> None:
    with db.core.tx() as con:
        s = telegram_settings(con)
        s.update(changes)
        db.core.set_setting("backup_telegram", s, con)


def _stamp() -> tuple[str, str]:
    now = datetime.now(db.TZ)
    jy, jm, jd = jalali.iso_to_jalali(now.date().isoformat())
    return f"{jy}{jm:02d}{jd:02d}-{now:%H%M}", f"{jy}/{jm:02d}/{jd:02d} ساعت {now:%H:%M}"


def _parts(path: Path) -> list[Path]:
    """Split a file into Telegram-sized pieces (rejoin with `cat file.zip.0* > file.zip`)."""
    if path.stat().st_size <= TELEGRAM_PART:
        return [path]
    parts = []
    with path.open("rb") as f:
        i = 1
        while chunk := f.read(TELEGRAM_PART):
            part = path.with_name(f"{path.name}.{i:03d}")
            part.write_bytes(chunk)
            parts.append(part)
            i += 1
    return parts


async def send_to_telegram(*, manual: bool = False) -> dict:
    """Zip every database and post it to the configured Telegram channel. Never raises: the outcome is saved
    and returned so the settings page can show it."""
    import asyncio

    import httpx

    s = telegram_settings()
    token, chat_id = telegram_token(s), str(s.get("chat_id") or "").strip()
    if not token or not chat_id:
        return {"ok": False, "error": "توکن ربات تلگرام یا شناسه کانال تنظیم نشده"}
    stamp, label = _stamp()
    zip_path = await asyncio.to_thread(databases_zip, f"aiko-db-{stamp}.zip")
    size = zip_path.stat().st_size
    error = ""
    try:
        parts = await asyncio.to_thread(_parts, zip_path)
        names = "، ".join(sorted(d.name for d in db.registry.values() if d.path.exists()))
        async with integrations.abroad_client(timeout=httpx.Timeout(300, connect=20)) as client:
            for i, part in enumerate(parts, 1):
                caption = (f"🗄 پشتیبان پنل آیکو — {label}\n{names}\nحجم: {size / 1048576:.2f} MB"
                           + (f"\nبخش {i} از {len(parts)} (برای بازکردن: cat {zip_path.name}.0* > {zip_path.name})"
                              if len(parts) > 1 else "")
                           + ("\n(دستی)" if manual else ""))
                with part.open("rb") as fh:
                    r = await client.post(TELEGRAM_API.format(token=token) + "sendDocument",
                                          data={"chat_id": chat_id, "caption": caption, "disable_notification": "true"},
                                          files={"document": (part.name, fh, "application/zip")})
                try:
                    body = r.json()
                except ValueError:
                    body = {}
                if r.status_code != 200 or not body.get("ok"):
                    error = body.get("description") or f"HTTP {r.status_code}"
                    break
    except httpx.HTTPError as exc:
        error = f"ارتباط با تلگرام برقرار نشد ({exc.__class__.__name__})" + ("" if integrations.proxy_url()
                                                                           else " — پروکسی تنظیم نشده")
    finally:
        shutil.rmtree(zip_path.parent, ignore_errors=True)
    ok = not error
    _save_telegram({"last_at": db.now(), "last_ok": ok, "last_error": error, "last_size": size})
    if ok:
        log.info("backup sent to telegram (%s bytes)", size)
    else:
        log.warning("telegram backup failed: %s", error)
    return {"ok": ok, "error": error, "size": size}


def telegram_due(s: dict | None = None) -> bool:
    s = s or telegram_settings()
    if not s.get("enabled"):
        return False
    last = s.get("last_at") or ""
    if not last:
        return True
    hours = max(1, int(s.get("hours") or 1))
    try:
        elapsed = datetime.now(db.TZ) - datetime.fromisoformat(last)
    except ValueError:
        return True
    # a failed attempt is retried after 10 minutes instead of waiting a whole interval
    wait = timedelta(hours=hours) if s.get("last_ok") else timedelta(minutes=10)
    return elapsed >= wait - timedelta(minutes=2)


async def telegram_tick() -> None:
    """Runs every few minutes; sends a backup when one is due (survives restarts and deploys)."""
    try:
        if telegram_due():
            await send_to_telegram()
    except Exception:
        log.exception("telegram backup tick failed")
