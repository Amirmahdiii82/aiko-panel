// Website connection. One rule (site/stock.py): the panel keeps stock, the site shows it. This page is built around
// that: a status card, a one-time start (which numbers are right today), one list of what is left to do, and — folded
// away — the linked products, the full history sync and the log. The site address and keys live in Settings.
import { api, confirmBox, delegate, fa, html, icon, isOwner, jdate, num, on, parseNum, timeOf, toast } from "/static/js/kit.js";
import { thumb } from "/static/js/kit.js";
import { refreshMe, wooBadge } from "../erp.js";

const STEPS = { catalog: "خواندن همه محصولات و رنگ‌ها از سایت…", orders: "خواندن همه سفارش‌های سایت…", apply: "ثبت فروش‌ها و هماهنگ کردن با داده‌های اکسل…" };
const when = (ts) => (ts ? `${jdate(ts.slice(0, 10), { year: false })} ساعت ${timeOf(ts)}` : "");
const LOG_LABEL = { stock_check: "بررسی موجودی", push_stock: "ارسال موجودی", pull_orders: "سفارش‌ها", webhook: "وب‌هوک",
  webhooks: "ثبت فوری", full_sync: "همگام‌سازی کامل", worker: "اتصال" };

export async function render(view, params, { setTitle }) {
  setTitle("اتصال سایت", "موجودی در پنل، همان عدد در سایت");
  let st = await api("/api/erp/woo");
  let cat = await api("/api/erp/woo/catalog");
  const draw = () => { view.innerHTML = String(page(st, cat)); };
  draw();
  const reload = async () => { st = await api("/api/erp/woo", { quiet: true }); cat = await api("/api/erp/woo/catalog", { quiet: true }); draw(); };

  const busy = async (el, label, fn) => {
    el.disabled = true;
    el.innerHTML = String(html`<span class="spin"></span> ${label}`);
    try { await fn(); } finally { reload(); }
  };
  delegate(view, "click", "[data-act]", async (e, el) => {
    const act = el.dataset.act;
    if (act === "start") {
      const site = el.dataset.side === "site";
      if (!(await confirmBox(site
        ? "موجودی پنل برای همه محصولات وصل‌شده با عدد فعلی سایت جایگزین شود؟ از این به بعد موجودی فقط در پنل تغییر می‌کند و سایت همان را نشان می‌دهد."
        : "موجودی سایت برای همه محصولات وصل‌شده با عدد فعلی پنل جایگزین شود؟ از این به بعد موجودی فقط در پنل تغییر می‌کند و سایت همان را نشان می‌دهد.",
      { okText: "شروع همگام‌سازی" }))) return;
      busy(el, "در حال هماهنگ کردن…", async () => {
        const r = await api("/api/erp/woo/start", { method: "POST", body: { side: el.dataset.side } });
        await refreshMe();
        toast(`همگام‌سازی شروع شد؛ ${fa(r.changed)} محصول هماهنگ شد`);
      });
    }
    if (act === "sync-now") {
      busy(el, "در حال بررسی…", async () => {
        const r = await api("/api/erp/woo/sync-now", { method: "POST" });
        toast([`${fa(r.checked)} محصول بررسی شد`, r.pushed && `${fa(r.pushed)} به سایت فرستاده شد`,
          r.corrected && `${fa(r.corrected)} عدد دستی سایت اصلاح شد`, r.created && `${fa(r.created)} محصول تازه`].filter(Boolean).join("، "));
      });
    }
    if (act === "codes") {
      if (!(await confirmBox("کد پنل روی محصولاتی از سایت که کد (SKU) ندارند نوشته شود؟ چیز دیگری در سایت تغییر نمی‌کند.", { okText: "بنویس" }))) return;
      busy(el, "در حال نوشتن…", async () => {
        const r = await api("/api/erp/woo/codes", { method: "POST" });
        toast(`${fa(r.written)} کد در سایت نوشته شد${r.errors.length ? `، ${fa(r.errors.length)} نشد` : ""}`, r.errors.length ? "info" : "success");
      });
    }
    if (act === "retry") { await api(`/api/erp/products/${el.dataset.pid}/push`, { method: "POST" }); toast("دوباره فرستاده می‌شود"); setTimeout(reload, 2500); }
    if (act === "webhooks") busy(el, "در حال ساخت…", async () => { await api("/api/erp/woo/webhooks", { method: "POST" }); toast("ثبت فوری فعال شد"); });
    if (act === "full-sync") {
      if (!(await confirmBox("همه سفارش‌های سایت از اول خوانده می‌شوند. فروش‌های سایت که دستی یا از اکسل ثبت شده‌اند با سفارش دقیق سایت جایگزین می‌شوند (قیمت خرید اکسل حفظ می‌شود). قبلش خودکار پشتیبان گرفته می‌شود. شروع شود؟", { okText: "شروع" }))) return;
      await api("/api/erp/woo/full-sync", { method: "POST" });
      toast("شروع شد؛ چند دقیقه طول می‌کشد", "info");
      reload();
    }
    if (act === "link") {
      const sel = view.querySelector(`select[data-manual="${el.dataset.pid}"]`);
      if (!sel.value) return toast("محصول سایت را انتخاب کنید", "error");
      const [woo, vr] = sel.value.split(":");
      await api("/api/erp/woo/link", { method: "POST", body: { product_id: Number(el.dataset.pid), woo_id: Number(woo), variation_id: vr ? Number(vr) : null } });
      toast("وصل شد");
      reload();
    }
    if (act === "merge") {
      if (!(await confirmBox(`«${el.dataset.name}» با «${el.dataset.intoName}» یکی شود؟ همه فروش‌ها، خریدها و موجودی آن به محصول سایت منتقل می‌شود.`, { okText: "ادغام" }))) return;
      await api(`/api/erp/products/${el.dataset.pid}/merge`, { method: "POST", body: { into: Number(el.dataset.into) } });
      toast("ادغام شد");
      reload();
    }
    if (act === "unlink") {
      if (!(await confirmBox("اتصال این محصول به سایت قطع شود؟", { danger: true, okText: "قطع اتصال" }))) return;
      await api("/api/erp/woo/unlink", { method: "POST", body: { product_id: Number(el.dataset.pid) } }); reload();
    }
  });
  delegate(view, "submit", "[data-count]", async (e, form) => {
    e.preventDefault();
    if (form.qty.value.trim() === "") return toast("تعداد را وارد کنید", "error");
    form.querySelector("button").disabled = true;
    await api("/api/erp/woo/count", { method: "POST", body: { product_id: Number(form.dataset.count), qty: Math.round(parseNum(form.qty.value)) } });
    toast("ثبت شد؛ سایت هم همین عدد را می‌گیرد");
    setTimeout(reload, 2500);
  });
  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "site_sync" || (ev.type === "product" && ev.woo_state) || (ev.type === "refresh" && ev.scope === "products")) {
      clearTimeout(timer); timer = setTimeout(reload, 1500);
    }
  });
  return () => { off(); clearTimeout(timer); };
}

function page(st, cat) {
  if (!st.configured) {
    return html`<section class="card sync-status"><div class="sync-head">
      <span class="sync-orb off">${icon("unlink")}</span>
      <div><h2>سایت هنوز وصل نشده</h2><p class="small muted mt8">آدرس و کلید ووکامرس را ${isOwner() ? html`در <a href="#/settings/connections">تنظیمات ← اتصال‌ها</a>` : "از مدیر کل بخواهید"} وارد کنید.</p></div>
    </div></section>`;
  }
  return html`<div class="stack">
    ${st.settings.stock_start ? statusCard(st) : startCard(st, cat)}
    ${todoCard(st, cat)}
    ${linkedCard(cat)}
    ${advancedCard(st)}
  </div>`;
}

function statusCard(st) {
  const s = st.settings, c = st.counts || {};
  return html`<section class="card sync-status">
    <div class="row between" style="align-items:flex-start">
      <div class="sync-head" style="flex:1 1 260px">
        <span class="sync-orb">${icon("refresh-cw")}</span>
        <div>
          <h2>${c.pending ? `در حال ارسال ${fa(c.pending)} محصول به سایت…` : "سایت با انبار پنل هماهنگ است"}</h2>
          <p class="small muted mt8">${fa(c.ok || 0)} محصول هماهنگ${c.checked_at ? ` — آخرین بررسی ${when(c.checked_at)}` : ""}${s.webhooks_at ? "، سفارش‌ها فوری می‌آیند" : ""}</p>
        </div>
      </div>
      <button class="btn soft sm" data-act="sync-now" ${st.busy ? "disabled" : ""}>${icon("refresh-cw", "sm")} همگام‌سازی همین الان</button>
    </div>
    <ul class="sync-rules">
      <li>${icon("package", "sm")}<span>موجودی را <b>فقط در پنل</b> تغییر دهید: فروش، «خرید کالا» یا اصلاح موجودی. چند ثانیه بعد سایت همان عدد را نشان می‌دهد.</span></li>
      <li>${icon("globe", "sm")}<span>سفارش‌های سایت خودکار فروش ثبت و از موجودی کم می‌شوند.</span></li>
      <li>${icon("tag", "sm")}<span>محصول جدید، رنگ، نام و قیمت را در سایت تعریف کنید؛ خودکار به پنل می‌آید.</span></li>
    </ul>
  </section>`;
}

function startCard(st, cat) {
  const c = st.counts || {};
  const differ = (cat.linked || []).filter((p) => p.woo_state === "differ");
  return html`<section class="card sync-status">
    <div class="sync-head">
      <span class="sync-orb paused">${icon("scale")}</span>
      <div>
        <h2>یک انتخاب تا شروع همگام‌سازی</h2>
        <p class="small muted mt8">از این به بعد پنل مرجع موجودی است و سایت همیشه همان عدد را نشان می‌دهد. فقط یک بار بگویید امروز کدام عدد درست‌تر است.
          ${fa(c.ok || 0)} محصول در هر دو یکی است${differ.length ? html` و <b>${fa(differ.length)} محصول فرق دارد</b>` : ""}.</p>
      </div>
    </div>
    ${differ.length ? html`<div class="table-wrap mt16" style="max-height:300px;overflow-y:auto"><table class="t">
      <thead><tr><th>محصول</th><th class="n">پنل</th><th class="n">سایت</th></tr></thead>
      <tbody>${differ.map((p) => html`<tr><td><div class="prod-cell">${thumb(p, "sm")}<span class="small">${p.name}</span></div></td>
        <td class="n bold">${fa(p.stock)}</td><td class="n bold">${fa(p.woo_stock)}</td></tr>`)}</tbody></table></div>` : ""}
    <div class="start-choice mt16">
      <button class="choice" data-act="start" data-side="site">${icon("globe")}<b>عدد سایت درست است</b><span>موجودی پنل از روی سایت پر می‌شود</span></button>
      <button class="choice" data-act="start" data-side="panel">${icon("package")}<b>عدد پنل درست است</b><span>موجودی سایت از روی پنل تنظیم می‌شود</span></button>
    </div>
    <p class="tiny muted mt12">اگر فروش حضوری و خریدها را در پنل ثبت کرده‌اید، معمولاً عدد پنل؛ اگر موجودی را بیشتر در سایت ویرایش می‌کردید، عدد سایت. هر محصولی را بعداً در «محصولات و انبار» اصلاح کنید، سایت هم درست می‌شود.</p>
  </section>`;
}

function todoCard(st, cat) {
  const rv = st.review || {}, linked = cat.linked || [];
  const errors = linked.filter((p) => p.woo_state === "error");
  const gone = linked.filter((p) => p.woo_state === "gone");
  const whole = linked.filter((p) => p.woo_state === "whole");
  const nocount = linked.filter((p) => p.woo_state === "nocount");
  const dups = rv.duplicates || [], web = rv.unmatched_web_sales || [], mc = rv.missing_cost || {};
  const loose = (cat.suggestions || []).filter((x) => !dups.some((d) => d.product.id === x.product.id));
  const codes = st.missing_codes || 0;
  const n = errors.length + gone.length + whole.length + nocount.length + dups.length + web.length + loose.length + (mc.lines ? 1 : 0) + (codes ? 1 : 0);
  if (!n) return "";
  const row = (p, side, action) => html`<div class="list-item">${thumb(p, "sm")}
    <div class="grow"><a class="title small" href="#/erp/products/${p.id}">${p.name}</a>${side ? html`<div class="sub">${side}</div>` : ""}</div>${action}</div>`;
  return html`<section class="card">
    <div class="card-head"><h2>${icon("list-checks")} کارهای باقی‌مانده</h2><span class="badge warn">${fa(n)}</span></div>
    <div class="stack s12">
      ${codes ? html`<div class="callout">${icon("tag")}<div><b>${fa(codes)} محصول در سایت کد (SKU) ندارد.</b>
        کد هر محصول در پنل (مثل PRD-012) روی همان محصول یا رنگ در سایت نوشته می‌شود؛ از آن به بعد هر دو یک شماره دارند و محصولات تازه هم خودکار کد می‌گیرند.
        <div class="mt8"><button class="btn xs primary" data-act="codes">${icon("tag", "sm")} نوشتن کدها در سایت</button></div></div></div>` : ""}
      ${errors.length ? group("cloud-off", "ارسال به سایت ناموفق بود", "", errors.map((p) => row(p, p.woo_error, html`<button class="btn xs soft" data-act="retry" data-pid="${p.id}">دوباره</button>`))) : ""}
      ${nocount.length ? group("hash", "در سایت تعداد ندارند", "سایت این‌ها را بدون شمارش «موجود» نشان می‌دهد. یک بار بشمارید و ثبت کنید؛ پنل و سایت هر دو همین عدد را می‌گیرند.",
        nocount.map((p) => html`<form class="list-item count-row" data-count="${p.id}">${thumb(p, "sm")}
          <div class="grow"><div class="title small">${p.name}</div><div class="sub">سایت: ${p.woo_in_stock ? "موجود" : "ناموجود"}</div></div>
          <input class="input sm" name="qty" inputmode="numeric" placeholder="تعداد" value="${p.stock > 0 ? fa(p.stock) : ""}" style="width:76px" aria-label="تعداد">
          <button class="btn xs primary" type="submit">ثبت</button></form>`)) : ""}
      ${whole.length ? group("split", "در سایت رنگ‌بندی دارند", "به کل محصول وصل‌اند و معلوم نیست کدام رنگ فروخته شده؛ از صفحه محصول «تفکیک به رنگ‌ها» را بزنید.",
        whole.map((p) => row(p, `سایت (همه رنگ‌ها): ${p.woo_stock == null ? "؟" : fa(p.woo_stock)}`, html`<a class="btn xs soft" href="#/erp/products/${p.id}">تفکیک</a>`))) : ""}
      ${gone.length ? group("circle-off", "در سایت پیدا نشدند", "اگر حذف شده‌اند، اتصال را قطع کنید.",
        gone.map((p) => row(p, "", html`<button class="btn xs ghost" data-act="unlink" data-pid="${p.id}">قطع اتصال</button>`))) : ""}
      ${mc.lines ? html`<div class="callout warn">${icon("triangle-alert")}<div><b>${fa(mc.lines)} ردیف فروش (${fa(mc.products)} محصول) قیمت خرید ندارد</b> و سودشان بیشتر از واقع حساب می‌شود (${num(mc.revenue)} تومان فروش).
        قیمت خرید را در <a href="#/erp/products?f=nocost">انبار</a> وارد کنید.</div></div>` : ""}
      ${dups.length ? group("merge", "احتمالاً یک کالا دو بار ثبت شده", "اگر یکی‌اند ادغام کنید تا موجودی و تاریخچه یک‌جا شود.",
        dups.map((d) => html`<div class="list-item">${thumb(d.product, "sm")}<div class="grow"><div class="title small">${d.product.name}</div>
          <div class="sub">← ${d.site_product.name}</div></div>
          <button class="btn xs ${d.strong ? "primary" : "soft"}" data-act="merge" data-pid="${d.product.id}" data-into="${d.site_product.id}"
            data-name="${d.product.name}" data-into-name="${d.site_product.name}">ادغام</button></div>`)) : ""}
      ${loose.length ? group("link", "محصولات انبار که به سایت وصل نیستند", "اگر در سایت هستند وصلشان کنید؛ اگر فقط حضوری فروخته می‌شوند کاری لازم نیست.",
        loose.map((x) => html`<div class="list-item" style="flex-wrap:wrap">${thumb(x.product, "sm")}<div class="grow" style="min-width:160px"><div class="title small">${x.product.name}</div></div>
          <div class="row nowrap" style="flex:1 1 240px;min-width:0"><select class="select sm" data-manual="${x.product.id}" style="flex:1;min-width:0;width:100%">${catalogOptions(cat)}</select>
          <button class="btn xs soft" data-act="link" data-pid="${x.product.id}">وصل</button></div></div>`)) : ""}
      ${web.length ? group("receipt", "فروش سایتی که سفارشش در سایت پیدا نشد", "دستی یا از اکسل ثبت شده‌اند؛ اگر تکراری‌اند باطلشان کنید.",
        web.map((w) => html`<a class="list-item clickable" href="#/erp/sales/${w.id}" style="text-decoration:none">
          <div class="grow"><div class="title small">${w.code}</div><div class="sub">${jdate(w.date)}</div></div><b class="num">${num(w.total)}</b></a>`)) : ""}
    </div>
  </section>`;
}

function group(ico, title, text, items) {
  return html`<details class="todo-group" open><summary>${icon(ico, "sm")}<b>${title}</b><span class="c-count">${fa(items.length)}</span></summary>
    ${text ? html`<p class="small muted">${text}</p>` : ""}<div class="list">${items}</div></details>`;
}

function linkedCard(cat) {
  const list = cat.linked || [];
  if (!list.length) return "";
  return html`<details class="card fold">
    <summary><h2>${icon("boxes")} محصولات وصل‌شده</h2><span class="c-count">${fa(list.length)}</span></summary>
    <div class="table-wrap mt12"><table class="t responsive">
      <thead><tr><th>محصول</th><th class="n">پنل</th><th class="n">سایت</th><th>وضعیت</th></tr></thead>
      <tbody>${list.map((p) => html`<tr>
        <td class="m-full"><div class="prod-cell">${thumb(p, "sm")}<a class="small" href="#/erp/products/${p.id}">${p.name}</a></div></td>
        <td class="n bold" data-l="پنل:">${fa(p.stock)}</td>
        <td class="n" data-l="سایت:">${p.woo_state === "nocount" ? html`<span class="small muted">بدون عدد</span>` : p.woo_stock == null ? "؟" : fa(p.woo_stock)}</td>
        <td>${wooBadge(p)}</td></tr>`)}</tbody></table></div>
  </details>`;
}

function advancedCard(st) {
  const s = st.settings, fs = st.full_sync || {};
  return html`<details class="card fold" ${fs.running ? "open" : ""}>
    <summary><h2>${icon("settings")} پیشرفته</h2></summary>
    <div class="stack s12 mt12">
      <div class="row between">
        <div><b class="small">ثبت فوری سفارش‌ها (وب‌هوک)</b><div class="tiny muted">${s.webhooks_at ? `فعال — ${when(s.webhooks_at)}` : "خاموش؛ سفارش‌ها هر چند دقیقه بررسی می‌شوند"}</div></div>
        <button class="btn xs soft" data-act="webhooks">${s.webhooks_at ? "ساخت دوباره" : "فعال کردن"}</button>
      </div>
      <div class="row between">
        <div><b class="small">همگام‌سازی کامل تاریخچه</b><div class="tiny muted">همه سفارش‌های سایت از روز اول با مبلغ دقیق؛ هر شب ۴:۳۰ خودکار${fs.finished_at ? ` — آخرین بار ${when(fs.finished_at)}` : ""}</div></div>
        <button class="btn xs soft" data-act="full-sync" ${fs.running ? "disabled" : ""}>${fs.running ? html`<span class="spin"></span>` : "شروع"}</button>
      </div>
      ${fs.running ? html`<div class="callout">${icon("loader-circle")}<div>${STEPS[fs.step] || "در حال انجام…"}${fs.orders ? ` (${fa(fs.orders)} سفارش)` : ""}</div></div>` : ""}
      ${!fs.running && fs.error ? html`<div class="callout bad">${icon("triangle-alert")}<div>${fs.error}</div></div>` : ""}
      <div><b class="small">گزارش</b>
        ${st.log.length ? html`<div class="list">${st.log.slice(0, 12).map((l) => html`<div class="list-item">
          <span class="badge ${l.ok ? "ok" : "bad"}">${icon(l.ok ? "check" : "x")}</span>
          <div class="grow"><div class="small">${l.detail}</div><div class="tiny muted">${LOG_LABEL[l.action] || l.action}، ${when(l.created_at)}</div></div></div>`)}</div>`
          : html`<p class="small muted">هنوز رویدادی نیست.</p>`}</div>
    </div>
  </details>`;
}

function catalogOptions(cat) {
  const used = new Set((cat.linked || []).map((p) => `${p.woo_id}:${p.woo_variation_id || ""}`));
  const parents = (cat.items || []).filter((e) => !e.variation_id);
  return html`<option value="">انتخاب از سایت…</option>${parents.map((p) => {
    const vars = cat.items.filter((e) => e.woo_id === p.woo_id && e.variation_id);
    return html`<optgroup label="${p.name}">
      <option value="${p.woo_id}:" ${used.has(`${p.woo_id}:`) ? "disabled" : ""}>${p.name}${vars.length ? " (همه رنگ‌ها با هم)" : ""}</option>
      ${vars.map((v) => html`<option value="${v.woo_id}:${v.variation_id}" ${used.has(`${v.woo_id}:${v.variation_id}`) ? "disabled" : ""}>— ${v.variation_label || v.name}</option>`)}
    </optgroup>`;
  })}`;
}
