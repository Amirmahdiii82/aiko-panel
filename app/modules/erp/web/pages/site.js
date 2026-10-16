// WooCommerce connection: keys, webhook, product linking, stock sync status and log.
import { $, api, confirmBox, delegate, fa, html, icon, jdate, num, on, timeOf, toast } from "/static/js/kit.js";
import { bindDates, copyText, dateField, emptyState, thumb } from "/static/js/kit.js";
import { erp, refreshMe, wooBadge } from "../erp.js";

export async function render(view, params, { setTitle }) {
  setTitle("اتصال سایت", "aikocosmetics.ir — موجودی از اینجا به سایت، سفارش‌ها از سایت به اینجا");
  let st = await api("/api/erp/woo");
  let cat = await api("/api/erp/woo/catalog");
  let tab = cat.suggestions?.length ? "suggest" : "linked";

  const draw = () => {
    view.innerHTML = String(page(st, cat, tab));
    bindDates(view);
  };
  draw();
  const reload = async () => { st = await api("/api/erp/woo", { quiet: true }); cat = await api("/api/erp/woo/catalog", { quiet: true }); draw(); };

  delegate(view, "click", "[data-tab]", (e, el) => { tab = el.dataset.tab; draw(); });
  delegate(view, "click", "[data-copy]", (e, el) => copyText(el.dataset.copy));
  delegate(view, "change", "#auto-push", async (e, el) => {
    if (el.checked && !(await confirmBox("از این به بعد هر تغییر موجودی محصولات وصل‌شده، همان لحظه در سایت تنظیم می‌شود. قبلش مطمئن شوید موجودی‌های اینجا درست است. روشن شود؟", { okText: "روشن کن" }))) {
      el.checked = false; return;
    }
    await api("/api/erp/woo", { method: "PUT", body: { auto_push: el.checked } });
    await refreshMe();
    toast(el.checked ? "همگام‌سازی خودکار روشن شد" : "همگام‌سازی خودکار خاموش شد");
    reload();
  });
  delegate(view, "submit", "#keys", async (e) => {
    e.preventDefault();
    const f = e.target;
    await api("/api/erp/woo", { method: "PUT", body: {
      url: f.url.value, key: f.key.value, secret: f.secret.value, query_auth: f.query_auth.checked, pull_minutes: Number(f.pull_minutes.value) || 3,
    } });
    toast("ذخیره شد؛ در حال آزمایش اتصال…", "info");
    try {
      const r = await api("/api/erp/woo/test", { method: "POST" });
      toast(`اتصال برقرار شد ✓ ${fa(r.products)} محصول، واحد پول: ${r.currency || "؟"}`);
    } catch (err) { /* toast already shown */ }
    await refreshMe();
    reload();
  });
  delegate(view, "click", "[data-act]", async (e, el) => {
    const act = el.dataset.act;
    if (act === "catalog") {
      el.disabled = true;
      el.innerHTML = String(html`${icon("loader-circle", "sm")} در حال خواندن…`);
      try {
        const r = await api("/api/erp/woo/catalog/refresh", { method: "POST" });
        toast(`${fa(r.count)} محصول و رنگ از سایت خوانده شد${r.source === "public" ? " (بدون عدد موجودی؛ برای موجودی دقیق کلید API لازم است)" : ""}`);
      } finally { reload(); }
    }
    if (act === "link") {
      await api("/api/erp/woo/link", { method: "POST", body: { product_id: Number(el.dataset.pid), woo_id: Number(el.dataset.woo), variation_id: el.dataset.var ? Number(el.dataset.var) : null } });
      toast("وصل شد");
      reload();
    }
    if (act === "link-select") {
      const sel = view.querySelector(`select[data-manual="${el.dataset.pid}"]`);
      if (!sel.value) return toast("محصول سایت را انتخاب کنید", "error");
      const [woo, vr] = sel.value.split(":");
      await api("/api/erp/woo/link", { method: "POST", body: { product_id: Number(el.dataset.pid), woo_id: Number(woo), variation_id: vr ? Number(vr) : null } });
      toast("وصل شد");
      reload();
    }
    if (act === "link-sure") {
      // one site product can only be linked once: keep the strongest claim
      const byTarget = new Map();
      cat.suggestions.filter((s) => sure(s)).forEach((s) => {
        const c = s.candidates[0], key = `${c.woo_id}:${c.variation_id || ""}`;
        if (!byTarget.has(key) || byTarget.get(key).score < c.score) byTarget.set(key, { product_id: s.product.id, woo_id: c.woo_id, variation_id: c.variation_id, score: c.score });
      });
      const links = [...byTarget.values()];
      if (!links.length) return toast("پیشنهاد مطمئنی نیست", "info");
      if (!(await confirmBox(`${fa(links.length)} محصول به پیشنهاد اول وصل شود؟ بعداً هر کدام را می‌توانید عوض کنید.`))) return;
      const res = await api("/api/erp/woo/link", { method: "POST", body: { links } });
      toast(`${fa(res.count)} محصول وصل شد${res.skipped.length ? ` (${fa(res.skipped.length)} مورد قبلاً وصل بود)` : ""}`);
      reload();
    }
    if (act === "unlink") {
      await api("/api/erp/woo/unlink", { method: "POST", body: { product_id: Number(el.dataset.pid) } });
      reload();
    }
    if (act === "push") { await api(`/api/erp/products/${el.dataset.pid}/push`, { method: "POST" }); toast("در صف ارسال"); setTimeout(reload, 3000); }
    if (act === "use-site") { await api(`/api/erp/products/${el.dataset.pid}/use-site-stock`, { method: "POST" }); toast("موجودی اینجا مثل سایت شد"); reload(); }
    if (act === "push-all") {
      if (!(await confirmBox(`موجودی همه ${fa(st.counts.linked || 0)} محصول وصل‌شده روی سایت تنظیم شود؟ (موجودی سایت با عدد اینجا جایگزین می‌شود)`, { okText: "ارسال همه" }))) return;
      const r = await api("/api/erp/woo/push-all", { method: "POST" });
      toast(`${fa(r.queued)} محصول در صف ارسال`);
      setTimeout(reload, 4000);
    }
    if (act === "pull") {
      const r = await api("/api/erp/woo/pull", { method: "POST", body: {} });
      toast(`سفارش‌ها بررسی شد${r.created ? ` — ${fa(r.created)} فروش جدید` : ""}`);
      reload();
    }
    if (act === "backfill") {
      const since = view.querySelector("input[name=since]").value;
      if (!(await confirmBox(`همه سفارش‌های سایت از ${jdate(since)} به بعد خوانده و به‌عنوان فروش ثبت می‌شوند. اگر این سفارش‌ها را قبلاً دستی (مثلاً در اکسل) وارد کرده‌اید، تکراری می‌شوند. ادامه؟`, { okText: "بخوان" }))) return;
      const r = await api("/api/erp/woo/pull", { method: "POST", body: { since } });
      toast(`انجام شد: ${fa(r.created || 0)} فروش جدید`);
      reload();
    }
    if (act === "import") {
      const items = [...view.querySelectorAll("input[data-imp]:checked")].map((c) => {
        const [woo_id, variation_id] = c.dataset.imp.split(":");
        return { woo_id: Number(woo_id), variation_id: variation_id ? Number(variation_id) : null };
      });
      if (!items.length) return toast("محصولی انتخاب نشده", "error");
      const r = await api("/api/erp/woo/import-products", { method: "POST", body: { items } });
      toast(`${fa(r.created)} محصول ساخته شد؛ قیمت خرید و موجودی را کامل کنید`);
      reload();
    }
  });
  delegate(view, "change", "[data-imp-parent]", (e, el) => {
    view.querySelectorAll(`input[data-imp^="${el.dataset.impParent}:"]`).forEach((c) => { c.checked = false; c.disabled = el.checked; });
  });
  let timer;
  const off = on("live:erp", (ev) => { if (ev.type === "product" && ev.woo_state) { clearTimeout(timer); timer = setTimeout(reload, 1500); } });
  return () => { off(); clearTimeout(timer); };
}

const sure = (s) => s.candidates[0] && s.candidates[0].score >= 0.8 && (!s.candidates[1] || s.candidates[0].score - s.candidates[1].score >= 0.08);

function page(st, cat, tab) {
  const s = st.settings, c = st.counts || {};
  const configured = st.configured;
  return html`<div class="stack">
    <section class="hero">
      <span class="blob-deco" style="width:220px;height:220px;left:-60px;top:-80px"></span>
      <div class="row between" style="align-items:flex-start">
        <div><h1>${icon("globe")} ${configured ? "سایت وصل است" : "سایت هنوز وصل نشده"}</h1>
          <p class="muted small">${configured
            ? html`سفارش‌های سایت هر ${fa(s.pull_minutes || 3)} دقیقه (و با وب‌هوک فوری) خوانده می‌شوند${s.last_order_sync ? `، آخرین بررسی ${jdate(s.last_order_sync.slice(0, 10), { year: false })} ${timeOf(s.last_order_sync)}` : ""}`
            : "کلیدهای API ووکامرس را وارد کنید (پایین صفحه، مرحله ۱)."}</p></div>
        <label class="check bold"><span class="switch"><input type="checkbox" id="auto-push" ${s.auto_push ? "checked" : ""} ${configured ? "" : "disabled"}><span></span></span>
          همگام‌سازی خودکار موجودی</label>
      </div>
      <div class="grid g4 mt16" style="gap:12px">
        <div class="inset"><div class="small muted">وصل‌شده</div><div class="bold num">${fa(c.linked || 0)} از ${fa(c.products || 0)}</div></div>
        <div class="inset"><div class="small muted">در صف ارسال</div><div class="bold num">${fa(c.pending || 0)}</div></div>
        <div class="inset"><div class="small muted">خطا</div><div class="bold num ${c.errors ? "bad-ink" : ""}">${fa(c.errors || 0)}</div></div>
        <div class="inset"><div class="small muted">موجودی ناهماهنگ</div><div class="bold num ${c.mismatched ? "warn-ink" : ""}">${fa(c.mismatched || 0)}</div></div>
      </div>
      ${configured ? html`<div class="row mt16">
        <button class="btn sm soft" data-act="push-all">${icon("cloud-upload", "sm")} ارسال همه موجودی‌ها به سایت</button>
        <button class="btn sm ghost" data-act="pull">${icon("refresh-cw", "sm")} خواندن سفارش‌های جدید</button></div>` : ""}
    </section>

    <section class="card">
      <div class="card-head"><h2>${icon("link")} اتصال محصولات</h2><span class="spacer"></span>
        <span class="small muted">${cat.fetched_at ? `محصولات سایت: ${jdate(cat.fetched_at.slice(0, 10), { year: false })} ${timeOf(cat.fetched_at)}${cat.source === "public" ? " (بدون کلید)" : ""}` : ""}</span>
        <button class="btn sm soft" data-act="catalog">${icon("refresh-cw", "sm")} خواندن محصولات سایت</button>
        <p>هر محصول انبار را به همان محصول (یا همان رنگ) در سایت وصل کنید تا موجودی‌اش خودکار در سایت تنظیم شود.</p></div>
      ${!cat.items?.length ? emptyState("globe", "محصولات سایت هنوز خوانده نشده", "دکمه «خواندن محصولات سایت» را بزنید. بدون کلید هم کار می‌کند، اما عدد موجودی سایت را فقط با کلید API می‌بینید.")
        : html`<div class="tabs">
            <button class="chip ${tab === "suggest" ? "on" : ""}" data-tab="suggest">وصل نشده <span class="c-count">${fa(cat.suggestions.length)}</span></button>
            <button class="chip ${tab === "linked" ? "on" : ""}" data-tab="linked">وصل‌شده <span class="c-count">${fa(cat.linked.length)}</span></button>
            <button class="chip ${tab === "site" ? "on" : ""}" data-tab="site">فقط در سایت <span class="c-count">${fa(cat.unlinked_site.length)}</span></button>
          </div>
          ${tab === "suggest" ? suggestTab(cat) : tab === "linked" ? linkedTab(cat) : siteTab(cat)}`}
    </section>

    <div class="grid g2">
      <section class="card">
        <div class="card-head"><h2>${icon("key-round")} راه‌اندازی</h2></div>
        <div class="steps">
          <div class="step ${s.key ? "done" : ""}"><div class="s-body"><b>ساخت کلید API در ووکامرس</b>
            <p class="small muted">پیشخوان وردپرس ← ووکامرس ← پیکربندی ← پیشرفته ← REST API ← «افزودن کلید». دسترسی را <b>خواندن/نوشتن</b> بگذارید و کلید و رمز را اینجا بچسبانید.</p>
            <form id="keys" class="stack s8 mt12" autocomplete="off">
              <input class="input sm ltr" name="url" value="${s.url || ""}" placeholder="https://aikocosmetics.ir">
              <input class="input sm ltr" name="key" value="${s.key || ""}" placeholder="ck_…">
              <input class="input sm ltr" name="secret" type="password" placeholder="${s.secret_set ? "رمز ذخیره شده (برای تغییر، رمز جدید را بنویسید)" : "cs_…"}">
              <div class="row"><label class="check small"><input type="checkbox" name="query_auth" ${s.query_auth ? "checked" : ""}> ارسال کلید در آدرس (اگر خطای ۴۰۱ گرفتید)</label>
                <label class="small row nowrap">هر <input class="input sm" name="pull_minutes" value="${fa(s.pull_minutes || 3)}" style="width:56px" inputmode="numeric"> دقیقه بررسی سفارش‌ها</label></div>
              <button class="btn sm primary" type="submit">${icon("check", "sm")} ذخیره و آزمایش اتصال</button>
            </form></div></div>
          <div class="step"><div class="s-body"><b>وب‌هوک برای ثبت فوری سفارش‌های سایت</b>
            <p class="small muted">ووکامرس ← پیکربندی ← پیشرفته ← وب‌هوک‌ها ← «افزودن». دو وب‌هوک بسازید با موضوع «سفارش ایجاد شد» و «سفارش به‌روز شد»، وضعیت فعال، نسخه API: WP REST API v3.</p>
            <div class="inset small stack s8 mt8">
              <div class="row nowrap"><span class="muted">آدرس تحویل:</span><code class="ltr ellipsis" style="flex:1">${st.webhook_url}</code>
                <button class="btn xs ghost" data-copy="${st.webhook_url}">${icon("copy", "sm")}</button></div>
              <div class="row nowrap"><span class="muted">رمز (Secret):</span><code class="ltr ellipsis" style="flex:1">${s.webhook_secret || "اول کلیدها را ذخیره کنید"}</code>
                ${s.webhook_secret ? html`<button class="btn xs ghost" data-copy="${s.webhook_secret}">${icon("copy", "sm")}</button>` : ""}</div>
            </div>
            <p class="tiny muted mt8">بدون وب‌هوک هم سفارش‌ها هر چند دقیقه خوانده می‌شوند؛ وب‌هوک فقط فوری‌ترش می‌کند. آدرس باید از اینترنت در دسترس باشد (روی سرور).</p></div></div>
          <div class="step ${c.linked ? "done" : ""}"><div class="s-body"><b>وصل کردن محصولات</b><p class="small muted">از بخش بالا. محصولاتی که چند رنگ دارند را می‌توانید کلی وصل کنید یا از صفحه محصول «تفکیک به رنگ‌ها» بزنید.</p></div></div>
          <div class="step ${s.auto_push ? "done" : ""}"><div class="s-body"><b>روشن کردن همگام‌سازی خودکار</b><p class="small muted">بعد از اینکه موجودی‌ها را چک کردید، کلید بالای صفحه را روشن کنید. از آن به بعد هر فروش (از هر کانالی) همان لحظه موجودی سایت را تنظیم می‌کند و محصول تمام‌شده در سایت «ناموجود» می‌شود.</p></div></div>
        </div>
        ${configured ? html`<div class="divider"></div>
          <h3>${icon("history", "sm")} خواندن سفارش‌های گذشته</h3>
          <p class="small muted">فقط اگر سفارش‌های سایت را قبلاً جایی ثبت نکرده‌اید (وگرنه تکراری می‌شوند).</p>
          <div class="row mt8" style="align-items:flex-end"><div style="flex:1">${dateField({ name: "since", label: "از تاریخ", value: erp.me.today })}</div>
            <button class="btn sm soft" data-act="backfill">${icon("download", "sm")} بخوان</button></div>` : ""}
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("list")} گزارش همگام‌سازی</h2></div>
        ${st.log.length ? html`<div class="list">${st.log.map((l) => html`<div class="list-item">
          <span class="badge ${l.ok ? "ok" : "bad"}">${icon(l.ok ? "check" : "x")}</span>
          <div class="grow"><div class="small">${l.detail}</div><div class="tiny muted">${l.action}، ${jdate(l.created_at.slice(0, 10), { year: false })} ${timeOf(l.created_at)}</div></div></div>`)}</div>`
          : emptyState("list", "هنوز رویدادی نیست")}
      </section>
    </div>
  </div>`;
}

function catalogOptions(cat) {
  const used = new Set(cat.linked.map((p) => `${p.woo_id}:${p.woo_variation_id || ""}`));
  const parents = cat.items.filter((e) => !e.variation_id);
  return html`<option value="">انتخاب دستی از سایت…</option>${parents.map((p) => {
    const vars = cat.items.filter((e) => e.woo_id === p.woo_id && e.variation_id);
    return html`<optgroup label="${p.name}">
      <option value="${p.woo_id}:" ${used.has(`${p.woo_id}:`) ? "disabled" : ""}>${p.name}${vars.length ? " (همه رنگ‌ها با هم)" : ""}</option>
      ${vars.map((v) => html`<option value="${v.woo_id}:${v.variation_id}" ${used.has(`${v.woo_id}:${v.variation_id}`) ? "disabled" : ""}>— ${v.variation_label || v.name}</option>`)}
    </optgroup>`;
  })}`;
}

function suggestTab(cat) {
  if (!cat.suggestions.length) return emptyState("circle-check", "همه محصولات انبار وصل شده‌اند");
  const nSure = cat.suggestions.filter(sure).length;
  const options = catalogOptions(cat);
  return html`${nSure ? html`<div class="callout ok" style="margin-bottom:14px">${icon("sparkles")}<div style="flex:1">${fa(nSure)} پیشنهاد با اطمینان بالا پیدا شد.</div>
      <button class="btn sm primary" data-act="link-sure">تأیید همه</button></div>` : ""}
    <div class="list">${cat.suggestions.map((s) => html`<div class="list-item" style="align-items:flex-start;flex-wrap:wrap">
      <div class="row nowrap" style="flex:1;min-width:240px">${thumb(s.product, "sm")}<div><div class="title small">${s.product.name}</div>
        <div class="sub">موجودی ${fa(s.product.stock)}، ${num(s.product.price)} تومان</div></div></div>
      <div class="stack s8" style="flex:1.4;min-width:260px">
        ${s.candidates.map((c, i) => html`<div class="row nowrap">
          <span class="badge ${c.score >= 0.8 ? "ok" : c.score >= 0.55 ? "warn" : ""}">${fa(Math.round(c.score * 100))}٪</span>
          <span class="small grow ellipsis" style="flex:1" title="${c.name}">${c.name}</span>
          <span class="tiny muted nowrap">${num(c.price)}</span>
          <button class="btn xs ${i === 0 && sure(s) ? "primary" : "soft"}" data-act="link" data-pid="${s.product.id}" data-woo="${c.woo_id}" data-var="${c.variation_id || ""}">وصل</button>
        </div>`)}
        <div class="row nowrap"><select class="select sm" data-manual="${s.product.id}" style="flex:1">${options}</select>
          <button class="btn xs soft" data-act="link-select" data-pid="${s.product.id}">وصل</button></div>
      </div>
    </div>`)}</div>`;
}

function linkedTab(cat) {
  if (!cat.linked.length) return emptyState("link", "هنوز محصولی وصل نشده");
  return html`<div class="table-wrap"><table class="t responsive">
    <thead><tr><th>محصول انبار</th><th>در سایت</th><th class="n">اینجا</th><th class="n">سایت</th><th>وضعیت</th><th></th></tr></thead>
    <tbody>${cat.linked.map((p) => {
      const mismatch = p.woo_stock !== null && p.woo_stock !== undefined && p.woo_stock !== Math.max(0, p.stock);
      return html`<tr>
        <td class="m-full"><div class="prod-cell">${thumb(p, "sm")}<a class="small" href="#/erp/products/${p.id}">${p.name}</a></div></td>
        <td class="small muted m-full">${p.woo_url ? html`<a href="${p.woo_url}" target="_blank" rel="noopener">${p.woo_name || "صفحه محصول"}</a>` : p.woo_name || ""}</td>
        <td class="n bold" data-l="اینجا:">${fa(p.stock)}</td>
        <td class="n ${mismatch ? "warn-ink bold" : ""}" data-l="سایت:">${p.woo_stock === null || p.woo_stock === undefined ? "؟" : fa(p.woo_stock)}</td>
        <td>${wooBadge(p)}${p.woo_error ? html`<div class="tiny bad-ink">${p.woo_error}</div>` : ""}</td>
        <td class="n m-full nowrap">
          <button class="btn xs soft" data-act="push" data-pid="${p.id}" title="موجودی اینجا را روی سایت بگذار">${icon("cloud-upload", "sm")}</button>
          ${mismatch ? html`<button class="btn xs ghost" data-act="use-site" data-pid="${p.id}" title="موجودی سایت درست است">${icon("download", "sm")}</button>` : ""}
          <button class="btn xs ghost" data-act="unlink" data-pid="${p.id}" title="قطع اتصال">${icon("unlink", "sm")}</button></td>
      </tr>`;
    })}</tbody></table></div>`;
}

function siteTab(cat) {
  const items = cat.unlinked_site;
  if (!items.length) return emptyState("circle-check", "همه محصولات سایت در انبار هستند");
  const parents = items.filter((e) => !e.variation_id);
  const orphans = items.filter((e) => e.variation_id && !parents.some((p) => p.woo_id === e.woo_id));
  return html`<div class="callout" style="margin-bottom:14px">${icon("info")}<div>این محصولات در سایت هستند ولی در انبار نه (مثلاً کالاهای جدید).
      انتخاب کنید تا ساخته شوند؛ برای محصولات چندرنگ یا «کل محصول» را بزنید یا رنگ‌ها را جدا.</div></div>
    <div class="list">${[...parents, ...orphans].map((p) => {
      const vars = p.variation_id ? [] : items.filter((e) => e.woo_id === p.woo_id && e.variation_id);
      return html`<div class="list-item" style="align-items:flex-start">
        <input type="checkbox" ${p.variation_id ? html`data-imp="${p.woo_id}:${p.variation_id}"` : html`data-imp="${p.woo_id}:" data-imp-parent="${p.woo_id}"`} style="margin-top:12px;width:18px;height:18px">
        ${thumb(p, "sm")}
        <div class="grow"><div class="title small">${p.name}${vars.length ? html` <span class="badge">کل محصول</span>` : ""}</div>
          <div class="sub">${num(p.price)} تومان${p.stock !== null && p.stock !== undefined ? `، موجودی سایت ${fa(p.stock)}` : ""}</div>
          ${vars.length ? html`<div class="chips mt8">${vars.map((v) => html`<label class="chip" style="height:30px;cursor:pointer">
            <input type="checkbox" data-imp="${v.woo_id}:${v.variation_id}"> ${v.variation_label}</label>`)}</div>` : ""}
        </div></div>`;
    })}</div>
    <div class="row mt16"><button class="btn primary" data-act="import">${icon("package-plus")} ساخت محصولات انتخاب‌شده در انبار</button></div>`;
}
