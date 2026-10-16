"""Generation lifecycle, run by the server so nothing is lost when a browser tab closes.

image: queued → (one synchronous OpenRouter call, up to 3 min) → completed | failed
video: submitting → pending → in_progress → completed | failed | cancelled | expired
       The server polls each running job (every ~20 s) and, once completed, downloads the video
       to data/media so it outlives OpenRouter's retention window and the whole team can see it.

Every change is pushed to browsers as a live event {"module": "media", "type": "generation", "item": ...}.
"""
import base64
import json
import logging
import re
import uuid
from datetime import datetime, timedelta

from ...core import activity, db as core_db, events, jobs
from . import db, openrouter, validation
from .openrouter import UpstreamError

log = logging.getLogger("aiko.media")
MODULE = "media"
TERMINAL = {"completed", "failed", "cancelled", "expired"}
ACTIVE_VIDEO = {"submitting", "pending", "in_progress"}
POLL_SECONDS = 20
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg",
       "image/avif": "avif", "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}
MEDIA_TYPE = re.compile(r"^image/[a-z0-9][a-z0-9.+-]{0,40}$")


# ---------------------------------------------------------------- records
def _decode(row: dict | None) -> dict | None:
    if not row:
        return None
    for key in ("request", "usage", "error", "outputs"):
        row[key] = json.loads(row[key]) if row.get(key) else None
    row["favorite"] = bool(row.get("favorite"))
    for o in row.get("outputs") or []:
        o["url"] = f"/api/media/generations/{row['id']}/files/{o['index']}"
    return row


def get(gen_id: int) -> dict | None:
    with db.database.read() as con:
        return _decode(core_db.one(con.execute(
            "SELECT g.*, u.name AS created_by_name FROM generations g LEFT JOIN core.users u ON u.id = g.created_by "
            "WHERE g.id = ?", (gen_id,))))


def listing(*, kind: str = "", status: str = "", favorite: bool = False, mine_of: int | None = None,
            before: int | None = None, limit: int = 40, batch: str = "") -> list[dict]:
    sql = ("SELECT g.*, u.name AS created_by_name FROM generations g LEFT JOIN core.users u ON u.id = g.created_by "
           "WHERE 1 = 1")
    args: list = []
    for cond, val in (("g.kind = ?", kind), ("g.batch_id = ?", batch)):
        if val:
            sql += f" AND {cond}"
            args.append(val)
    if status == "active":
        sql += " AND g.status NOT IN ('completed', 'failed', 'cancelled', 'expired')"
    elif status:
        sql += " AND g.status = ?"
        args.append(status)
    if favorite:
        sql += " AND g.favorite = 1"
    if mine_of:
        sql += " AND g.created_by = ?"
        args.append(mine_of)
    if before:
        sql += " AND g.id < ?"
        args.append(before)
    sql += " ORDER BY g.id DESC LIMIT ?"
    args.append(min(limit, 200))
    with db.database.read() as con:
        return [_decode(r) for r in core_db.rows(con.execute(sql, args))]


def _update(gen_id: int, **fields) -> dict:
    for key in ("request", "usage", "error", "outputs"):
        if key in fields and fields[key] is not None and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    fields["updated_at"] = core_db.now()
    if fields.get("status") in TERMINAL:
        fields.setdefault("finished_at", core_db.now())
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db.database.tx() as con:
        con.execute(f"UPDATE generations SET {sets} WHERE id = ?", (*fields.values(), gen_id))
    item = get(gen_id)
    events.publish({"module": MODULE, "type": "generation", "item": item})
    return item


def month_spend() -> float:
    start = datetime.now(core_db.TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    with db.database.read() as con:
        return float(con.execute("SELECT IFNULL(SUM(cost), 0) FROM generations WHERE created_at >= ?", (start,)).fetchone()[0])


# ---------------------------------------------------------------- submit
def create_batch(kind: str, models: list[dict], fields: dict, user: dict) -> list[dict]:
    """Validate one payload per model and queue them. Raises ValidationError before anything is spent."""
    if kind not in ("video", "image"):
        raise validation.ValidationError("نوع تولید باید ویدیو یا تصویر باشد.")
    if not models or len(models) > 3:
        raise validation.ValidationError("یک تا سه مدل انتخاب کنید.")
    limit = openrouter.settings()["monthly_limit_usd"]
    if limit and month_spend() >= limit:
        raise validation.ValidationError(f"سقف هزینه ماهانه استودیو (${limit:g}) پر شده است. در تنظیمات استودیو قابل تغییر است.")
    payloads = []
    for m in models:
        body = {**fields, "model": str(m.get("id") or "")}
        payloads.append((m, validation.video_payload(body) if kind == "video" else validation.image_payload(body)))
    batch_id = uuid.uuid4().hex[:16]
    now = core_db.now()
    ids = []
    with db.database.tx() as con:
        for m, payload in payloads:
            cur = con.execute(
                "INSERT INTO generations (batch_id, kind, model_id, model_name, prompt, request, status, created_by, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (batch_id, kind, payload["model"], (m.get("name") or payload["model"])[:200], payload["prompt"],
                 json.dumps(payload, ensure_ascii=False), "queued" if kind == "image" else "submitting", user["id"], now, now))
            ids.append(cur.lastrowid)
    for gen_id in ids:
        jobs.spawn(_run_image(gen_id) if kind == "image" else _submit_video(gen_id), name=f"media.{kind}.{gen_id}")
    return [get(i) for i in ids]


def _error(exc: Exception) -> dict:
    if isinstance(exc, UpstreamError):
        return {"code": exc.code, "message": str(exc), "status": exc.status}
    return {"code": exc.__class__.__name__, "message": str(exc) or "خطای ناشناخته"}


def _cost(usage) -> float | None:
    if isinstance(usage, dict):
        try:
            return float(usage.get("cost")) if usage.get("cost") is not None else None
        except (TypeError, ValueError):
            return None
    return None


async def _run_image(gen_id: int) -> None:
    g = get(gen_id)
    _update(gen_id, status="in_progress")
    try:
        data = await openrouter.request_json("POST", "/api/v1/images", body=g["request"], timeout=180,
                                             limit=openrouter.IMAGE_JSON_LIMIT)
        images = data.get("data") if isinstance(data, dict) else None
        if not isinstance(images, list) or not images:
            raise UpstreamError(502, "OpenRouter تصویری برنگرداند.", "missing_images")
        outputs = []
        folder = _folder()
        for i, item in enumerate(images[: validation.MAX_IMAGES_PER_REQUEST]):
            raw = item.get("b64_json") if isinstance(item, dict) else None
            if not isinstance(raw, str) or not raw:
                raise UpstreamError(502, f"تصویر {i + 1} بدون داده برگشت.", "invalid_upstream_response")
            content = base64.b64decode(raw)
            declared = (item.get("media_type") or "").strip().lower()
            mtype = declared if MEDIA_TYPE.match(declared) else "image/png"
            path = folder / f"{gen_id}-{i}.{EXT.get(mtype, 'png')}"
            path.write_bytes(content)
            outputs.append({"index": i, "path": _rel(path), "media_type": mtype, "bytes": len(content)})
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        _update(gen_id, status="completed", outputs=outputs, usage=usage, cost=_cost(usage), error=None)
    except Exception as exc:
        if not isinstance(exc, UpstreamError):
            log.exception("image generation %s failed", gen_id)
        _update(gen_id, status="failed", error=_error(exc))


async def _submit_video(gen_id: int) -> None:
    g = get(gen_id)
    try:
        data = await openrouter.request_json("POST", "/api/v1/videos", body=g["request"])
        job = str(data.get("id") or "")
        if not job:
            raise UpstreamError(502, "OpenRouter شناسه کار برنگرداند.", "missing_job_id")
        validation.job_id(job)
        status = data.get("status") or "pending"
        _update(gen_id, job_id=job, status=status if status in ACTIVE_VIDEO | TERMINAL else "pending",
                generation_id=data.get("generation_id"), next_poll_at=_after(POLL_SECONDS))
    except Exception as exc:
        if not isinstance(exc, UpstreamError):
            log.exception("video submit %s failed", gen_id)
        _update(gen_id, status="failed", error=_error(exc))


# ---------------------------------------------------------------- polling running video jobs
def _after(seconds: float) -> str:
    return (datetime.now(core_db.TZ) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


async def poll_due() -> None:
    with db.database.read() as con:
        due = [r[0] for r in con.execute(
            "SELECT id FROM generations WHERE kind = 'video' AND job_id IS NOT NULL AND status IN ('pending', 'in_progress') "
            "AND (next_poll_at IS NULL OR next_poll_at <= ?) ORDER BY id LIMIT 20", (core_db.now(),))]
    for gen_id in due:
        await poll(gen_id)


async def poll(gen_id: int) -> dict:
    g = get(gen_id)
    if not g or g["kind"] != "video" or not g["job_id"] or g["status"] in TERMINAL:
        return g
    try:
        data = await openrouter.request_json("GET", f"/api/v1/videos/{g['job_id']}")
    except UpstreamError as exc:
        failures = g["poll_failures"] + 1
        if exc.status in (401, 404):
            return _update(gen_id, status="failed", error=_error(exc), poll_failures=failures)
        delay = max(int(exc.retry_after or 0), POLL_SECONDS * min(failures, 6))
        return _update(gen_id, poll_failures=failures, next_poll_at=_after(delay))
    status = data.get("status") or g["status"]
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else g["usage"]
    if status == "completed":
        _update(gen_id, status="in_progress", usage=usage, cost=_cost(usage), next_poll_at=_after(3600))
        return await _save_video(gen_id)
    if status in TERMINAL:
        err = data.get("error")
        message = err if isinstance(err, str) else (err or {}).get("message") if isinstance(err, dict) else None
        item = _update(gen_id, status=status, usage=usage, cost=_cost(usage),
                       error={"code": f"job_{status}", "message": message or f"کار با وضعیت «{status}» تمام شد."})
        _notify(item)
        return item
    return _update(gen_id, status=status if status in ACTIVE_VIDEO else "pending", usage=usage, poll_failures=0,
                   generation_id=data.get("generation_id") or g["generation_id"], next_poll_at=_after(POLL_SECONDS))


async def _save_video(gen_id: int) -> dict:
    g = get(gen_id)
    path = _folder() / f"{gen_id}-0.mp4"
    try:
        ctype, size = await openrouter.download(f"/api/v1/videos/{g['job_id']}/content?index=0", path)
        if ctype in EXT and EXT[ctype] != "mp4":
            final = path.with_suffix("." + EXT[ctype])
            path.replace(final)
            path = final
        outputs = [{"index": 0, "path": _rel(path), "media_type": ctype if ctype.startswith("video/") else "video/mp4",
                    "bytes": size}]
        item = _update(gen_id, status="completed", outputs=outputs, error=None)
    except Exception as exc:
        log.warning("video %s finished but download failed: %s", gen_id, exc)
        # still completed: content is streamed from OpenRouter on demand while it is retained there
        item = _update(gen_id, status="completed", outputs=[], error={"code": "download_failed", "message": str(exc)})
    _notify(item)
    return item


def _notify(item: dict) -> None:
    ok = item["status"] == "completed"
    activity.record(None, MODULE, "video_done" if ok else "video_failed",
                    f"🎬 ویدیوی «{item['model_name']}» {'آماده شد' if ok else 'ناموفق بود'}", item["prompt"][:120],
                    user_id=item["created_by"], level="success" if ok else "danger",
                    link=f"#/media/library/{item['id']}", notify=True, bot=True)


# ---------------------------------------------------------------- files
def _folder():
    now = datetime.now(core_db.TZ)
    folder = db.files_dir() / f"{now.year}" / f"{now.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _rel(path) -> str:
    return path.relative_to(db.files_dir()).as_posix()


def file_for(g: dict, index: int):
    for o in g.get("outputs") or []:
        if o["index"] == index:
            target = (db.files_dir() / o["path"]).resolve()
            if target.is_file() and db.files_dir().resolve() in target.parents:
                return target, o["media_type"]
    return None, None


def delete(gen_id: int) -> None:
    g = get(gen_id)
    if not g:
        return
    for o in g.get("outputs") or []:
        target = (db.files_dir() / o["path"]).resolve()
        if db.files_dir().resolve() in target.parents:
            target.unlink(missing_ok=True)
    with db.database.tx() as con:
        con.execute("DELETE FROM generations WHERE id = ?", (gen_id,))
    events.publish({"module": MODULE, "type": "generation_deleted", "id": gen_id})


def recover_on_start() -> None:
    """Image calls cut off by a restart cannot be resumed (and may have been billed); video jobs keep polling."""
    with db.database.tx() as con:
        con.execute("UPDATE generations SET status = 'failed', error = ?, updated_at = ? "
                    "WHERE kind = 'image' AND status IN ('queued', 'in_progress')",
                    (json.dumps({"code": "interrupted", "message": "برنامه وسط تولید ری‌استارت شد؛ ممکن است هزینه آن کسر شده باشد."},
                                ensure_ascii=False), core_db.now()))
        con.execute("UPDATE generations SET status = 'failed', error = ?, updated_at = ? "
                    "WHERE kind = 'video' AND status = 'submitting' AND job_id IS NULL",
                    (json.dumps({"code": "interrupted", "message": "ارسال کار وسط ری‌استارت قطع شد."}, ensure_ascii=False),
                     core_db.now()))
        # videos that completed but whose download was interrupted get another try
        con.execute("UPDATE generations SET next_poll_at = NULL WHERE kind = 'video' AND status = 'in_progress'")
