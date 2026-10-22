// Website sync. Stock is synced both ways all the time (stocksync.py): a change here reaches the site in seconds, a
// change made on the site arrives here within minutes (instantly with webhooks). This page shows that state, what
// still needs a person (duplicates, hand-typed website sales, items without a cost, items the site does not count),
// the one-time full sync of history, and the log. The site address and keys live in Settings → Connections.
import { api, confirmBox, delegate, fa, html, icon, isOwner, jdate, num, on, parseNum, timeOf, toast } from "/static/js/kit.js";
import { copyText, emptyState, thumb } from "/static/js/kit.js";
import { refreshMe, WOO_STATE, wooBadge } from "../erp.js";

const STEPS = { catalog: "خواندن همه محصولات و رنگ‌ها از سایت…", orders: "خواندن همه سفارش‌های سایت…", apply: "ثبت فروش‌ها و هماهنگ کردن با داده‌های اکسل…" };
const when = (ts) => (ts ? `${jdate(ts.slice(0, 10), { year: false })} ساعت ${timeOf(ts)}` : "");
const PROBLEM = new Set(["error", "gone", "whole"]);
const LOG_LABEL = { stock_check: "بررسی موجودی", push_stock: "ارسال موجودی", pull_orders: "سفارش‌ها", webhook: "وب‌هوک",
  webhooks: "ساخت وب‌هوک", full_sync: "همگام‌سازی کامل", worker: "اتصال" };

export async function render(view, params, { setTitle, query }) {
  setTitle("اتصال سایت", "موجودی و فروش سایت، دوطرفه و خودکار");
  let st = await api("/api/erp/woo");
  let cat = await api("/api/erp/woo/catalog");
  let tab = query?.get("tab") || (st.counts?.conflict ? "conflict" : "stock");
  let filter = "all";

  const draw = () => { view.innerHTML = String(page(st, cat, tab, filter)); };
  draw();
  const reload = async () => { st = await api("/api/erp/woo", { quiet: true }); cat = await api("/api/erp/woo/catalog", { quiet: true }); draw(); };

  delegate(view, "click", "[data-tab]", (e, el) => { tab = el.dataset.tab; draw(); });
  delegate(view, "click", "[data-filter]", (e, el) => { filter = el.dataset.filter; draw(); });
  delegate(view, "click", "[data-copy]", (e, el) => copyText(el.dataset.copy));
  delegate(view, "change", "#stock-sync", async (e, el) => {
    if (!el.checked && !(await confirmBox("اگر خاموش شود، فروش و خرید اینجا دیگر موجودی سایت را تغییر نمی‌دهد و تغییرهای سایت هم اینجا نمی‌آید (سفارش‌ها همچنان ثبت می‌شوند). خاموش شود؟", { okText: "خاموش کن", danger: true }))) {
      el.checked = true; return;
    }
    await api("/api/erp/woo", { method: "PUT", body: { stock_sync: el.checked } });
    await refreshMe();
    toast(el.checked ? "همگام‌سازی دوطرفه روشن شد" : "همگام‌سازی دوطرفه خاموش شد");
    reload();
  });
  delegate(view, "submit", "#opts", async (e) => {
    e.preventDefault();
    await api("/api/erp/woo", { method: "PUT", body: { pull_minutes: Math.max(1, Math.round(parseNum(e.target.pull_minutes.value)) || 3) } });
    toast("ذخیره شد");
    reload();
  });
  delegate(view, "submit", "[data-count]", async (e, form) => {
    e.preventDefault();
    const pid = Number(form.dataset.count), cur = Number(form.dataset.stock);
    const v = Math.round(parseNum(form.qty.value));
    if (!(v >= 0) || form.qty.value.trim() === "") return toast("تعداد را وارد کنید", "error");
    form.querySelector("button").disabled = true;
    // the same number as now still turns counting on for the site: send it exactly
    if (v === cur) await api(`/api/erp/products/${pid}/push`, { method: "POST" });
    else await api(`/api/erp/products/${pid}/adjust`, { method: "POST", body: { set_to: v, reason: "شمارش برای سایت" } });
    toast("ثبت شد؛ سایت هم همین عدد را می‌گیرد");
    setTimeout(reload, 2500);
  });
  delegate(view, "click", "[data-act]", async (e, el) => {
    const act = el.dataset.act;
    if (act === "resolve") {
      const one = el.dataset.pid ? [Number(el.dataset.pid)] : null;
      const site = el.dataset.side === "site";
      if (!one && !(await confirmBox(site
        ? "برای همه محصولات این فهرست، عدد سایت جایگزین عدد انبار شود؟ (فروش‌ها و خریدهایی که بعداً اینجا ثبت شده‌اند حفظ می‌شوند)"
        : "برای همه محصولات این فهرست، عدد انبار روی سایت گذاشته شود؟", { okText: site ? "عدد سایت درست است" : "عدد انبار درست است" }))) return;
      const r = await api("/api/erp/woo/resolve", { method: "POST", body: { side: el.dataset.side, product_ids: one } });
      toast(`${fa(r.count)} محصول هماهنگ شد`);
      setTimeout(reload, 2500);
      return;
    }
    if (act === "sync-now") {
      el.disabled = true;
      el.innerHTML = String(html`<span class="spin"></span> در حال بررسی…`);
      try {
        const r = await api("/api/erp/woo/sync-now", { method: "POST" });
        const parts = [`${fa(r.checked)} محصول بررسی شد`];
        if (r.pushed) parts.push(`${fa(r.pushed)} به سایت فرستاده شد`);
        if (r.adopted) parts.push(`${fa(r.adopted)} تغییر از سایت آمد`);
        if (r.created) parts.push(`${fa(r.created)} محصول تازه`);
        if (r.drift) parts.push(`${fa(r.drift)} تغییر سایت تا یک دقیقه دیگر تأیید می‌شود`);
        toast(parts.join("، "));
      } finally { reload(); }
    }
    if (act === "webhooks") {
      el.disabled = true;
      try {
        const r = await api("/api/erp/woo/webhooks", { method: "POST" });
        toast(r.created.length ? `${fa(r.created.length)} وب‌هوک در سایت ساخته شد` : "وب‌هوک‌ها از قبل بودند و به‌روز شدند");
      } finally { reload(); }
    }
    if (act === "full-sync") {
      if (!(await confirmBox("همه محصولات و همه سفارش‌های سایت از اول خوانده می‌شوند. فروش‌های سایت که دستی یا از اکسل ثبت شده‌اند با سفارش دقیق سایت جایگزین می‌شوند (قیمت خرید اکسل حفظ می‌شود). فروش‌های حضوری/اینستاگرام، خریدها و هزینه‌ها دست نمی‌خورند. قبلش خودکار پشتیبان گرفته می‌شود. شروع شود؟", { okText: "شروع" }))) return;
      await api("/api/erp/woo/full-sync", { method: "POST" });
      toast("شروع شد؛ چند دقیقه طول می‌کشد", "info");
      reload();
    }
    if (act === "link" || act === "link-select") {
      let woo = el.dataset.woo, vr = el.dataset.var;
      if (act === "link-select") {
        const sel = view.querySelector(`select[data-manual="${el.dataset.pid}"]`);
        if (!sel.value) return toast("محصول سایت را انتخاب کنید", "error");
        [woo, vr] = sel.value.split(":");
      }
      await api("/api/erp/woo/link", { method: "POST", body: { product_id: Number(el.dataset.pid), woo_id: Number(woo), variation_id: vr ? Number(vr) : null } });
      toast("وصل شد؛ موجودی‌اش تا چند ثانیه دیگر با سایت مقایسه می‌شود");
      reload();
    }
    if (act === "merge") {
      if (!(await confirmBox(`«${el.dataset.name}» با «${el.dataset.intoName}» یکی شود؟ همه فروش‌ها، خریدها و موجودی آن به محصول سایت منتقل می‌شود.`, { okText: "ادغام" }))) return;
      await api(`/api/erp/products/${el.dataset.pid}/merge`, { method: "POST", body: { into: Number(el.dataset.into) } });
      toast("ادغام شد");
      reload();
    }
    if (act === "unlink") {
      if (!(await confirmBox("اتصال این محصول به سایت قطع شود؟ موجودی‌اش دیگر با سایت همگام نمی‌شود.", { danger: true, okText: "قطع اتصال" }))) return;
      await api("/api/erp/woo/unlink", { method: "POST", body: { product_id: Number(el.dataset.pid) } }); reload();
    }
    if (act === "push") {
      if (!(await confirmBox(`موجودی سایت دقیقاً ${fa(el.dataset.stock)} شود (عدد اینجا)؟`, { okText: "بله" }))) return;
      await api(`/api/erp/products/${el.dataset.pid}/push`, { method: "POST" }); toast("در حال ارسال"); setTimeout(reload, 2500);
    }
    if (act === "use-site") { await api(`/api/erp/products/${el.dataset.pid}/use-site-stock`, { method: "POST" }); toast("موجودی اینجا مثل سایت شد"); reload(); }
  });
  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "site_sync" || (ev.type === "product" && ev.woo_state) || (ev.type === "refresh" && ev.scope === "products")) {
      clearTimeout(timer); timer = setTimeout(reload, 1500);
    }
  });
  return () => { off(); clearTimeout(timer); };
}

function page(st, cat, tab, filter) {
  const s = st.settings, c = st.counts || {}, fs = st.full_sync || {}, rv = st.review || {};
  const configured = st.configured, on = s.stock_sync !== false;
  const loose = (cat.suggestions || []).filter((x) => !(rv.duplicates || []).some((d) => d.product.id === x.product.id));
  const nReview = (rv.duplicates?.length || 0) + (rv.unmatched_web_sales?.length || 0) + loose.length + (rv.missing_cost?.lines ? 1 : 0);
  const problems = (c.errors || 0) + (c.gone || 0) + (c.whole || 0);
  return html`<div class="stack">
    <section class="card sync-status">
      <div class="row between" style="align-items:flex-start">
        <div class="row nowrap" style="align-items:flex-start;gap:14px;min-width:0;flex:1">
          <span class="sync-orb ${!configured ? "off" : on ? "" : "paused"}">${icon(configured ? "refresh-cw" : "unlink")}</span>
          <div style="min-width:0">
            <h2>${!configured ? "سایت هنوز وصل نشده" : on ? "همگام‌سازی دوطرفه روشن است" : "همگام‌سازی موجودی خاموش است"}</h2>
            <p class="small muted mt8">${!configured
              ? html`آدرس و کلید ووکامرس را ${isOwner() ? html`در <a href="#/settings/connections">تنظیمات ← اتصال‌ها</a>` : "از مدیر کل بخواهید"} وارد کنید.`
              : on ? html`فروش و خرید اینجا چند ثانیه بعد در سایت اعمال می‌شود؛ تغییرهای خود سایت (ویرایش موجودی، محصول تازه، قیمت) هر ${fa(s.pull_minutes || 3)} دقیقه${s.webhooks_at ? " و با وب‌هوک فوری" : ""} اینجا می‌آید. سفارش‌های سایت هم خودکار فروش ثبت می‌شوند.`
              : "فقط سفارش‌های سایت ثبت می‌شوند؛ موجودی دو طرف جدا از هم تغییر می‌کند."}</p>
            ${configured ? html`<p class="tiny muted mt8"><span class="ltr">${s.url}</span>${c.checked_at ? ` — آخرین بررسی موجودی ${when(c.checked_at)}` : ""}${s.last_order_sync ? `، سفارش‌ها ${when(s.last_order_sync)}` : ""}</p>` : ""}
          </div>
        </div>
        <label class="check bold"><span class="switch"><input type="checkbox" id="stock-sync" ${on ? "checked" : ""} ${configured ? "" : "disabled"}><span></span></span> دوطرفه</label>
      </div>
      ${configured ? html`<div class="sync-stats mt16">
        ${stat("ok", c.ok, "هماهنگ", "circle-check")}
        ${stat("pending", c.pending, "در حال ارسال", "loader-circle")}
        ${stat("drift", c.drift, "تغییر در سایت", "refresh-cw")}
        ${stat("nocount", c.nocount, "سایت تعداد ندارد", "hash")}
        ${stat("bad", problems + (c.conflict || 0), "نیاز به رسیدگی", "triangle-alert")}
      </div>
      <div class="row mt16">
        <button class="btn primary sm" data-act="sync-now" ${st.busy || fs.running ? "disabled" : ""}>${icon("refresh-cw", "sm")} بررسی همین الان</button>
        ${!s.webhooks_at ? html`<button class="btn soft sm" data-act="webhooks">${icon("zap", "sm")} فعال کردن ثبت فوری (وب‌هوک)</button>` : ""}
        <span class="tiny muted">${fa(c.linked || 0)} از ${fa(c.products || 0)} محصول انبار به سایت وصل است</span>
      </div>` : ""}
    </section>

    ${configured ? html`<section class="card">
      <div class="tabs">
        ${c.conflict ? html`<button class="chip coral ${tab === "conflict" ? "on" : ""}" data-tab="conflict">${icon("scale", "sm")} اختلاف قدیمی <span class="c-count">${fa(c.conflict)}</span></button>` : ""}
        <button class="chip ${tab === "stock" ? "on" : ""}" data-tab="stock">${icon("boxes", "sm")} موجودی محصولات وصل‌شده <span class="c-count">${fa(cat.linked?.length || 0)}</span></button>
        <button class="chip ${tab === "nocount" ? "on" : ""}" data-tab="nocount">${icon("hash", "sm")} شمارش برای سایت <span class="c-count">${fa(c.nocount || 0)}</span></button>
        <button class="chip ${tab === "review" ? "on" : ""}" data-tab="review">${icon("list", "sm")} نیاز به بررسی <span class="c-count">${fa(nReview)}</span></button>
      </div>
      ${tab === "review" ? reviewTab(rv, cat, loose) : tab === "nocount" ? countTab(cat) : tab === "conflict" ? conflictTab(cat) : stockTab(cat, filter)}
    </section>` : ""}

    <div class="grid g2">
      <section class="card">
        <div class="card-head"><h2>${icon("zap")} ثبت فوری (وب‌هوک)</h2>
          ${s.webhooks_at ? html`<span class="badge ok">${icon("check")}فعال</span>` : html`<span class="badge">خاموش</span>`}
          <p>بدون وب‌هوک هم همه چیز هماهنگ می‌شود، فقط با چند دقیقه فاصله. با وب‌هوک، سفارش و ویرایش محصول در سایت همان لحظه اینجا می‌آید.</p></div>
        <div class="row">
          <button class="btn sm ${s.webhooks_at ? "ghost" : "primary"}" data-act="webhooks" ${configured ? "" : "disabled"}>${icon("zap", "sm")} ${s.webhooks_at ? "ساخت دوباره" : "ساخت خودکار در سایت"}</button>
          ${s.webhooks_at ? html`<span class="tiny muted">ساخته شده ${when(s.webhooks_at)}</span>` : ""}
        </div>
        <details class="mt12"><summary class="small muted" style="cursor:pointer">ساخت دستی (اگر ساخت خودکار خطا داد)</summary>
          <p class="small muted mt8">ووکامرس ← پیکربندی ← پیشرفته ← وب‌هوک‌ها ← «افزودن»: برای هر موضوع «سفارش ایجاد شد»، «سفارش به‌روز شد»، «محصول ایجاد شد»، «محصول به‌روز شد» و «محصول حذف شد» یک وب‌هوک فعال با نسخه API v3.</p>
          <div class="inset small stack s8 mt8">
            <div class="row nowrap"><span class="muted">آدرس تحویل:</span><code class="ltr ellipsis" style="flex:1">${st.webhook_url}</code>
              <button class="btn xs ghost" data-copy="${st.webhook_url}" aria-label="کپی">${icon("copy", "sm")}</button></div>
            <div class="row nowrap"><span class="muted">رمز (Secret):</span><code class="ltr ellipsis" style="flex:1">${s.webhook_secret || "—"}</code>
              ${s.webhook_secret ? html`<button class="btn xs ghost" data-copy="${s.webhook_secret}" aria-label="کپی">${icon("copy", "sm")}</button>` : ""}</div>
          </div>
        </details>
        <form id="opts" class="row mt12"><label class="small row nowrap">بررسی خودکار هر <input class="input sm" name="pull_minutes" value="${fa(s.pull_minutes || 3)}" style="width:56px" inputmode="numeric"> دقیقه</label>
          <button class="btn xs soft" type="submit">ذخیره</button></form>
      </section>

      <section class="card">
        <div class="card-head"><h2>${icon("history")} همگام‌سازی کامل تاریخچه</h2><span class="spacer"></span>
          <button class="btn sm soft" data-act="full-sync" ${configured && !fs.running ? "" : "disabled"}>${fs.running ? html`<span class="spin"></span> در حال انجام` : "شروع"}</button>
          <p>همه سفارش‌های سایت از روز اول با مبلغ دقیق (تخفیف، ارسال، کارمزد، برگشت وجه) و وصل کردن محصولات اکسل به سایت. هر شب ۴:۳۰ خودکار؛ دستی فقط وقتی لازم است که تاریخچه قدیمی جا افتاده باشد.</p></div>
        ${fs.running ? html`<div class="callout">${icon("loader-circle")}<div>${STEPS[fs.step] || "در حال انجام…"}${fs.orders ? ` (${fa(fs.orders)} سفارش)` : ""}</div></div>` : ""}
        ${!fs.running && fs.error ? html`<div class="callout bad">${icon("triangle-alert")}<div>${fs.error}</div></div>` : ""}
        ${!fs.running && fs.report ? report(fs) : ""}
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>${icon("list")} گزارش همگام‌سازی</h2></div>
      ${st.log.length ? html`<div class="list">${st.log.slice(0, 15).map((l) => html`<div class="list-item">
        <span class="badge ${l.ok ? "ok" : "bad"}">${icon(l.ok ? "check" : "x")}</span>
        <div class="grow"><div class="small">${l.detail}</div><div class="tiny muted">${LOG_LABEL[l.action] || l.action}، ${when(l.created_at)}</div></div></div>`)}</div>`
        : emptyState("list", "هنوز رویدادی نیست")}
    </section>
  </div>`;
}

function stat(kind, n, label, ico) {
  return html`<div class="sync-stat ${kind} ${n ? "" : "zero"}">${icon(ico, "sm")}<b class="num">${fa(n || 0)}</b><span>${label}</span></div>`;
}

function report(fs) {
  const r = fs.report;
  return html`<div class="list small">
      <div class="list-item"><span class="grow muted">فروش سایت ثبت شد</span><b class="num">${fa(r.sales_created)}</b></div>
      <div class="list-item"><span class="grow muted">جایگزین فروش دستی/اکسل</span><b class="num">${fa(r.sales_replaced)}</b></div>
      <div class="list-item"><span class="grow muted">محصول ساخته / وصل شد</span><b class="num">${fa(r.products_created)} / ${fa(r.linked)}</b></div>
    </div>
    <p class="tiny muted mt8">${fa(r.orders)} سفارش بررسی شد — ${when(fs.finished_at)} (${fs.by || ""})</p>`;
}

const FILTERS = [
  { key: "all", label: "همه" },
  { key: "attention", label: "نیاز به رسیدگی", test: (p) => PROBLEM.has(p.woo_state) || p.woo_state === "drift" || p.woo_state === "conflict" },
  { key: "pending", label: "در حال ارسال", test: (p) => p.woo_state === "pending" || p.woo_state === "force" },
  { key: "ok", label: "هماهنگ", test: (p) => p.woo_state === "ok" },
];

function siteStock(p) {
  if (p.woo_state === "nocount") return html`<span class="muted small">${p.woo_in_stock ? "موجود" : "ناموجود"}، بدون عدد</span>`;
  return p.woo_stock === null || p.woo_stock === undefined ? "؟" : fa(p.woo_stock);
}

function stockTab(cat, filter) {
  if (!cat.linked?.length) return emptyState("link", "هنوز محصولی وصل نشده", "«همگام‌سازی کامل تاریخچه» را یک بار بزنید تا محصولات سایت ساخته و وصل شوند.");
  const f = FILTERS.find((x) => x.key === filter) || FILTERS[0];
  const list = f.test ? cat.linked.filter(f.test) : cat.linked;
  return html`<div class="chips scroll">${FILTERS.map((x) => html`<button class="chip ${x.key === filter ? "on" : ""}" data-filter="${x.key}">${x.label}
      <span class="c-count">${fa(x.test ? cat.linked.filter(x.test).length : cat.linked.length)}</span></button>`)}</div>
    ${list.length ? html`<div class="table-wrap mt12"><table class="t responsive">
    <thead><tr><th>محصول</th><th class="n">اینجا</th><th class="n">سایت</th><th>وضعیت</th><th></th></tr></thead>
    <tbody>${list.map((p) => {
      const st = WOO_STATE[p.woo_state];
      const differs = p.woo_stock !== null && p.woo_stock !== undefined && p.woo_stock !== Math.max(0, p.stock) && p.woo_state !== "pending";
      return html`<tr>
        <td class="m-full"><div class="prod-cell">${thumb(p, "sm")}<div style="min-width:0"><a class="small" href="#/erp/products/${p.id}">${p.name}</a>
          ${p.woo_url && p.woo_name !== p.name ? html`<div class="tiny muted ellipsis"><a href="${p.woo_url}" target="_blank" rel="noopener">${p.woo_name || "صفحه محصول"}</a></div>` : ""}</div></div></td>
        <td class="n bold" data-l="اینجا:">${fa(p.stock)}</td>
        <td class="n ${differs ? "warn-ink bold" : ""}" data-l="سایت:">${siteStock(p)}</td>
        <td class="m-full">${wooBadge(p)}${p.woo_state === "error" && p.woo_error ? html`<div class="tiny bad-ink">${p.woo_error}</div>`
          : st && !["ok", "pending", "force"].includes(p.woo_state) ? html`<div class="tiny muted">${st.tip}</div>` : ""}</td>
        <td class="n m-full nowrap">
          ${differs || p.woo_state === "error" ? html`<button class="btn xs soft" data-act="push" data-pid="${p.id}" data-stock="${Math.max(0, p.stock)}" title="سایت همین عدد اینجا را بگیرد">${icon("cloud-upload", "sm")} عدد اینجا</button>` : ""}
          ${differs ? html`<button class="btn xs ghost" data-act="use-site" data-pid="${p.id}" title="عدد سایت درست است">${icon("download", "sm")} عدد سایت</button>` : ""}
          <button class="btn xs ghost icon" data-act="unlink" data-pid="${p.id}" title="قطع اتصال" aria-label="قطع اتصال">${icon("unlink", "sm")}</button></td>
      </tr>`;
    })}</tbody></table></div>` : emptyState("circle-check", "موردی نیست")}`;
}

function conflictTab(cat) {
  const list = (cat.linked || []).filter((p) => p.woo_state === "conflict" || (p.woo_review === 1 && p.woo_drift));
  if (!list.length) return emptyState("circle-check", "اختلافی نمانده");
  return html`<div class="callout warn">${icon("scale")}<div>این محصولات <b>از قبل</b> در انبار و سایت عدد متفاوتی داشتند. تا الان فروش حضوری و خرید اینجا به سایت نمی‌رفت و ویرایش‌های سایت هم اینجا نمی‌آمد،
      پس هر کدام ممکن است درست باشد و پنل حدس نمی‌زند. برای هر محصول یک بار انتخاب کنید (اگر مطمئن نیستید بشمارید). از آن به بعد همه چیز خودکار و دوطرفه است.</div></div>
    <div class="row mt12"><span class="small muted">برای همه:</span>
      <button class="btn xs soft" data-act="resolve" data-side="site">${icon("globe", "sm")} عدد سایت درست است</button>
      <button class="btn xs soft" data-act="resolve" data-side="here">${icon("package", "sm")} عدد انبار درست است</button></div>
    <div class="table-wrap mt12"><table class="t responsive">
      <thead><tr><th>محصول</th><th class="n">انبار</th><th class="n">سایت</th><th></th></tr></thead>
      <tbody>${list.map((p) => html`<tr>
        <td class="m-full"><div class="prod-cell">${thumb(p, "sm")}<a class="small" href="#/erp/products/${p.id}">${p.name}</a></div></td>
        <td class="n bold" data-l="انبار:">${fa(p.stock)}</td>
        <td class="n bold" data-l="سایت:">${p.woo_drift != null ? fa(p.stock + p.woo_drift) : siteStock(p)}</td>
        <td class="n m-full nowrap">
          <button class="btn xs ghost" data-act="resolve" data-side="site" data-pid="${p.id}">سایت درست است</button>
          <button class="btn xs ghost" data-act="resolve" data-side="here" data-pid="${p.id}">انبار درست است</button></td>
      </tr>`)}</tbody></table></div>`;
}

function countTab(cat) {
  const list = (cat.linked || []).filter((p) => p.woo_state === "nocount");
  if (!list.length) return emptyState("circle-check", "همه محصولات وصل‌شده در سایت تعداد دارند");
  return html`<div class="callout">${icon("info")}<div>در سایت برای این محصولات «مدیریت موجودی» خاموش است؛ سایت فقط «موجود» یا «ناموجود» نشان می‌دهد و هیچ‌وقت خودش تمام نمی‌شود.
      تعداد واقعی هر کدام را بشمارید و ثبت کنید: انبار همین عدد می‌شود و سایت هم از این به بعد با همین عدد دقیق کار می‌کند.</div></div>
    <div class="list mt12">${list.map((p) => html`<form class="list-item count-row" data-count="${p.id}" data-stock="${p.stock}">
      ${thumb(p, "sm")}
      <div class="grow"><div class="title small">${p.name}</div>
        <div class="sub">سایت: ${p.woo_in_stock ? "موجود" : "ناموجود"} — اینجا: ${fa(p.stock)}</div></div>
      <input class="input sm" name="qty" inputmode="numeric" placeholder="تعداد" value="${p.stock > 0 ? fa(p.stock) : ""}" style="width:76px" aria-label="تعداد شمرده‌شده">
      <button class="btn xs primary" type="submit">ثبت</button>
    </form>`)}</div>`;
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

function reviewTab(rv, cat, loose) {
  const dups = rv.duplicates || [], web = rv.unmatched_web_sales || [], mc = rv.missing_cost || {};
  if (!dups.length && !web.length && !loose.length && !mc.lines) return emptyState("circle-check", "همه چیز با سایت هماهنگ است");
  return html`<div class="stack">
    ${mc.lines ? html`<div class="callout warn">${icon("triangle-alert")}<div><b>${fa(mc.lines)} ردیف فروش (${fa(mc.products)} محصول) قیمت خرید ندارد</b> و سودشان بیشتر از واقع حساب می‌شود (${num(mc.revenue)} تومان فروش).
      قیمت خرید این محصولات را در <a href="#/erp/products?f=nocost">انبار</a> وارد کنید یا خریدشان را ثبت کنید؛ فروش‌های گذشته خودکار اصلاح می‌شوند.</div></div>` : ""}

    ${dups.length ? html`<div><h3>${icon("merge", "sm")} احتمالاً یک کالا دو بار ثبت شده</h3>
      <p class="small muted">این محصولات در انبار هستند (مثلاً از اکسل) ولی به سایت وصل نیستند، و محصول سایت با نام نزدیک هم جدا ساخته شده. اگر یکی‌اند، ادغام کنید تا موجودی و تاریخچه یک‌جا شود.</p>
      <div class="list mt8">${dups.map((d) => html`<div class="list-item" style="flex-wrap:wrap">
        <div class="row nowrap" style="flex:1;min-width:220px">${thumb(d.product, "sm")}<div><div class="title small">${d.product.name}</div>
          <div class="sub">انبار — موجودی ${fa(d.product.stock)}، ${fa(d.product.sales)} فروش</div></div></div>
        ${icon("arrow-left", "sm")}
        <div class="row nowrap" style="flex:1;min-width:220px">${thumb(d.site_product, "sm")}<div><div class="title small">${d.site_product.name}</div>
          <div class="sub">سایت — موجودی ${fa(d.site_product.stock)}</div></div></div>
        <button class="btn xs ${d.strong ? "primary" : "soft"}" data-act="merge" data-pid="${d.product.id}" data-into="${d.site_product.id}"
          data-name="${d.product.name}" data-into-name="${d.site_product.name}">ادغام</button>
      </div>`)}</div></div>` : ""}

    ${web.length ? html`<div><h3>${icon("receipt", "sm")} فروش سایتی که سفارشش در سایت پیدا نشد</h3>
      <p class="small muted">این فروش‌ها با کانال «سایت» دستی یا از اکسل ثبت شده‌اند ولی سفارش هم‌تاریخ و هم‌مبلغی در سایت ندارند. بازش کنید: اگر تکراری است باطل کنید، اگر از سایت نبوده کانالش را عوض کنید.</p>
      <div class="list mt8">${web.map((w) => html`<a class="list-item clickable" href="#/erp/sales/${w.id}" style="text-decoration:none">
        <div class="grow"><div class="title small">${w.code}</div><div class="sub">${jdate(w.date)} — ${w.source === "sheet" ? "از اکسل" : "دستی"}</div></div>
        <b class="num">${num(w.total)}</b>${icon("chevron-left", "sm")}</a>`)}</div></div>` : ""}

    ${loose.length ? html`<div><h3>${icon("link", "sm")} محصولات انبار که به سایت وصل نیستند</h3>
      <p class="small muted">اگر در سایت هستند، محصول سایت را انتخاب کنید؛ اگر فقط حضوری/اینستاگرام فروخته می‌شوند، کاری لازم نیست.</p>
      <div class="list mt8">${loose.map((x) => html`<div class="list-item" style="flex-wrap:wrap">
        <div class="row nowrap" style="flex:1;min-width:220px">${thumb(x.product, "sm")}<div><div class="title small">${x.product.name}</div>
          <div class="sub">موجودی ${fa(x.product.stock)}</div></div></div>
        <div class="row nowrap" style="flex:1.4;min-width:260px"><select class="select sm" data-manual="${x.product.id}" style="flex:1">${catalogOptions(cat)}</select>
          <button class="btn xs soft" data-act="link-select" data-pid="${x.product.id}">وصل</button></div>
      </div>`)}</div></div>` : ""}
  </div>`;
}
