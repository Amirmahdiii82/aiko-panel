// Home: today at a glance, what needs attention, partner balance, live activity.
import { $, api, compact, delegate, fa, html, icon, jdate, num, on, pct, state, toman } from "/static/js/kit.js";
import { barChart } from "/static/js/kit.js";
import { avatar, barList, delta, emptyState, feedItem, kpi, moneyKpi, thumb } from "/static/js/kit.js";
import { openExpenseForm } from "./expenses.js";
import { openSettlement } from "./money.js";
import { CHANNEL_ICON, erp, isAdmin, stockBadge } from "../erp.js";

export async function render(view, params, { setTitle }) {
  const hour = Number(new Date().toLocaleString("en-US", { hour: "numeric", hour12: false, timeZone: "Asia/Tehran" }));
  const greet = hour < 12 ? "صبح بخیر" : hour < 17 ? "روز بخیر" : "عصر بخیر";
  setTitle(isAdmin() ? "داشبورد فروشگاه" : `${greet}، ${erp.me.user.name}`, jdate(erp.me.today, { weekday: true }));
  let data = await api("/api/erp/dashboard");
  const draw = () => {
    view.innerHTML = String(data.seller ? sellerHome(data) : adminHome(data));
    if (!data.seller) {
      const c = $("#daily-chart", view);
      if (c) barChart(c, data.daily.map((d) => fa(jdate(d.date, { year: false }))), data.daily.map((d) => d.revenue));
    }
  };
  draw();

  delegate(view, "click", "[data-link]", (e, el) => { if (el.dataset.link) location.hash = el.dataset.link; });
  delegate(view, "click", "[data-act]", (e, el) => {
    const act = el.dataset.act;
    if (act === "expense") openExpenseForm();
    if (act === "settle") openSettlement(data.partners.settlement[0]);
  });
  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "activity") {
      const feed = $("#feed", view);
      if (feed) {
        const div = document.createElement("div");
        div.innerHTML = String(feedItem({ ...ev.item, user_name: "" }));
        div.firstElementChild.classList.add("fresh");
        feed.prepend(div.firstElementChild);
      }
    }
    if (ev.type === "refresh" || ev.type === "product") {
      clearTimeout(timer);
      timer = setTimeout(async () => { data = await api("/api/erp/dashboard", { quiet: true }); draw(); }, 1200);
    }
  });
  return () => { off(); clearTimeout(timer); };
}

function adminHome(d) {
  const m = d.month, pm = d.prev_month, inv = d.inventory, money = d.money, site = d.site;
  const settle = d.partners.settlement[0];
  const alerts = [];
  if (inv.out_count) alerts.push({ ico: "ban", cls: "bad", text: `${fa(inv.out_count)} محصول ناموجود`, link: "#/erp/products?f=out" });
  if (inv.low_count) alerts.push({ ico: "triangle-alert", cls: "warn", text: `${fa(inv.low_count)} محصول رو به اتمام`, link: "#/erp/products?f=low" });
  if (site.errors) alerts.push({ ico: "cloud-off", cls: "bad", text: `${fa(site.errors)} خطای همگام‌سازی سایت`, link: "#/erp/site" });
  if (!site.configured) alerts.push({ ico: "globe", cls: "info", text: "سایت هنوز وصل نشده — موجودی سایت خودکار به‌روز نمی‌شود", link: "#/erp/site" });
  else if (!site.auto_push) alerts.push({ ico: "globe", cls: "warn", text: "همگام‌سازی خودکار موجودی سایت خاموش است", link: "#/erp/site" });
  if (site.unlinked && site.configured) alerts.push({ ico: "unlink", cls: "info", text: `${fa(site.unlinked)} محصول به سایت وصل نیست`, link: "#/erp/site" });
  if (money.receivable) alerts.push({ ico: "clock", cls: "warn", text: `${toman(money.receivable)} فروش پرداخت‌نشده`, link: "#/erp/sales?unpaid=1" });
  if (money.with_agents > 0) alerts.push({ ico: "hand-coins", cls: "info", text: `${toman(money.with_agents)} پول نزد فروشنده‌ها`, link: "#/erp/money" });

  return html`<div class="stack">
    <section class="hero">
      <span class="blob-deco" style="width:220px;height:220px;left:-60px;top:-80px"></span>
      <span class="blob-deco" style="width:140px;height:140px;left:22%;bottom:-70px;opacity:.1"></span>
      <div class="row between">
        <div>
          <h1>امروز ${d.today.orders ? html`${fa(d.today.orders)} فروش به مبلغ <span class="num">${compact(d.today.revenue)}</span> تومان` : "هنوز فروشی ثبت نشده"}</h1>
          <p class="muted">${d.month_label}: ${fa(m.orders)} فروش، سود خالص ${compact(m.net)} تومان</p>
        </div>
      </div>
      <div class="quick">
        <button data-link="#/erp/sell"><span class="q-ico" style="background:linear-gradient(135deg,#F6A496,#D27C6D)">${icon("shopping-bag")}</span><span>فروش سریع<small>حضوری، دایرکت، دوستان</small></span></button>
        <button data-act="expense"><span class="q-ico" style="background:linear-gradient(135deg,#D297BE,#AC6E97)">${icon("receipt")}</span><span>ثبت هزینه<small>با عکس رسید</small></span></button>
        <button data-link="#/erp/purchases/new"><span class="q-ico" style="background:linear-gradient(135deg,#978DB3,#5B4B87)">${icon("truck")}</span><span>خرید کالا<small>ورود به انبار</small></span></button>
        <button data-link="#/erp/products?f=out"><span class="q-ico" style="background:linear-gradient(135deg,#9CC4A3,#4D6F54)">${icon("package")}</span><span>موجودی<small>ناموجود کردن سریع</small></span></button>
      </div>
    </section>

    <div class="grid g4">
      ${moneyKpi({ label: "فروش این ماه", amount: m.revenue, color: "indigo", ico: "trending-up",
        foot: html`${delta(m.revenue, pm.revenue)} <span>نسبت به ماه قبل، ${fa(m.orders)} سفارش</span>` })}
      ${moneyKpi({ label: "سود ناخالص", amount: m.gross, color: "orchid", ico: "sparkles",
        foot: html`<span>حاشیه سود ${pct(m.margin)}</span>` })}
      ${moneyKpi({ label: "سود خالص (بعد از هزینه‌ها)", amount: m.net, color: m.net >= 0 ? "mint" : "coral", ico: "piggy-bank",
        foot: html`<span>هزینه‌های جاری ${compact(m.expenses)} تومان</span>` })}
      ${moneyKpi({ label: "ارزش انبار (قیمت خرید)", amount: inv.cost_value, color: "sand", ico: "boxes",
        foot: html`<span>${fa(inv.units)} عدد، ارزش فروش ${compact(inv.retail_value)}</span>` })}
    </div>

    <div class="grid side">
      <section class="card">
        <div class="card-head"><h2>${icon("chart-column")} فروش ۳۰ روز اخیر</h2><span class="spacer"></span>
          <a class="btn sm ghost" href="#/erp/reports">گزارش کامل ${icon("chevron-left", "sm")}</a></div>
        <div class="chart-box"><canvas id="daily-chart" aria-label="نمودار فروش روزانه"></canvas></div>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("layers")} سهم کانال‌ها</h2><span class="spacer"></span><span class="muted small">${d.month_label}</span></div>
        ${d.channels.length ? barList(d.channels, { label: (c) => html`${icon(CHANNEL_ICON[c.channel] || "tag", "sm")} ${c.label}`, value: (c) => c.revenue,
          sub: (c) => `${fa(c.orders)} سفارش` }) : emptyState("layers", "این ماه فروشی نیست")}
      </section>
    </div>

    <div class="grid g3">
      <section class="card">
        <div class="card-head"><h2>${icon("bell")} نیاز به توجه</h2></div>
        ${alerts.length ? html`<div class="list">${alerts.map((a) => html`<div class="list-item clickable" data-link="${a.link}">
          <span class="badge ${a.cls}" style="width:34px;height:34px;padding:0;justify-content:center;border-radius:12px">${icon(a.ico)}</span>
          <span class="grow title">${a.text}</span>${icon("chevron-left", "sm")}</div>`)}</div>`
          : emptyState("circle-check", "همه چیز مرتب است")}
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("handshake")} تسویه شرکا</h2><span class="spacer"></span><a class="btn xs ghost" href="#/erp/money">جزئیات</a></div>
        ${settle ? html`<div class="stack s12">
            <div class="row nowrap">${avatar(settle.from_name)} ${icon("arrow-left")} ${avatar(settle.to_name)}
              <div><b>${settle.from_name}</b> باید به <b>${settle.to_name}</b> بدهد</div></div>
            <div class="money-big">${num(settle.amount)} <span class="small muted">تومان</span></div>
            <button class="btn soft block" data-act="settle">${icon("check")} ثبت این تسویه</button>
          </div>`
          : emptyState("scale", "حساب شرکا صاف است", "هر دو شریک به نسبت سهمشان هزینه کرده‌اند.")}
        <div class="divider"></div>
        <div class="list">
          <div class="list-item"><span class="grow">پول در حساب‌های فروشگاه</span><b class="num">${compact(money.shop_cash)}</b></div>
          ${money.with_agents ? html`<div class="list-item"><span class="grow">نزد فروشنده‌ها</span><b class="num">${compact(money.with_agents)}</b></div>` : ""}
          ${money.receivable ? html`<div class="list-item"><span class="grow">طلب از مشتری‌ها</span><b class="num">${compact(money.receivable)}</b></div>` : ""}
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("package-minus")} رو به اتمام</h2><span class="spacer"></span><a class="btn xs ghost" href="#/erp/products?f=low">همه</a></div>
        ${d.low_stock.length ? html`<div class="list">${d.low_stock.slice(0, 6).map((p) => html`<div class="list-item clickable" data-link="#/erp/products/${p.id}">
            ${thumb(p, "sm")}<span class="grow ellipsis small">${p.name}</span>${stockBadge(p)}</div>`)}</div>`
          : emptyState("package", "موجودی همه محصولات کافی است")}
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>${icon("history")} آخرین رویدادها</h2><span class="spacer"></span>
        <span class="small muted row nowrap"><span class="live-dot ${state.live ? "" : "off"}"></span> زنده</span>
        <a class="btn xs ghost" href="#/activity?module=erp">همه</a></div>
      <div class="feed" id="feed">${d.recent.map(feedItem)}</div>
    </section>
  </div>`;
}

function sellerHome(d) {
  return html`<div class="stack">
    <section class="hero">
      <span class="blob-deco" style="width:200px;height:200px;left:-50px;top:-70px"></span>
      <h1>فروش جدید داشتید؟</h1>
      <p class="muted">همین‌جا ثبت کنید تا موجودی انبار و سایت فوراً کم شود و کسی کالای تمام‌شده را نخرد.</p>
      <a class="btn brand lg mt16" href="#/erp/sell">${icon("plus")} ثبت فروش</a>
    </section>
    <div class="grid g3">
      ${moneyKpi({ label: "فروش ۳۰ روز اخیر شما", amount: d.month_total, color: "indigo", ico: "trending-up" })}
      ${moneyKpi({ label: "پول نزد شما (تحویل‌نشده)", amount: d.held, color: d.held > 0 ? "coral" : "mint", ico: "hand-coins",
        foot: d.held > 0 ? "بعد از تحویل به مدیر، صفر می‌شود" : "همه را تحویل داده‌اید" })}
      ${moneyKpi({ label: "پورسانت ۳۰ روز اخیر", amount: d.commission, color: "orchid", ico: "badge-percent" })}
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
