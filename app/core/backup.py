"""Backups of every module database plus uploaded files.

* Daily, inside the app (BACKUP_TIME, default 03:15): `data/backups/YYYY-MM-DD/` with one consistent
  copy per database (SQLite online backup API — safe while the app writes) and a tar of uploads.
  Snapshots older than BACKUP_KEEP_DAYS are removed.
* On demand: owners can download a zip of all databases from the System page.
* deploy.sh takes a snapshot before every release so a failed deploy can be rolled back with its data.

Copy `data/backups` off the server regularly (or point BACKUP_DIR at a mounted drive).
"""
import logging
import shutil
import tarfile
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

from . import config, db

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
    return removed


def daily_job() -> None:
    try:
        snapshot()
        prune()
    except Exception:
        log.exception("daily backup failed")


def databases_zip() -> Path:
    """A zip of every database (no media files — they can be large), for download."""
    tmp = Path(tempfile.mkdtemp())
    for database in db.registry.values():
        if database.path.exists():
            database.backup_to(tmp / f"{database.name}.db")
    out = tmp / f"aiko-backup-{db.today()}.zip"
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
