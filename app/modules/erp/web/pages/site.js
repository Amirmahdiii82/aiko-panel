// Website sync: one full sync (every site product and every order since the shop opened, exact figures), what still
// needs a person (duplicates to merge, hand-typed website sales with no site order, sold items without a cost),
// linked products and stock, webhook and log. The site address and keys live in Settings → Connections.
import { $, api, confirmBox, delegate, fa, html, icon, isOwner, jdate, num, on, timeOf, toast } from "/static/js/kit.js";
import { copyText, emptyState, thumb } from "/static/js/kit.js";
import { refreshMe, wooBadge } from "../erp.js";

const STEPS = { catalog: "خواندن همه محصولات و رنگ‌ها از سایت…", orders: "خواندن همه سفارش‌های سایت…", apply: "ثبت فروش‌ها و هماهنگ کردن با داده‌های اکسل…" };
const when = (ts) => (ts ? `${jdate(ts.slice(0, 10), { year: false })} ${timeOf(ts)}` : "");

export async function render(view, params, { setTitle }) {
  setTitle("اتصال سایت", "همه محصولات و فروش‌های سایت، دقیق و خودکار");
  let st = await api("/api/erp/woo");
  let cat = await api("/api/erp/woo/catalog");
  let tab = "review";

  const draw = () => { view.innerHTML = String(page(st, cat, tab)); };
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
  delegate(view, "submit", "#opts", async (e) => {
    e.preventDefault();
    await api("/api/erp/woo", { method: "PUT", body: { pull_minutes: Number(String(e.target.pull_minutes.value).replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d))) || 3 } });
    toast("ذخیره شد");
    reload();
  });
  delegate(view, "click", "[data-act]", async (e, el) => {
    const act = el.dataset.act;
    if (act === "full-sync") {
      if (!(await confirmBox("همه محصولات و همه سفارش‌های سایت از اول خوانده می‌شوند. فروش‌های سایت که دستی یا از اکسل ثبت شده‌اند با سفارش دقیق سایت جایگزین می‌شوند (قیمت خرید اکسل حفظ می‌شود). فروش‌های حضوری/اینستاگرام، خریدها و هزینه‌ها دست نمی‌خورند. قبلش خودکار پشتیبان گرفته می‌شود. شروع شود؟", { okText: "شروع" }))) return;
      await api("/api/erp/woo/full-sync", { method: "POST" });
      toast("شروع شد؛ چند دقیقه طول می‌کشد", "info");
      reload();
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
    if (act === "merge") {
      if (!(await confirmBox(`«${el.dataset.name}» با «${el.dataset.intoName}» یکی شود؟ همه فروش‌ها، خریدها و موجودی آن به محصول سایت منتقل می‌شود.`, { okText: "ادغام" }))) return;
      await api(`/api/erp/products/${el.dataset.pid}/merge`, { method: "POST", body: { into: Number(el.dataset.into) } });
      toast("ادغام شد");
      reload();
    }
    if (act === "unlink") { await api("/api/erp/woo/unlink", { method: "POST", body: { product_id: Number(el.dataset.pid) } }); reload(); }
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
  });
  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "site_sync" || (ev.type === "product" && ev.woo_state)) { clearTimeout(timer); timer = setTimeout(reload, 1200); }
  });
  return () => { off(); clearTimeout(timer); };
}

function page(st, cat, tab) {
  const s = st.settings, c = st.counts || {}, fs = st.full_sync || {}, rv = st.review || {};
  const configured = st.configured;
  const nReview = (rv.duplicates?.length || 0) + (rv.unmatched_web_sales?.length || 0) + (cat.suggestions?.length || 0);
  return html`<div class="stack">
    <section class="hero">
      <span class="blob-deco" style="width:220px;height:220px;left:-60px;top:-80px"></span>
      <div class="row between" style="align-items:flex-start">
        <div><h1>${icon("globe")} ${configured ? "سایت وصل است" : "سایت هنوز وصل نشده"}</h1>
          <p class="muted small">${configured
            ? html`<span class="ltr">${s.url}</span> — سفارش‌های جدید فوری (وب‌هوک) و هر ${fa(s.pull_minutes || 3)} دقیقه خوانده می‌شوند${s.last_order_sync ? `، آخرین بررسی ${when(s.last_order_sync)}` : ""}`
            : html`آدرس و کلید ووکامرس را ${isOwner() ? html`در <a href="#/settings/connections">تنظیمات ← اتصال‌ها</a>` : "از مدیر کل بخواهید"} وارد کنید (برای فروشگاه و قیمت رقبا با هم).`}</p></div>
        <label class="check bold"><span class="switch"><input type="checkbox" id="auto-push" ${s.auto_push ? "checked" : ""} ${configured ? "" : "disabled"}><span></span></span>
          همگام‌سازی خودکار موجودی</label>
      </div>
      <div class="grid g4 mt16" style="gap:12px">
        <div class="inset"><div class="small muted">محصولات وصل به سایت</div><div class="bold num">${fa(c.linked || 0)} از ${fa(c.products || 0)}</div></div>
        <div class="inset"><div class="small muted">فروش‌های سایت</div><div class="bold num">${fa(st.sales?.site || 0)}</div></div>
        <div class="inset"><div class="small muted">خطای ارسال</div><div class="bold num ${c.errors ? "bad-ink" : ""}">${fa(c.errors || 0)}</div></div>
        <div class="inset"><div class="small muted">موجودی ناهماهنگ</div><div class="bold num ${c.mismatched ? "warn-ink" : ""}">${fa(c.mismatched || 0)}</div></div>
      </div>
    </section>

    <section class="card">
      <div class="card-head"><h2>${icon("refresh-cw")} همگام‌سازی کامل با سایت</h2><span class="spacer"></span>
        <button class="btn primary" data-act="full-sync" ${configured && !fs.running ? "" : "disabled"}>${fs.running ? html`<span class="spin"></span> در حال انجام` : html`${icon("refresh-cw", "sm")} همگام‌سازی کامل`}</button>
        <p>همه محصولات و رنگ‌های سایت در انبار ساخته یا وصل می‌شوند (بدون انتخاب دستی رنگ‌ها) و همه سفارش‌های سایت از اول با مبلغ دقیق ثبت می‌شوند: قیمت هر ردیف، کد تخفیف، هزینه ارسال، کارمزد و مبلغ برگشتی.
          فروش سایتی که قبلاً دستی یا از اکسل ثبت شده با سفارش سایت جایگزین می‌شود و قیمت خرید اکسل حفظ می‌شود. فروش‌های بیرون از سایت، خریدها و هزینه‌ها از اکسل/پنل می‌مانند. هر شب ساعت ۴:۳۰ هم خودکار اجرا می‌شود.</p></div>
      ${fs.running ? html`<div class="callout">${icon("loader-circle")}<div>${STEPS[fs.step] || "در حال انجام…"}${fs.orders ? ` (${fa(fs.orders)} سفارش)` : ""}</div></div>` : ""}
      ${!fs.running && fs.error ? html`<div class="callout bad">${icon("triangle-alert")}<div>${fs.error}</div></div>` : ""}
      ${!fs.running && fs.report ? report(fs) : ""}
    </section>

    <section class="card">
      <div class="tabs">
        <button class="chip ${tab === "review" ? "on" : ""}" data-tab="review">نیاز به بررسی <span class="c-count">${fa(nReview)}</span></button>
        <button class="chip ${tab === "linked" ? "on" : ""}" data-tab="linked">محصولات وصل‌شده <span class="c-count">${fa(cat.linked?.length || 0)}</span></button>
      </div>
      ${tab === "review" ? reviewTab(rv, cat) : linkedTab(cat)}
      ${configured && tab === "linked" ? html`<div class="row mt16">
        <button class="btn sm soft" data-act="push-all">${icon("cloud-upload", "sm")} ارسال همه موجودی‌ها به سایت</button>
        <button class="btn sm ghost" data-act="pull">${icon("refresh-cw", "sm")} خواندن سفارش‌های جدید</button></div>` : ""}
    </section>

    <div class="grid g2">
      <section class="card">
        <div class="card-head"><h2>${icon("zap")} وب‌هوک (ثبت فوری سفارش‌ها)</h2></div>
        <p class="small muted">ووکامرس ← پیکربندی ← پیشرفته ← وب‌هوک‌ها ← «افزودن». دو وب‌هوک با موضوع «سفارش ایجاد شد» و «سفارش به‌روز شد»، وضعیت فعال، نسخه API: WP REST API v3.</p>
        <div class="inset small stack s8 mt8">
          <div class="row nowrap"><span class="muted">آدرس تحویل:</span><code class="ltr ellipsis" style="flex:1">${st.webhook_url}</code>
            <button class="btn xs ghost" data-copy="${st.webhook_url}">${icon("copy", "sm")}</button></div>
          <div class="row nowrap"><span class="muted">رمز (Secret):</span><code class="ltr ellipsis" style="flex:1">${s.webhook_secret || "بعد از وصل شدن سایت ساخته می‌شود"}</code>
            ${s.webhook_secret ? html`<button class="btn xs ghost" data-copy="${s.webhook_secret}">${icon("copy", "sm")}</button>` : ""}</div>
        </div>
        <form id="opts" class="row mt12"><label class="small row nowrap">بدون وب‌هوک هم هر <input class="input sm" name="pull_minutes" value="${fa(s.pull_minutes || 3)}" style="width:56px" inputmode="numeric"> دقیقه سفارش‌ها بررسی شوند</label>
          <button class="btn xs soft" type="submit">ذخیره</button></form>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("list")} گزارش همگام‌سازی</h2></div>
        ${st.log.length ? html`<div class="list">${st.log.map((l) => html`<div class="list-item">
          <span class="badge ${l.ok ? "ok" : "bad"}">${icon(l.ok ? "check" : "x")}</span>
          <div class="grow"><div class="small">${l.detail}</div><div class="tiny muted">${l.action}، ${when(l.created_at)}</div></div></div>`)}</div>`
          : emptyState("list", "هنوز رویدادی نیست")}
      </section>
    </div>
  </div>`;
}

function report(fs) {
  const r = fs.report;
  return html`<div class="grid g4" style="gap:12px">
      <div class="inset"><div class="small muted">فروش سایت ثبت شد</div><div class="bold num">${fa(r.sales_created)}</div></div>
      <div class="inset"><div class="small muted">جایگزین فروش دستی/اکسل</div><div class="bold num">${fa(r.sales_replaced)}</div></div>
      <div class="inset"><div class="small muted">محصول ساخته شد</div><div class="bold num">${fa(r.products_created)}</div></div>
      <div class="inset"><div class="small muted">محصول وصل شد</div><div class="bold num">${fa(r.linked)}</div></div>
    </div>
    <p class="tiny muted mt8">${fa(r.orders)} سفارش بررسی شد، ${fa(r.sales_updated)} به‌روز، ${fa(r.sales_voided)} لغو — ${when(fs.finished_at)} (${fs.by || ""})</p>`;
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

function reviewTab(rv, cat) {
  const dups = rv.duplicates || [], web = rv.unmatched_web_sales || [], mc = rv.missing_cost || {};
  const loose = (cat.suggestions || []).filter((s) => !dups.some((d) => d.product.id === s.product.id));
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

    ${loose.length ? html`<div><h3>${icon("link", "sm")} محصولات انبار که در سایت نیستند</h3>
      <p class="small muted">اگر در سایت هستند، محصول سایت را انتخاب کنید؛ اگر فقط حضوری/اینستاگرام فروخته می‌شوند، کاری لازم نیست.</p>
      <div class="list mt8">${loose.map((s) => html`<div class="list-item" style="flex-wrap:wrap">
        <div class="row nowrap" style="flex:1;min-width:220px">${thumb(s.product, "sm")}<div><div class="title small">${s.product.name}</div>
          <div class="sub">موجودی ${fa(s.product.stock)}</div></div></div>
        <div class="row nowrap" style="flex:1.4;min-width:260px"><select class="select sm" data-manual="${s.product.id}" style="flex:1">${catalogOptions(cat)}</select>
          <button class="btn xs soft" data-act="link-select" data-pid="${s.product.id}">وصل</button></div>
      </div>`)}</div></div>` : ""}
  </div>`;
}

function linkedTab(cat) {
  if (!cat.linked?.length) return emptyState("link", "هنوز محصولی وصل نشده", "«همگام‌سازی کامل» را بزنید.");
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
