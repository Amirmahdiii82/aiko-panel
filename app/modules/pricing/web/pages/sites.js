// Competitors and runs: which sites are read and counted, per-site status, crawl history.
import { api, delegate, emptyState, fa, html, icon, on, raw, toast } from "/static/js/kit.js";
import { P, canEdit, faDate, n, refreshMeta, startCrawl } from "../pricing.js";

const STATUS = {
  ok: html`<span class="badge ok">✓ موفق</span>`, partial: html`<span class="badge warn">ناقص</span>`,
  blocked: html`<span class="badge bad" title="سایت درخواست‌ها را مسدود کرد (کپچا/محدودیت)">⛔ مسدود</span>`,
  failed: html`<span class="badge bad">✕ خطا</span>`, running: html`<span class="badge info">در حال اجرا</span>`,
  skipped: html`<span class="badge warn" title="بعد از مسدود شدن، یک دور استراحت می‌کند">⏸ استراحت</span>`,
};
const TRIGGER = { schedule: "زمان‌بندی", manual: "دستی", cli: "خط فرمان", startup: "شروع برنامه" };

export async function render(view, params, { setTitle }) {
  setTitle("رقبا و اجراها", "کدام سایت‌ها خوانده و در محاسبات شمرده شوند");
  const draw = async () => {
    const [meta, sum, crawls] = await Promise.all([refreshMeta(), api("/api/pricing/summary"), api("/api/pricing/crawls?limit=15")]);
    const h2h = Object.fromEntries(sum.head_to_head.map((x) => [x.site, x]));
    const edit = canEdit();
    view.innerHTML = String(html`<div class="stack pricing">
      <div class="callout">${icon("info")}<div>«در محاسبات» را برای سایت‌هایی خاموش کنید که نمی‌خواهید مبنای مقایسه باشند (مثلاً فروشنده‌های متفرقه باسلام).
        ${meta.schedule.length ? `بروزرسانی خودکار هر روز ساعت ${meta.schedule.map(fa).join(" و ")} (به وقت تهران).` : "بروزرسانی خودکار خاموش است؛ قیمت‌ها فقط با دکمه «بروزرسانی» تازه می‌شوند (CRAWL_TIMES در تنظیمات سرور)."}</div></div>
      <section class="card"><div class="table-wrap"><table class="t">
        <thead><tr><th>سایت</th><th>خواندن قیمت</th><th title="اگر خاموش باشد قیمت‌ها نمایش داده می‌شوند ولی در شاخص، رتبه و پیشنهادها حساب نمی‌شوند">در محاسبات</th>
          <th>آخرین اجرا</th><th class="n">محصول مشترک</th><th class="n">ارزان‌تر از شما</th><th></th></tr></thead>
        <tbody>${meta.sites.map((s) => html`<tr>
          <td><b>${s.name}</b> ${s.marketplace ? html`<span class="badge">بازارگاه</span>` : ""}<div class="small muted ltr" style="text-align:right">${s.url}</div></td>
          <td><label class="switch"><input type="checkbox" data-site-toggle="${s.key}" ${s.enabled ? raw("checked") : ""} ${edit ? "" : raw("disabled")} aria-label="خواندن قیمت از ${s.name}"><span></span></label></td>
          <td><label class="switch"><input type="checkbox" data-site-stats="${s.key}" ${s.in_stats ? raw("checked") : ""} ${edit ? "" : raw("disabled")} aria-label="محاسبه ${s.name} در شاخص"><span></span></label></td>
          <td>${STATUS[h2h[s.key]?.last_status] || html`<span class="badge">—</span>`}${h2h[s.key]?.last_error ? html`<div class="small muted" style="max-width:320px">${h2h[s.key].last_error}</div>` : ""}</td>
          <td class="n">${n(h2h[s.key]?.overlap || 0)}</td>
          <td class="n">${h2h[s.key]?.cheaper_pct == null ? "—" : `${n(h2h[s.key].cheaper_pct)}٪`}</td>
          <td>${edit ? html`<button class="btn xs soft" data-crawl-site="${s.key}">${icon("refresh-cw", "sm")} فقط این سایت</button>` : ""}</td></tr>`)}
        </tbody></table></div></section>
      <section class="card"><div class="card-head"><h2>${icon("history")} تاریخچه اجراها</h2></div><div class="table-wrap"><table class="t">
        <thead><tr><th>زمان</th><th>نوع</th><th>وضعیت</th><th class="n">محصولات</th><th>سایت‌ها</th></tr></thead>
        <tbody>${crawls.items.length ? crawls.items.map((c) => html`<tr><td class="nowrap">${faDate(c.started_at)}</td>
          <td>${TRIGGER[c.trigger] || c.trigger}</td>
          <td>${c.status === "done" ? html`<span class="badge ok">تمام شد</span>` : c.status === "running" ? html`<span class="badge info">در حال اجرا</span>`
            : html`<span class="badge bad" title="${c.stats?.error || ""}">ناموفق</span>`}
            ${c.stats?.error ? html`<div class="small muted">${c.stats.error}</div>` : ""}</td>
          <td class="n">${n(c.stats?.products)}</td>
          <td><div class="offer-meta">${c.sites.map((s) => html`<span title="${s.last_error || ""}">${P.siteNames[s.site] || s.site}: ${STATUS[s.status] || ""} <span class="num">${n(s.found)}</span></span>`)}</div></td></tr>`)
          : html`<tr><td colspan="5">${emptyState("history", "هنوز اجرایی نبوده")}</td></tr>`}
        </tbody></table></div></section>
    </div>`);
  };
  await draw();
  delegate(view, "change", "[data-site-toggle]", async (e, c) => {
    await api(`/api/pricing/sites/${c.dataset.siteToggle}`, { method: "POST", body: { enabled: c.checked } });
    toast(c.checked ? "فعال شد" : "غیرفعال شد");
  });
  delegate(view, "change", "[data-site-stats]", async (e, c) => {
    await api(`/api/pricing/sites/${c.dataset.siteStats}`, { method: "POST", body: { in_stats: c.checked } });
    toast(c.checked ? "در محاسبات لحاظ می‌شود" : "فقط نمایش داده می‌شود، در محاسبات نه");
  });
  delegate(view, "click", "[data-crawl-site]", (e, b) => startCrawl({ sites: [b.dataset.crawlSite] }));
  const off = on("pricing:state", (ev) => { if (ev?.state === "done" || ev?.state === "failed" || ev?.state === "started") draw(); });
  return off;
}
