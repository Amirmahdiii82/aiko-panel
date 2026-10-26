// Shop dashboard. Owners: a period switch (7 / 30 / 90 days, 12 months) and a channel switch, four numbers against
// the period before (the first one dark), revenue over time next to the period before, the channel split, best
// sellers, what needs attention and the partners' balance. Sellers: their own sales and the money they hold.
import { $, api, avatar, compact, delegate, delta, emptyState, fa, html, icon, isOwner, jdate, kpi, moneyKpi, num, on, pct, storage,
  thumb, todoBadge, todoList, toman, trendChart } from "/static/js/kit.js";
import { openExpenseForm } from "./expenses.js";
import { openSettlement } from "./money.js";
import { CHANNEL_ICON, erp, isAdmin } from "../erp.js";

const MAIN_CHANNELS = ["website", "instagram", "in_person"];     // always offered; the rest only when they sold

export async function render(view, params, { setTitle }) {
  const hour = Number(new Date().toLocaleString("en-US", { hour: "numeric", hour12: false, timeZone: "Asia/Tehran" }));
  const greet = hour < 12 ? "صبح بخیر" : hour < 17 ? "روز بخیر" : "عصر بخیر";
  setTitle(isAdmin() ? "داشبورد فروشگاه" : `${greet}، ${erp.me.user.name}`, jdate(erp.me.today, { weekday: true }));
  const pick = storage("erp-dash") || {};
  let days = pick.days || 30, channel = pick.channel || "";
  const load = (quiet = false) => api(`/api/erp/dashboard?days=${days}&channel=${channel}`, { quiet });
  let data = await load();
  const draw = () => {
    view.innerHTML = String(data.seller ? sellerHome(data) : adminHome(data));
    if (!data.seller) {
      const c = $("#trend-chart", view), t = data.trend;
      const labels = t.unit === "day" ? t.labels.map((d) => jdate(d, { year: false })) : t.labels;
      if (c) trendChart(c, labels, t.current, t.previous, { label: data.period_label, prevLabel: "دوره قبل" });
    }
  };
  draw();

  delegate(view, "click", "[data-link]", (e, el) => { if (el.dataset.link) location.hash = el.dataset.link; });
  delegate(view, "click", "[data-act]", (e, el) => {
    const act = el.dataset.act;
    if (act === "expense") openExpenseForm();
    if (act === "settle") openSettlement(data.partners.settlement[0]);
  });
  delegate(view, "click", "[data-days], [data-channel]", async (e, el) => {
    if (el.classList.contains("on")) return;
    if (el.dataset.days) days = Number(el.dataset.days);
    if (el.dataset.channel !== undefined) channel = el.dataset.channel;
    storage("erp-dash", { days, channel });
    data = await load();
    draw();
  });
  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "refresh" || ev.type === "product") {             // every change to a number sends one of these
      clearTimeout(timer);
      timer = setTimeout(async () => { data = await load(true); draw(); }, 1200);
    }
  });
  return () => { off(); clearTimeout(timer); };
}

function adminHome(d) {
  const m = d.period, pm = d.prev_period, inv = d.inventory, money = d.money, site = d.site;
  const settle = d.partners.settlement[0];
  const one = !!d.channel;                       // a single channel: running expenses are the whole shop's
  const alerts = [];
  if (inv.out_count) alerts.push({ ico: "ban", tone: "bad", text: `${fa(inv.out_count)} محصول ناموجود در انبار`, href: "#/erp/products?f=out" });
  if (inv.low_count) alerts.push({ ico: "triangle-alert", tone: "warn", text: `${fa(inv.low_count)} محصول رو به اتمام`, sub: "از «ثبت فروش و خرید ← خرید» دوباره پرش کنید", href: "#/erp/products?f=low" });
  if (!site.configured) alerts.push({ ico: "globe", tone: "warn", text: "سایت هنوز وصل نشده", sub: isOwner() ? "آدرس و کلید ووکامرس در تنظیمات" : "از مدیر کل بخواهید کلید ووکامرس را وارد کند", href: isOwner() ? "#/settings/connections" : "#/erp/site" });
  if (site.errors) alerts.push({ ico: "cloud-off", tone: "bad", text: `${fa(site.errors)} محصول با سایت هماهنگ نمی‌شود`, href: "#/erp/site" });
  if (site.whole) alerts.push({ ico: "split", tone: "warn", text: `${fa(site.whole)} محصول باید به رنگ‌ها تفکیک شود`, href: "#/erp/site" });
  if (site.nocount) alerts.push({ ico: "hash", tone: "info", text: `${fa(site.nocount)} محصول در سایت تعداد موجودی ندارد`, href: "#/erp/site" });
  if (site.unlinked && site.configured) alerts.push({ ico: "unlink", tone: "info", text: `${fa(site.unlinked)} محصول انبار در سایت نیست`, href: "#/erp/products?f=unlinked" });
  if (money.receivable) alerts.push({ ico: "clock", tone: "warn", text: `${toman(money.receivable)} فروش پرداخت‌نشده`, href: "#/erp/sales?unpaid=1" });
  if (money.with_agents > 0) alerts.push({ ico: "hand-coins", tone: "info", text: `${toman(money.with_agents)} پول نزد فروشنده‌ها`, href: "#/erp/money" });
  const vs = d.days >= 365 ? "نسبت به ۱۲ ماه قبل" : `نسبت به ${fa(d.days)} روز قبل`;
  const chTotal = d.channels.reduce((a, c) => a + (c.revenue || 0), 0) || 1;

  return html`<div class="stack">
    <div class="row">
      <div class="seg" role="group" aria-label="بازه">${Object.entries(d.periods).map(([k, label]) =>
        html`<button class="${Number(k) === d.days ? "on" : ""}" data-days="${k}">${label.replace(" اخیر", "")}</button>`)}</div>
      <div class="seg" role="group" aria-label="کانال"><button class="${!d.channel ? "on" : ""}" data-channel="">همه کانال‌ها</button>
        ${Object.entries(d.channel_names).filter(([k]) => MAIN_CHANNELS.includes(k) || d.channels.some((c) => c.channel === k) || k === d.channel).map(([k, label]) =>
          html`<button class="${k === d.channel ? "on" : ""}" data-channel="${k}">${label.split(" / ")[0]}</button>`)}</div>
      <span class="spacer"></span>
      <div class="quick">
        <a href="#/erp/sell"><span class="q-ico">${icon("shopping-bag")}</span>ثبت فروش</a>
        <button data-act="expense"><span class="q-ico">${icon("banknote")}</span>هزینه</button>
        <a href="#/erp/sell?mode=buy"><span class="q-ico">${icon("truck")}</span>خرید کالا</a>
      </div>
    </div>

    <div class="grid g4">
      ${moneyKpi({ hero: true, label: `فروش ${d.period_label}`, amount: m.revenue, href: "#/erp/sales",
        foot: html`${delta(m.revenue, pm.revenue)} <span>${vs}</span>`, link: html`${fa(m.orders)} سفارش · امروز ${compact(d.today.revenue)}` })}
      ${moneyKpi({ label: one ? "سود ناخالص" : "سود خالص", amount: one ? m.gross : m.net, ico: "piggy-bank", tone: (one ? m.gross : m.net) < 0 ? "bad" : "",
        foot: html`${delta(one ? m.gross : m.net, one ? pm.gross : pm.net)} <span>حاشیه ${pct(m.margin)}${one ? "" : ` · هزینه‌ها ${compact(m.expenses)}`}</span>` })}
      ${moneyKpi({ label: "میانگین هر سفارش", amount: m.avg_order, ico: "receipt",
        foot: html`${delta(m.avg_order, pm.avg_order)} <span>${fa(m.items)} قلم فروخته شد</span>` })}
      ${kpi({ label: "ارزش انبار", value: compact(inv.cost_value), unit: "تومان", ico: "boxes", title: `${toman(inv.cost_value)} به قیمت خرید`,
        foot: html`<span>${fa(inv.units)} عدد · به قیمت فروش ${compact(inv.retail_value)}</span>`, href: "#/erp/products" })}
    </div>

    <div class="grid side">
      <section class="card">
        <div class="card-head"><h2>فروش در طول زمان</h2><span class="spacer"></span>
          <span class="small muted row nowrap" style="gap:14px"><span class="row nowrap" style="gap:6px"><i style="width:14px;height:2px;background:var(--chart-1);display:inline-block"></i>${d.period_label}</span>
          <span class="row nowrap" style="gap:6px"><i style="width:14px;height:0;border-top:2px dashed var(--chart-2);display:inline-block"></i>دوره قبل</span></span></div>
        <div class="row" style="align-items:baseline;gap:10px;margin:-4px 0 6px"><span class="money-big">${compact(m.revenue)}</span><span class="small muted">تومان</span>${delta(m.revenue, pm.revenue)}</div>
        <div class="chart-box"><canvas id="trend-chart" aria-label="نمودار فروش"></canvas></div>
      </section>
      <section class="card">
        <div class="card-head"><h2>سهم کانال‌ها</h2><span class="spacer"></span><span class="small muted">${d.period_label}</span></div>
        ${d.channels.length ? html`
          <div class="split-head"><b>${pct((d.channels[0].revenue || 0) / chTotal)}</b><span>${d.channels[0].label}</span></div>
          <div class="split-bar">${d.channels.map((c, i) => html`<span class="s${Math.min(i, 2)}" style="width:${Math.max(2, (c.revenue / chTotal) * 100)}%" title="${c.label}"></span>`)}</div>
          <div class="mt12">${d.channels.map((c, i) => html`<div class="ch-row">
            <span class="sw s${Math.min(i, 2)}"></span>
            <div class="grow"><b>${icon(CHANNEL_ICON[c.channel] || "tag", "sm")} ${c.label}</b><span>${fa(c.orders)} سفارش · میانگین ${compact(c.revenue / Math.max(1, c.orders))}</span></div>
            <div class="amt">${compact(c.revenue)}</div></div>`)}</div>`
          : emptyState("layers", `در ${d.period_label} فروشی نیست`)}
      </section>
    </div>

    <div class="grid g2">
      <section class="card">
        <div class="card-head"><h2>${icon("list-checks")} نیاز به توجه</h2><span class="spacer"></span>${todoBadge(alerts)}</div>
        ${todoList(alerts, { clear: "انبار، سایت و حساب‌ها مشکلی ندارند." })}
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("trophy")} پرفروش‌ها</h2><span class="spacer"></span><a class="btn xs ghost" href="#/erp/reports">گزارش کامل ${icon("chevron-left", "sm")}</a></div>
        ${d.top_products.length ? html`<div class="list">${d.top_products.map((p) => html`<div class="list-item ${p.product_id ? "clickable" : ""}" data-link="${p.product_id ? `#/erp/products/${p.product_id}` : ""}">
            ${thumb(p, "sm")}<div class="grow"><div class="title small ellipsis">${p.name}</div><div class="sub">${fa(p.qty)} عدد</div></div>
            <b class="num small">${compact(p.revenue)}</b></div>`)}</div>`
          : emptyState("trophy", `در ${d.period_label} فروشی نیست`)}
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>${icon("handshake")} شرکا و نقدینگی</h2><span class="spacer"></span><a class="btn xs ghost" href="#/erp/money">حساب‌ها ${icon("chevron-left", "sm")}</a></div>
      <div class="grid g3">
        <div>${settle ? html`<div class="row nowrap">${avatar(settle.from_name, "sm")} ${icon("arrow-left", "sm")} ${avatar(settle.to_name, "sm")}
            <div class="small"><b>${settle.from_name}</b> باید به <b>${settle.to_name}</b> بدهد</div></div>
            <div class="row mt8" style="align-items:baseline"><span class="money-big md">${num(settle.amount)}</span><span class="small muted">تومان</span>
            <button class="btn xs soft" data-act="settle">${icon("check", "sm")} ثبت تسویه</button></div>`
          : html`<div class="small muted">${icon("scale", "sm")} حساب شرکا صاف است؛ هر دو به نسبت سهمشان هزینه کرده‌اند.</div>`}</div>
        <div><div class="small muted">پول در حساب‌های فروشگاه</div><div class="money-big md">${compact(money.shop_cash)}</div></div>
        <div><div class="small muted">طلب از مشتری‌ها${money.with_agents ? " و نزد فروشنده‌ها" : ""}</div>
          <div class="money-big md">${compact((money.receivable || 0) + Math.max(0, money.with_agents || 0))}</div></div>
      </div>
    </section>
  </div>`;
}

function sellerHome(d) {
  return html`<div class="stack">
    <section class="hero">
      <h1>فروش جدید داشتید؟</h1>
      <p class="muted mt8">همین‌جا ثبت کنید تا موجودی انبار و سایت فوراً کم شود و کسی کالای تمام‌شده را نخرد.</p>
      <a class="btn primary lg mt16" href="#/erp/sell">${icon("plus")} ثبت فروش</a>
    </section>
    <div class="grid g3">
      ${moneyKpi({ hero: true, label: "فروش ۳۰ روز اخیر شما", amount: d.month_total, ico: "trending-up" })}
      ${moneyKpi({ label: "پول نزد شما (تحویل‌نشده)", amount: d.held, ico: "hand-coins",
        foot: d.held > 0 ? "بعد از تحویل به مدیر، صفر می‌شود" : "همه را تحویل داده‌اید" })}
      ${moneyKpi({ label: "پورسانت ۳۰ روز اخیر", amount: d.commission, ico: "badge-percent" })}
    </div>
    <section class="card">
      <div class="card-head"><h2>${icon("receipt")} فروش‌های اخیر شما</h2><span class="spacer"></span><a class="btn xs ghost" href="#/erp/sales">همه</a></div>
      ${d.sales.length ? html`<div class="list">${d.sales.slice(0, 10).map((s) => html`<div class="list-item clickable" data-link="#/erp/sales/${s.id}">
          <span class="feed-icon">${icon(CHANNEL_ICON[s.channel] || "tag")}</span>
          <span class="grow"><div class="title">${s.customer_name || s.code}</div><div class="sub">${jdate(s.date)}</div></span>
          <b class="num ${s.status === "void" ? "muted" : ""}">${num(s.total)}</b></div>`)}</div>`
        : emptyState("receipt", "هنوز فروشی ثبت نکرده‌اید")}
    </section>
  </div>`;
}
