"""Application factory: core + the modules listed in MODULES, as one FastAPI app.

Run with `python -m app serve` (uvicorn factory mode: `app.main:create_app`)."""
import asyncio
import hashlib
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .core import auth, backup, config, db, events, jobs, modules
from .core.router import router as core_router

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aiko")
WEB = Path(__file__).resolve().parent / "core" / "web"
# No inline scripts anywhere; styles may be inline (style="" attributes). Remote https images are product
# photos (the shop, competitors); camera uploads go through our own /api/uploads.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
       "media-src 'self' blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
       "form-action 'self'; object-src 'none'")


def init_storage() -> None:
    """Create folders and bring every database to the latest schema (safe to run repeatedly)."""
    for d in (config.DATA_DIR, config.UPLOAD_DIR, config.BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
    db.core.migrate()
    for mod in modules.loaded.values():
        for database in mod.databases:
            db.register(database)
            database.migrate()


def asset_version() -> str:
    """Cache-busting token for the shell: the deployed commit, or a hash of the web files in development."""
    if config.VERSION:
        return config.VERSION[:12]
    h = hashlib.sha1()
    dirs = [WEB] + [m.web_dir for m in modules.loaded.values() if m.web_dir]
    for d in dirs:
        for f in sorted(d.rglob("*")):
            if f.is_file():
                h.update(f"{f}:{f.stat().st_mtime_ns}".encode())
    return h.hexdigest()[:12]


def create_app() -> FastAPI:
    modules.load(config.MODULES)
    init_storage()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        events.attach_loop(asyncio.get_running_loop())
        jobs.reset()
        created = auth.bootstrap()
        if created:
            log.warning("created owner accounts %s with INITIAL_PASSWORD — change it after logging in", created)
        for mod in modules.loaded.values():
            if mod.startup:
                await mod.startup()
        if config.BACKUP_TIME:
            jobs.daily("core.backup", config.BACKUP_TIME, backup.daily_job)
        jobs.every("core.backup.telegram", 300, backup.telegram_tick)     # sends when due (hourly by default)
        jobs.start()
        log.info("ready: modules=%s data=%s", ",".join(modules.loaded), config.DATA_DIR)
        yield
        for mod in modules.loaded.values():
            if mod.shutdown:
                await mod.shutdown()
        await jobs.stop()

    app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(_: Request, exc: sqlite3.IntegrityError):
        return JSONResponse({"detail": f"این رکورد با داده‌های دیگر تداخل دارد ({exc})"}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        msgs = "، ".join(f"{'.'.join(str(p) for p in e.get('loc', [])[1:])}: {e.get('msg')}" for e in exc.errors())
        return JSONResponse({"detail": f"داده نامعتبر: {msgs}"}, status_code=422)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), payment=()")
        response.headers.setdefault("Content-Security-Policy", CSP)
        path = request.url.path
        if path.startswith(("/static/", "/m/")):
            # Scripts import each other without a version in the URL (kit.js → widgets.js), so the browser must
            # re-check them on every load (an unchanged file is a tiny 304) — otherwise it keeps an old copy for hours
            # after a deploy. Versioned URLs (?v=…) and fonts/images may stay cached.
            if request.url.query.startswith("v=") or path.startswith(("/static/fonts/", "/static/img/")):
                response.headers.setdefault("Cache-Control", "public, max-age=604800")
            else:
                response.headers.setdefault("Cache-Control", "no-cache")
        return response

    def domain_error(status: int):
        async def handler(_: Request, exc: Exception):
            return JSONResponse({"detail": str(exc)}, status_code=status)
        return handler

    app.include_router(core_router)
    for mod in modules.loaded.values():
        for exc_class, status in mod.exception_handlers.items():
            app.add_exception_handler(exc_class, domain_error(status))
        if mod.router:
            app.include_router(mod.router, prefix=f"/api/{mod.id}")
        if mod.web_dir:
            app.mount(f"/m/{mod.id}", StaticFiles(directory=mod.web_dir), name=f"web-{mod.id}")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str):
        raise HTTPException(404, "این مسیر API وجود ندارد")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    version = asset_version()
    shell = (WEB / "index.html").read_text(encoding="utf-8").replace("__V__", version).replace("__APP__", config.APP_NAME)

    @app.get("/", include_in_schema=False)
    def index():
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        body = (WEB / "sw.js").read_text(encoding="utf-8").replace("__V__", version)
        return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")

    return app
