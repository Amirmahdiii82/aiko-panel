"""Starting crawls and telling everyone how they went: live progress over SSE (no polling),
an activity entry when a run ends, and an optional bot message with the products at risk."""
import asyncio
import json
import logging

from ...core import activity, events, jobs
from . import crawler, db, insights

log = logging.getLogger("aiko.pricing.runner")
MODULE = "pricing"
TRIGGERS = {"schedule": "زمان‌بندی", "manual": "دستی", "cli": "خط فرمان", "startup": "شروع برنامه",
            "resume": "ادامه بعد از ری‌استارت"}


def start_crawl(trigger: str, **kw) -> bool:
    """Start a crawl in the background. False if one is already running."""
    if crawler.is_running():
        return False
    jobs.spawn(_run(trigger, **kw), name=f"pricing.crawl.{trigger}")
    return True


async def _run(trigger: str, **kw) -> None:
    ticker = asyncio.create_task(_progress_ticker())
    events.publish({"module": MODULE, "type": "crawl", "state": "started", "trigger": trigger})
    try:
        crawl_id = await crawler.run_crawl(trigger, **kw)
    finally:
        ticker.cancel()
    if crawl_id is None:
        return
    row = db.q1("SELECT * FROM crawls WHERE id=?", (crawl_id,)) or {}
    events.publish({"module": MODULE, "type": "crawl", "state": row.get("status", "done"), "crawl_id": crawl_id})
    partial = bool(kw.get("only_sites") or kw.get("product_ids"))
    if row.get("status") == "failed":
        err = json.loads(row.get("stats") or "{}").get("error", "")
        activity.record(None, MODULE, "crawl_failed", "⚠️ بروزرسانی قیمت رقبا ناموفق بود", err[:300], level="danger",
                        link="#/pricing/sites", notify=True, bot=True)
        return
    if partial:
        return
    try:
        s = await asyncio.to_thread(insights.summary)
    except Exception:
        log.exception("summary after crawl failed")
        return
    far = next((d["count"] for d in s["distribution"] if d["key"] == "far_above"), 0)
    lines = [f"شاخص قیمت: {s['median_index'] if s['median_index'] is not None else '—'} (۱۰۰ = میانه بازار)",
             f"بیش از ۱۰٪ گران‌تر از ارزان‌ترین رقیب: {far} محصول",
             f"فرصت افزایش قیمت: {s['raise_count']} محصول"]
    if s["pending_reviews"]:
        lines.append(f"منتظر تأیید تطبیق: {s['pending_reviews']}")
    for r in s["risk"][:3]:
        lines.append(f"• {r['name']} ({r['gap_min_pct']:+.0f}٪)")
    activity.record(None, MODULE, "crawl_done", f"📊 قیمت رقبا بروز شد ({TRIGGERS.get(trigger, trigger)})",
                    "\n".join(lines), level="warning" if far else "success", link="#/pricing", notify=bool(far),
                    bot=True)


async def _progress_ticker() -> None:
    while True:
        await asyncio.sleep(3)
        events.publish({"module": MODULE, "type": "progress", "progress": crawler.progress,
                        "running": crawler.is_running()})
