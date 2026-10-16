"""Media studio HTTP API (mounted at /api/media)."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from ...core import auth
from . import openrouter, service, validation
from .openrouter import UpstreamError

router = APIRouter()
Viewer = Depends(auth.require("media"))
Creator = Depends(auth.require("media", "creator"))
Owner = Depends(auth.admin_user)


def _upstream(exc: UpstreamError) -> HTTPException:
    status = exc.status if 400 <= exc.status < 600 else 502
    return HTTPException(status, str(exc))


# ---------------------------------------------------------------- connection & settings
@router.get("/config")
def config(user=Viewer):
    s = openrouter.settings()
    return {"configured": bool(s["api_key"]), "proxy": bool(s["proxy_url"]), "monthly_limit_usd": s["monthly_limit_usd"],
            "month_spend": round(service.month_spend(), 4), "can_create": user["role"] == "creator",
            "can_configure": user["is_admin"]}


@router.get("/settings")
def get_settings(user=Owner):
    s = openrouter.settings()
    return {"key_set": bool(s["api_key"]), "key_hint": f"…{s['api_key'][-4:]}" if s["api_key"] else "",
            "proxy_url": s["proxy_url"], "monthly_limit_usd": s["monthly_limit_usd"]}


@router.put("/settings")
async def save_settings(request: Request, user=Owner):
    body = await request.json()
    current = service.db.database.get_setting("openrouter", {}) or {}
    if body.get("api_key"):
        current["api_key"] = str(body["api_key"]).strip()
    if body.get("clear_key"):
        current["api_key"] = ""
    if "proxy_url" in body:
        proxy = str(body["proxy_url"] or "").strip()
        if proxy and not proxy.split("://")[0] in ("http", "https", "socks5", "socks5h"):
            raise HTTPException(400, "آدرس پروکسی باید با http:// یا socks5:// شروع شود")
        current["proxy_url"] = proxy
    if "monthly_limit_usd" in body:
        try:
            current["monthly_limit_usd"] = max(0.0, float(body["monthly_limit_usd"] or 0))
        except (TypeError, ValueError):
            raise HTTPException(400, "سقف هزینه باید عدد باشد")
    service.db.database.set_setting("openrouter", current)
    openrouter.clear_cache()
    return get_settings(user)


@router.post("/settings/test")
async def test_settings(user=Owner):
    try:
        data = await openrouter.request_json("GET", "/api/v1/videos/models")
    except UpstreamError as exc:
        raise _upstream(exc)
    return {"ok": True, "video_models": len(data.get("data") or [])}


# ---------------------------------------------------------------- live model catalogue
@router.get("/models")
async def models(kind: str = "video", user=Viewer):
    path = "/api/v1/videos/models" if kind == "video" else "/api/v1/images/models"
    try:
        return await openrouter.cached(path)
    except UpstreamError as exc:
        raise _upstream(exc)


@router.get("/models/{author}/{slug}/endpoints")
async def image_endpoints(author: str, slug: str, user=Viewer):
    try:
        a, s = validation.model_segment(author), validation.model_segment(slug)
        return await openrouter.cached(f"/api/v1/images/models/{quote(a, safe='')}/{quote(s, safe='')}/endpoints")
    except validation.ValidationError as exc:
        raise HTTPException(400, str(exc))
    except UpstreamError as exc:
        raise _upstream(exc)


# ---------------------------------------------------------------- generations
@router.post("/generate")
async def generate(request: Request, user=Creator):
    body = await request.json()
    try:
        items = service.create_batch(body.get("kind"), body.get("models") or [], body.get("fields") or {}, user)
    except validation.ValidationError as exc:
        raise HTTPException(400, str(exc))
    return {"items": items}


@router.get("/generations")
def generations(kind: str = "", status: str = "", favorite: bool = False, mine: bool = False, before: int | None = None,
                limit: int = 40, batch: str = "", user=Viewer):
    return service.listing(kind=kind, status=status, favorite=favorite, mine_of=user["id"] if mine else None,
                           before=before, limit=limit, batch=batch)


@router.get("/generations/{gen_id}")
def generation(gen_id: int, user=Viewer):
    g = service.get(gen_id)
    if not g:
        raise HTTPException(404, "پیدا نشد")
    return g


@router.post("/generations/{gen_id}/refresh")
async def refresh(gen_id: int, user=Viewer):
    g = service.get(gen_id)
    if not g:
        raise HTTPException(404, "پیدا نشد")
    return await service.poll(gen_id)


@router.patch("/generations/{gen_id}")
async def patch(gen_id: int, request: Request, user=Viewer):
    body = await request.json()
    if not service.get(gen_id):
        raise HTTPException(404, "پیدا نشد")
    if "favorite" in body:
        service._update(gen_id, favorite=1 if body["favorite"] else 0)
    return service.get(gen_id)


@router.delete("/generations/{gen_id}")
def delete(gen_id: int, user=Creator):
    g = service.get(gen_id)
    if not g:
        raise HTTPException(404, "پیدا نشد")
    if g["created_by"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "فقط سازنده یا مدیر کل می‌تواند حذف کند")
    service.delete(gen_id)
    return {"ok": True}


@router.get("/generations/{gen_id}/files/{index}")
async def file(gen_id: int, index: int, request: Request, user=Viewer):
    g = service.get(gen_id)
    if not g:
        raise HTTPException(404, "پیدا نشد")
    path, mtype = service.file_for(g, index)
    name = f"aiko-{g['kind']}-{gen_id}-{index + 1}"
    if path:
        # SVG is an active document type: never let it render as a page
        disposition = "attachment" if mtype == "image/svg+xml" or request.query_params.get("download") else "inline"
        return FileResponse(path, media_type=mtype, filename=f"{name}{path.suffix}", content_disposition_type=disposition,
                            headers={"Cache-Control": "private, max-age=604800"})
    if g["kind"] == "video" and g["status"] == "completed" and g["job_id"]:
        return await _stream_from_upstream(g, index, request)
    raise HTTPException(404, "این فایل روی سرور نیست")


async def _stream_from_upstream(g: dict, index: int, request: Request):
    """Fallback when the download failed: stream from OpenRouter while it still retains the video."""
    import httpx
    headers = {"Accept": "video/*, application/octet-stream;q=0.9"}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    try:
        client = openrouter._client(600)
        upstream = await client.send(client.build_request("GET", f"/api/v1/videos/{g['job_id']}/content?index={index}",
                                                          headers=headers), stream=True)
    except UpstreamError as exc:
        raise _upstream(exc)
    except httpx.HTTPError:
        raise HTTPException(502, "OpenRouter در دسترس نیست")
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(upstream.status_code, "این ویدیو دیگر روی OpenRouter نگهداری نمی‌شود")
    passthrough = {k: v for k, v in upstream.headers.items()
                   if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges")}

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()
    return StreamingResponse(body(), status_code=upstream.status_code, headers=passthrough)
