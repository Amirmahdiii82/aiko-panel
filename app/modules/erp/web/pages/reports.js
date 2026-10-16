// Reports: profit & loss for a period, monthly trend, channels, best/worst products, expenses, stock health.
import { $, api, compact, delegate, fa, html, icon, jdate, num, pct, storage, toman } from "/static/js/kit.js";
import { barChart, comboChart } from "/static/js/kit.js";
import { barList, delta, emptyState, moneyKpi, thumb } from "/static/js/kit.js";
import { CHANNEL_ICON } from "../erp.js";

const PERIODS = [
  { key: "month", label: "این ماه" }, { key: "last_month", label: "ماه قبل" }, { key: "3m", label: "سه ماه اخیر" },
  { key: "year", label: "امسال" }, { key: "all", label: "از ابتدا" },
];

export async function render(view, params, { setTitle }) {
  setTitle("گزارش‌ها", "سود واقعی بعد از بهای کالا و هزینه‌ها");
  let period = storage("report-period") || "month";
  view.innerHTML = String(html`<div class="stack">
    <div class="row"><div class="chips scroll" id="periods" style="flex:1"></div>
      <a class="btn sm soft" href="/api/erp/export.xlsx">${icon("file-spreadsheet", "sm")} خروجی اکسل کامل</a></div>
    <div id="body"></div></div>`);
  const load = async () => {
    $("#periods", view).innerHTML = String(html`${PERIODS.map((p) => html`<button class="chip ${p.key === period ? "on" : ""}" data-p="${p.key}">${p.label}</button>`)}`);
    $("#body", view).innerHTML = '<div class="skeleton" style="height:400px"></div>';
    const r = await api(`/api/erp/reports?period=${period}`);
    $("#body", view).innerHTML = String(body(r));
    const mc = $("#monthly", view);
    if (mc && r.monthly.length) comboChart(mc, r.monthly.map((m) => fa(m.label)), r.monthly.map((m) => m.revenue), r.monthly.map((m) => m.net), r.monthly.map((m) => m.expenses));
    const dc = $("#daily", view);
    if (dc && r.daily.length) barChart(dc, r.daily.map((d) => jdate(d.date, { year: false })), r.daily.map((d) => d.revenue));
  };
  await load();
  delegate(view, "click", "[data-p]", (e, el) => { period = el.dataset.p; storage("report-period", period); load(); });
  delegate(view, "click", "[data-href]", (e, el) => { if (el.dataset.href) location.hash = el.dataset.href; });
}

function body(r) {
  const t = r.totals, p = r.previous, inv = r.inventory;
  if (!t.orders && !t.expenses) return String(emptyState("chart-column", `در ${r.label} فروش یا هزینه‌ای ثبت نشده`));
  const mcost = r.missing_cost || {};
  return html`<div class="stack">
    ${mcost.lines ? html`<div class="callout warn">${icon("triangle-alert")}<div><b>${fa(mcost.lines)} ردیف فروش در این بازه قیمت خرید ندارد</b>
      (${num(mcost.revenue)} تومان)، پس سود این بازه بیشتر از واقع نشان داده می‌شود. <a href="#/erp/products?f=nocost">وارد کردن قیمت خرید</a> — فروش‌های گذشته خودکار اصلاح می‌شوند.</div></div>` : ""}
    <div class="grid g4">
      ${moneyKpi({ label: "فروش", amount: t.revenue, color: "indigo", ico: "trending-up",
        foot: html`${p ? delta(t.revenue, p.revenue) : ""} ${fa(t.orders)} سفارش، ${fa(t.items)} عدد` })}
      ${moneyKpi({ label: "سود ناخالص", amount: t.gross, color: "orchid", ico: "sparkles",
        foot: html`حاشیه ${pct(t.margin, 1)}، بهای کالا ${compact(t.cogs)}` })}
      ${moneyKpi({ label: "هزینه‌های جاری", amount: t.expenses, color: "coral", ico: "receipt",
        foot: html`${p ? delta(t.expenses, p.expenses) : ""} بسته‌بندی، تبلیغات، …` })}
      ${moneyKpi({ label: "سود خالص", amount: t.net, color: t.net >= 0 ? "mint" : "coral", ico: "piggy-bank",
        foot: html`${p ? delta(t.net, p.net) : ""} ${r.label}` })}
    </div>

    <section class="card">
      <div class="card-head"><h2>${icon("chart-column")} روند ماهانه</h2><span class="spacer"></span><span class="small muted">فروش، هزینه‌ها و سود خالص هر ماه</span></div>
      ${r.monthly.length ? html`<div class="chart-box tall"><canvas id="monthly"></canvas></div>` : emptyState("chart-column", "داده‌ای نیست")}
      ${r.daily.length > 1 ? html`<h3 class="mt20">${icon("calendar", "sm")} روزانه</h3><div class="chart-box mt8"><canvas id="daily"></canvas></div>` : ""}
    </section>

    <div class="grid g2">
      <section class="card">
        <div class="card-head"><h2>${icon("receipt")} صورت سود و زیان</h2><span class="spacer"></span><span class="small muted">${r.label}</span></div>
        <div class="list">
          <div class="list-item"><span class="grow">فروش (مبلغ دریافتی از مشتری)</span><b class="num">${num(t.revenue)}</b></div>
          ${t.discount ? html`<div class="list-item small"><span class="grow muted">  شامل تخفیف داده‌شده</span><span class="num muted">${num(t.discount)}</span></div>` : ""}
          ${t.shipping ? html`<div class="list-item small"><span class="grow muted">  شامل هزینه ارسال از مشتری</span><span class="num muted">${num(t.shipping)}</span></div>` : ""}
          <div class="list-item"><span class="grow">بهای تمام‌شده کالای فروخته‌شده</span><b class="num bad-ink">−${num(t.cogs)}</b></div>
          <div class="list-item"><span class="grow bold">سود ناخالص</span><b class="num">${num(t.gross)}</b></div>
          ${r.expense_categories.map((c) => html`<div class="list-item small"><span class="grow muted">${c.category}</span><span class="num bad-ink">−${num(c.amount)}</span></div>`)}
          <div class="list-item"><span class="grow bold">سود خالص</span><b class="num ${t.net < 0 ? "bad-ink" : "ok-ink"}" style="font-size:18px">${num(t.net)}</b></div>
        </div>
        <p class="tiny muted mt12">پول خرید کالا هزینه حساب نمی‌شود؛ وقتی کالا فروخته شد به‌عنوان «بهای تمام‌شده» کم می‌شود. خرید کالا در این بازه: ${toman(r.stock_spend)}${t.unpaid ? `، فروش پرداخت‌نشده: ${toman(t.unpaid)}` : ""}</p>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("layers")} کانال‌های فروش</h2></div>
        ${r.channels.length ? barList(r.channels, { label: (c) => html`${icon(CHANNEL_ICON[c.channel] || "tag", "sm")} ${c.label}`, value: (c) => c.revenue,
          sub: (c) => `${fa(c.orders)} سفارش، سود ${compact(c.gross)}` }) : emptyState("layers", "فروشی نیست")}
        ${r.sellers.length > 1 ? html`<h3 class="mt20">${icon("users", "sm")} فروشنده‌ها</h3><div class="mt12">${barList(r.sellers, { label: (s) => s.name, value: (s) => s.revenue,
          sub: (s) => `${fa(s.orders)} فروش${s.commission ? `، پورسانت ${compact(s.commission)}` : ""}` })}</div>` : ""}
      </section>
    </div>

    <div class="grid g2">
      <section class="card">
        <div class="card-head"><h2>${icon("star")} پرسودترین محصولات</h2></div>
        ${r.top_products.length ? html`<div class="table-wrap"><table class="t">
          <thead><tr><th>محصول</th><th class="n">تعداد</th><th class="n">فروش</th><th class="n">سود</th><th class="n">حاشیه</th></tr></thead>
          <tbody>${r.top_products.map((p) => html`<tr class="${p.product_id ? "clickable" : ""}" data-href="${p.product_id ? `#/erp/products/${p.product_id}` : ""}">
            <td><div class="prod-cell" style="min-width:180px">${thumb(p, "sm")}<span class="small">${p.name}</span></div></td>
            <td class="n">${fa(p.qty)}</td><td class="n">${compact(p.revenue)}</td><td class="n bold">${compact(p.profit)}</td>
            <td class="n ${p.margin < 0.15 ? "warn-ink" : ""}">${pct(p.margin)}</td></tr>`)}</tbody></table></div>` : emptyState("star", "فروشی نیست")}
        ${r.worst_products.filter((p) => p.margin < 0.15).length ? html`<div class="callout warn mt16">${icon("triangle-alert")}<div><b>حاشیه سود کم:</b>
          ${r.worst_products.filter((p) => p.margin < 0.15).map((p) => `${p.name} (${pct(p.margin)})`).join("، ")} — قیمت فروش این‌ها را بررسی کنید.</div></div>` : ""}
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("boxes")} وضعیت انبار</h2><span class="spacer"></span><span class="small muted">همین الان</span></div>
        <div class="grid g3" style="gap:12px">
          <div class="inset"><div class="small muted">ارزش خرید</div><div class="bold num">${compact(inv.cost_value)}</div></div>
          <div class="inset"><div class="small muted">ارزش فروش</div><div class="bold num">${compact(inv.retail_value)}</div></div>
          <div class="inset"><div class="small muted">سود بالقوه</div><div class="bold num ok-ink">${compact(inv.potential_profit)}</div></div>
        </div>
        <p class="small muted mt12">${fa(inv.units)} عدد در ${fa(inv.products)} محصول، ${fa(inv.out_count)} ناموجود، ${fa(inv.low_count)} رو به اتمام</p>
        <h3 class="mt16">${icon("clock", "sm")} بدون فروش در ۴۵ روز اخیر</h3>
        ${inv.slow.length ? html`<div class="list mt8">${inv.slow.map((p) => html`<a class="list-item clickable" href="#/erp/products/${p.id}" style="text-decoration:none">
            ${thumb(p, "sm")}<span class="grow small">${p.name}<br><span class="muted tiny">${fa(p.stock)} عدد، آخرین فروش: ${p.last_sale ? jdate(p.last_sale) : "هیچ‌وقت"}</span></span>
            <span class="num small">${compact(p.tied)} خوابیده</span></a>`)}</div>
          <p class="tiny muted mt8">پول این کالاها خوابیده؛ تخفیف یا تبلیغ را در نظر بگیرید.</p>` : html`<p class="small muted mt8">همه کالاها در ۴۵ روز اخیر فروش داشته‌اند 👌</p>`}
      </section>
    </div>
  </div>`;
}
