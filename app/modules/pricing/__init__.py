"""Pricing module: your products vs. competitors (Digikala, Torob, Basalam, ...), matching review, new-product pricing."""
import asyncio
import sys
from pathlib import Path

from ...core import jobs
from ...core.botkit import Report
from ...core.text import fa
from ...core.modules import Module
from . import config, crawler, db, insights
from .router import router
from .runner import start_crawl


async def scheduled_crawl() -> None:
    # async so APScheduler runs it on the event loop (sync jobs run in a worker thread with no loop)
    start_crawl("schedule")


async def startup() -> None:
    # a crawl that was cut off by a restart is marked failed
    with db.tx() as c:
        c.execute("UPDATE crawls SET status='failed', finished_at=? WHERE status='running'", (db.now_iso(),))
        c.execute("UPDATE new_products SET status='done' WHERE status='running'")
    for t in config.CRAWL_TIMES:
        jobs.daily(f"pricing.crawl.{t}", t, scheduled_crawl)
    if config.RUN_ON_STARTUP:
        start_crawl("startup")


async def shutdown() -> None:
    db.close()


def summary(user: dict) -> dict:
    rows = insights.analyse_all()
    compared = [r for r in rows if r["index"] is not None]
    dist = {}
    for r in rows:
        dist[r["position"]] = dist.get(r["position"], 0) + 1
    import statistics
    idx = round(statistics.median(
        [r["my_price"] / statistics.median([x["price"] for x in r["sites"]]) * 100 for r in compared]), 1) if compared else None
    last = db.q1("SELECT id, status, started_at, finished_at FROM crawls WHERE status IN ('done','failed') ORDER BY id DESC LIMIT 1")
    risk = sorted([r for r in rows if r["opportunity"] == "risk"], key=lambda r: -(r["gap_min_pct"] or 0))[:3]
    return {
        "products": len(rows), "compared": len(compared), "median_index": idx,
        "far_above": dist.get("far_above", 0), "cheapest": dist.get("cheapest", 0),
        "raise_count": sum(1 for r in rows if r["opportunity"] == "raise"),
        "pending_reviews": db.q1("SELECT COUNT(*) n FROM offers WHERE status='pending'")["n"],
        "last_crawl": last, "running": crawler.is_running(),
        "risk": [{"id": r["id"], "name": r["name"], "image": r["image"], "gap": r["gap_min_pct"]} for r in risk],
    }


def bot_prices() -> str:
    """Competitor prices in one message for the owners' bot."""
    s = summary({})
    if not s["products"]:
        return "🏷 هنوز قیمتی خوانده نشده."
    lines = [f"🏷 قیمت رقبا ({fa(s['compared'])} از {fa(s['products'])} محصول مقایسه شده)",
             f"شاخص قیمت ما: {fa(s['median_index']) if s['median_index'] is not None else '—'} (۱۰۰ = میانه بازار)",
             f"خیلی گران‌تر از بازار: {fa(s['far_above'])} محصول",
             f"ارزان‌ترین بازار: {fa(s['cheapest'])} محصول",
             f"فرصت افزایش قیمت: {fa(s['raise_count'])} محصول",
             f"منتظر تأیید تطبیق: {fa(s['pending_reviews'])}"]
    if s["risk"]:
        lines.append("\n🔻 بیشترین فاصله با ارزان‌ترین رقیب:")
        lines += [f"• {r['name']} — {fa(round(r['gap'] or 0))}٪ گران‌تر" for r in s["risk"]]
    last = s["last_crawl"]
    if last:
        lines.append(f"\nآخرین بروزرسانی: {(last.get('finished_at') or last.get('started_at') or '')[:16].replace('T', ' ')}")
    return "\n".join(lines)


def _cli_crawl(args: list[str]) -> None:
    crawl_id = asyncio.run(crawler.run_crawl("cli", only_sites=args or None))
    print(f"crawl {crawl_id} finished")
    sys.exit(0 if crawl_id else 1)


module = Module(
    id="pricing",
    name="قیمت رقبا",
    icon="chart-line",
    description="مقایسه قیمت محصولات سایت با رقبا، تأیید تطبیق‌ها و قیمت‌گذاری محصول جدید",
    roles={"editor": "مدیر قیمت‌گذاری", "viewer": "فقط مشاهده"},
    router=router,
    web_dir=Path(__file__).resolve().parent / "web",
    databases=[db.database],
    startup=startup,
    shutdown=shutdown,
    notify={"crawl_done": "پایان بروزرسانی قیمت رقبا (با خلاصه)", "crawl_failed": "خطای بروزرسانی قیمت رقبا"},
    summary=summary,
    cli={"crawl": _cli_crawl},
    bot={"prices": Report("🏷 قیمت رقبا", bot_prices)},
)
