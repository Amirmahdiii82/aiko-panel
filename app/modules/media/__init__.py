"""Media studio: AI video and image generation for campaigns through OpenRouter, with a shared team library."""
from pathlib import Path

from ...core import jobs
from ...core.modules import Module
from . import db, openrouter, service
from .router import router


async def startup() -> None:
    service.recover_on_start()
    jobs.every("media.poll", 15, service.poll_due)


def summary(user: dict) -> dict:
    recent = service.listing(status="completed", limit=6)
    active = service.listing(status="active", limit=20)
    return {"configured": openrouter.configured(), "month_spend": round(service.month_spend(), 2),
            "active": len(active),
            "recent": [{"id": g["id"], "kind": g["kind"], "model_name": g["model_name"], "prompt": g["prompt"][:80],
                        "thumb": (g["outputs"] or [{}])[0].get("url") if g["kind"] == "image" else None}
                       for g in recent]}


module = Module(
    id="media",
    name="استودیو محتوا",
    short="استودیو",
    settings_role=None,            # the monthly spending cap is the owners' call
    icon="clapperboard",
    description="ساخت ویدیو و تصویر تبلیغاتی با هوش مصنوعی و کتابخانه مشترک",
    roles={"creator": "سازنده (هزینه‌بر)", "viewer": "فقط مشاهده"},
    router=router,
    web_dir=Path(__file__).resolve().parent / "web",
    databases=[db.database],
    startup=startup,
    notify={"video_done": "آماده شدن ویدیو", "video_failed": "ناموفق شدن ویدیو"},
    summary=summary,
)
