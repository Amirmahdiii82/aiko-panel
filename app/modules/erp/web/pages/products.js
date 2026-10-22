// Products & stock: list, filters, quick "out of stock", adjustments, product drawer with history and site link.
import { $, api, compact, confirmBox, delegate, esc, fa, html, icon, jdate, num, on, parseNum, pct, sheet, timeOf, toast } from "/static/js/kit.js";
import { bindMoney, emptyState, formData, moneyField, selectOptions, thumb } from "/static/js/kit.js";
import { erp, isAdmin, refreshMe, stockBadge, WOO_STATE, wooBadge } from "../erp.js";

const FILTERS = [
  { key: "all", label: "همه" },
  { key: "low", label: "رو به اتمام", test: (p) => p.stock > 0 && p.stock <= p.low_stock },
  { key: "out", label: "ناموجود", test: (p) => p.stock <= 0 },
  { key: "unlinked", label: "وصل نشده به سایت", test: (p) => !p.woo_id, admin: true },
  { key: "error", label: "خطای سایت", test: (p) => p.woo_state === "error", admin: true },
  { key: "nocost", label: "بدون قیمت خرید", test: (p) => !p.avg_cost && (p.stock > 0 || p.sold_total > 0), admin: true },
  { key: "archived", label: "بایگانی", admin: true },
];
const MOVE_LABEL = { opening: "موجودی اولیه", purchase: "خرید", sale: "فروش", sale_void: "برگشت فروش", adjust: "اصلاح دستی",
  split: "تفکیک رنگ", purchase_void: "ابطال خرید", site_sync: "تغییر در سایت" };
const norm = (s) => String(s || "").replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ").toLowerCase();

export async function render(view, params, { setTitle, query }) {
  const admin = isAdmin();
  setTitle(admin ? "محصولات و انبار" : "موجودی محصولات", admin ? "موجودی اینجا مرجع است و به سایت فرستاده می‌شود" : "");
  let filter = query.get("f") || "all", q = "", cat = "";
  let products = [];
  const load = async () => {
    products = await api(`/api/erp/products${filter === "archived" ? "?include_inactive=true" : ""}`, { quiet: true });
  };
  await load();

  view.innerHTML = String(html`<div class="stack">
    <div class="card tight">
      <div class="row">
        <div class="input-wrap" style="flex:1;min-width:220px">${icon("search")}<input enterkeyhint="search" class="input" id="q" placeholder="جستجو در نام، برند، کد…"></div>
        <select class="select" id="cat" style="width:auto;min-width:150px"></select>
        ${admin ? html`<button class="btn primary" id="new">${icon("plus")} محصول جدید</button>` : ""}
      </div>
      <div class="chips scroll mt12" id="filters"></div>
    </div>
    <section class="card" id="list"></section>
  </div>`);

  function counts() {
    const c = {};
    FILTERS.forEach((f) => { c[f.key] = f.test ? products.filter((p) => p.active && f.test(p)).length : null; });
    c.all = products.filter((p) => p.active).length;
    return c;
  }
  function visible() {
    const f = FILTERS.find((x) => x.key === filter) || FILTERS[0];
    const terms = norm(q).split(/\s+/).filter(Boolean);
    return products
      .filter((p) => filter === "archived" ? !p.active : p.active)
      .filter((p) => !f.test || f.test(p))
      .filter((p) => !cat || p.category === cat)
      .filter((p) => !terms.length || terms.every((t) => norm(`${p.name} ${p.brand || ""} ${p.sku || ""}`).includes(t)));
  }
  function drawFilters() {
    const c = counts();
    $("#filters", view).innerHTML = String(html`${FILTERS.filter((f) => admin || !f.admin).map((f) => html`<button class="chip ${filter === f.key ? "on" : ""} ${f.key === "out" ? "coral" : ""}" data-f="${f.key}">
      ${f.label}${c[f.key] !== null && c[f.key] !== undefined ? html` <span class="c-count">${fa(c[f.key])}</span>` : ""}</button>`)}`);
    const cats = [...new Set(products.map((p) => p.category).filter(Boolean))].sort();
    $("#cat", view).innerHTML = String(selectOptions(cats.map((c2) => ({ value: c2, label: c2 })), cat, "همه دسته‌ها"));
  }
  function drawList() {
    const list = visible();
    const el = $("#list", view);
    if (!list.length) {
      el.innerHTML = String(emptyState("package", "محصولی نیست", filter !== "all" ? "فیلتر را عوض کنید." : ""));
      return;
    }
    const totalUnits = list.reduce((s, p) => s + Math.max(0, p.stock), 0);
    const totalValue = list.reduce((s, p) => s + Math.max(0, p.stock) * (p.avg_cost || 0), 0);
    el.innerHTML = String(html`
      <div class="card-head"><h3>${fa(list.length)} محصول</h3><span class="muted small">، ${fa(totalUnits)} عدد${admin ? html`، ارزش خرید ${compact(totalValue)} تومان` : ""}</span></div>
      <div class="table-wrap"><table class="t responsive">
        <thead><tr><th>محصول</th><th class="n">قیمت فروش</th>${admin ? html`<th class="n">قیمت خرید</th><th class="n">سود</th>` : ""}
          <th>موجودی</th>${admin ? html`<th class="n">فروش ۳۰ روز</th><th>سایت</th><th></th>` : ""}</tr></thead>
        <tbody>${list.map((p) => {
          const margin = p.price ? (p.price - p.avg_cost) / p.price : 0;
          return html`<tr class="clickable" data-open="${p.id}">
            <td class="m-full"><div class="prod-cell">${thumb(p)}<div style="min-width:0"><div class="name">${p.name}</div>
              <div class="meta">${[p.sku, p.brand, p.category].filter(Boolean).join("، ")}</div></div></div></td>
            <td class="n" data-l="قیمت:">${num(p.price)}</td>
            ${admin ? html`<td class="n m-hide">${num(p.avg_cost)}</td>
              <td class="n m-hide"><span class="${margin < 0.15 ? "warn-ink" : ""}">${p.avg_cost ? pct(margin) : "—"}</span></td>` : ""}
            <td>${stockBadge(p)}</td>
            ${admin ? html`<td class="n m-hide">${fa(p.sold_30 || 0)}</td><td>${wooBadge(p)}</td>
              <td class="n m-full" style="white-space:nowrap">
                ${p.stock > 0 && p.active ? html`<button class="btn xs danger" data-out="${p.id}" title="موجودی را صفر کن">${icon("ban", "sm")} ناموجود</button>` : ""}
                <button class="btn xs soft" data-adjust="${p.id}">${icon("pencil", "sm")} موجودی</button></td>` : ""}
          </tr>`;
        })}</tbody>
      </table></div>`);
  }
  const redraw = () => { drawFilters(); drawList(); };
  redraw();

  $("#q", view).addEventListener("input", (e) => { q = e.target.value; drawList(); });
  $("#cat", view).addEventListener("change", (e) => { cat = e.target.value; drawList(); });
  delegate(view, "click", "[data-f]", async (e, el) => {
    const prev = filter;
    filter = el.dataset.f;
    if ((prev === "archived") !== (filter === "archived")) await load();
    redraw();
  });
  delegate(view, "click", "[data-out]", async (e, el) => {
    e.stopPropagation();
    const p = products.find((x) => x.id === Number(el.dataset.out));
    if (!(await confirmBox(`موجودی «${p.name}» صفر شود؟ ${p.woo_id ? "در سایت هم ناموجود می‌شود." : ""}`, { okText: "ناموجود کن", danger: true }))) return;
    await api(`/api/erp/products/${p.id}/adjust`, { method: "POST", body: { set_to: 0, reason: "ناموجود کردن سریع" } });
    toast(`«${p.name}» ناموجود شد`);
    await load(); redraw();
  });
  delegate(view, "click", "[data-adjust]", (e, el) => {
    e.stopPropagation();
    openAdjust(products.find((x) => x.id === Number(el.dataset.adjust)), async () => { await load(); redraw(); });
  });
  delegate(view, "click", "[data-open]", (e, el) => { location.hash = `#/erp/products/${el.dataset.open}`; });
  $("#new", view)?.addEventListener("click", () => openProductForm(null, async (id) => { await load(); redraw(); location.hash = `#/erp/products/${id}`; }));

  let drawer = null;
  const openFromParams = (p) => {
    if (drawer) { drawer.close(); drawer = null; }
    if (p[0]) drawer = openProduct(Number(p[0]), async () => { await load(); redraw(); });
  };
  openFromParams(params);

  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "product") {
      const p = products.find((x) => x.id === ev.id);
      if (p) {
        if (ev.stock !== undefined) p.stock = ev.stock;
        if (ev.woo_state) p.woo_state = ev.woo_state;
        clearTimeout(timer);
        timer = setTimeout(redraw, 300);
      }
    }
    if (ev.type === "refresh" && (ev.scope === "products" || ev.scope === "purchases")) {
      clearTimeout(timer);
      timer = setTimeout(async () => { await load(); redraw(); }, 600);
    }
  });
  return { cleanup: () => { off(); drawer && drawer.close(); }, onParams: openFromParams };
}

// ---------------------------------------------------------------- dialogs

export function openAdjust(p, done) {
  const s = sheet({
    title: `اصلاح موجودی «${p.name}»`,
    body: html`<div class="stack s12">
      <div class="inset row between"><span>موجودی فعلی</span><b class="num" style="font-size:20px">${fa(p.stock)}</b></div>
      <div class="field"><label>موجودی درست (شمارش واقعی)</label>
        <div class="row nowrap"><div class="stepper"><button type="button" data-d="1">${icon("plus", "sm")}</button>
          <input name="set_to" value="${fa(p.stock)}" inputmode="numeric" style="width:64px;font-size:18px">
          <button type="button" data-d="-1">${icon("minus", "sm")}</button></div>
          <button class="btn sm danger" type="button" data-zero>${icon("ban", "sm")} صفر (ناموجود)</button></div></div>
      <div class="field"><label>دلیل</label>
        <div class="chips" id="reasons">${["شمارش انبار", "فروش خارج از سیستم", "خراب / تاریخ گذشته", "هدیه / تستر", "پیدا شد"].map((r) =>
          html`<button type="button" class="chip" data-r="${r}">${r}</button>`)}</div>
        <input class="input mt8" name="reason" placeholder="یا دلیل را بنویسید"></div>
      ${p.woo_id ? html`<div class="callout">${icon("globe")}<div>این محصول به سایت وصل است؛ موجودی جدید به سایت هم فرستاده می‌شود.</div></div>` : ""}
    </div>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ثبت</button><button class="btn ghost" data-close>انصراف</button>`,
  });
  const input = s.root.querySelector("[name=set_to]");
  delegate(s.root, "click", "[data-d]", (e, b) => { input.value = fa(Math.max(0, Math.round(parseNum(input.value)) + Number(b.dataset.d))); });
  s.root.querySelector("[data-zero]").onclick = () => { input.value = fa(0); };
  delegate(s.root, "click", "[data-r]", (e, b) => {
    s.root.querySelectorAll("[data-r]").forEach((c) => c.classList.toggle("on", c === b));
    s.root.querySelector("[name=reason]").value = b.dataset.r;
  });
  s.root.querySelector("#save").onclick = async () => {
    const set_to = Math.round(parseNum(input.value));
    await api(`/api/erp/products/${p.id}/adjust`, { method: "POST", body: { set_to, reason: s.root.querySelector("[name=reason]").value } });
    s.close();
    toast("موجودی ثبت شد");
    done && done();
  };
}

export function openProductForm(p, done) {
  const cats = erp.me.settings.product_categories || [];
  const s = sheet({
    title: p ? "ویرایش محصول" : "محصول جدید",
    size: "wide",
    body: html`<form class="form-grid" id="pf" autocomplete="off">
      <div class="field full"><label>نام محصول *</label><input class="input" name="name" value="${p?.name || ""}" required></div>
      <div class="field"><label>برند</label><input class="input" name="brand" value="${p?.brand || ""}" list="brand-list">
        <datalist id="brand-list">${erp.me.brands.map((b) => html`<option value="${b}">`)}</datalist></div>
      <div class="field"><label>دسته</label><select class="select" name="category">${selectOptions(cats.map((c) => ({ value: c, label: c })), p?.category, "—")}</select></div>
      ${moneyField({ name: "price", label: "قیمت فروش", value: p?.price || "" })}
      ${p ? moneyField({ name: "avg_cost", label: "میانگین قیمت خرید", value: Math.round(p.avg_cost) || "", hint: "با هر خرید خودکار حساب می‌شود" })
        : moneyField({ name: "avg_cost", label: "قیمت خرید هر عدد", value: "" })}
      ${p ? "" : html`<div class="field"><label>موجودی اولیه</label><input class="input" name="stock" data-num inputmode="numeric" placeholder="۰"></div>`}
      <div class="field"><label>هشدار وقتی موجودی به این عدد رسید</label><input class="input" name="low_stock" data-num inputmode="numeric" value="${fa(p?.low_stock ?? erp.me.settings.shop?.low_stock ?? 2)}"></div>
      <div class="field"><label>کد محصول</label><input class="input ltr" name="sku" value="${p?.sku || ""}" placeholder="خودکار"></div>
      <div class="field full"><label>یادداشت</label><input class="input" name="notes" value="${p?.notes || ""}"></div>
    </form>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ذخیره</button><button class="btn ghost" data-close>انصراف</button>
      ${p ? html`<span class="spacer"></span><button class="btn ghost" id="archive">${icon(p.active ? "box" : "rotate-ccw")} ${p.active ? "بایگانی" : "فعال‌سازی دوباره"}</button>` : ""}`,
  });
  bindMoney(s.root);
  s.root.querySelector("#save").onclick = async () => {
    const f = formData(s.root.querySelector("#pf"));
    if (!f.name.trim()) return toast("نام محصول را وارد کنید", "error");
    if (p) {
      await api(`/api/erp/products/${p.id}`, { method: "PUT", body: f });
      toast("ذخیره شد");
      s.close();
      done && done(p.id);
    } else {
      const res = await api("/api/erp/products", { method: "POST", body: f });
      toast("محصول ساخته شد");
      s.close();
      refreshMe();
      done && done(res.id);
    }
  };
  s.root.querySelector("#archive")?.addEventListener("click", async () => {
    await api(`/api/erp/products/${p.id}`, { method: "PUT", body: { active: !p.active } });
    toast(p.active ? "بایگانی شد" : "فعال شد");
    s.close();
    done && done(p.id);
  });
}

export function openProduct(id, changed) {
  let off = () => {};
  const s = sheet({ title: "محصول", side: true, body: '<div class="skeleton" style="height:300px"></div>',
    onClose: () => { off(); if (location.hash.startsWith(`#/erp/products/${id}`)) history.replaceState(null, "", "#/erp/products"); } });
  const admin = isAdmin();
  const load = async () => {
    const { product: p, moves, stats } = await api(`/api/erp/products/${id}`);
    s.root.querySelector(".sheet-head h2").textContent = p.name;
    const margin = p.price ? (p.price - p.avg_cost) / p.price : 0;
    s.root.querySelector(".sheet-body").innerHTML = String(html`<div class="stack">
      <div class="row nowrap">${thumb(p, "lg")}<div style="min-width:0">
        <div class="small muted">${[p.sku, p.brand, p.category].filter(Boolean).join("، ")}</div>
        <div class="row mt8">${stockBadge(p)} ${admin ? wooBadge(p) : ""} ${p.active ? "" : html`<span class="badge">بایگانی</span>`}</div></div></div>
      <div class="grid g3" style="gap:12px">
        <div class="inset"><div class="small muted">موجودی</div><div class="bold num" style="font-size:22px">${fa(p.stock)}</div></div>
        <div class="inset"><div class="small muted">قیمت فروش</div><div class="bold num">${num(p.price)}</div></div>
        ${admin ? html`<div class="inset"><div class="small muted">قیمت خرید (میانگین)</div><div class="bold num">${num(p.avg_cost)}</div>
          <div class="tiny ${margin < 0.15 ? "warn-ink" : "muted"}">سود ${pct(margin)}</div></div>` : ""}
      </div>
      ${admin && stats ? html`<div class="inset row between small"><span>فروش کل: <b>${fa(stats.qty)}</b> عدد</span><span>درآمد <b class="num">${compact(stats.revenue)}</b></span>
        <span>سود <b class="num">${compact(stats.profit)}</b></span><span>آخرین فروش: ${stats.last_sale ? jdate(stats.last_sale) : "—"}</span></div>` : ""}
      ${admin ? html`<div class="row">
          <button class="btn soft sm" data-a="adjust">${icon("pencil", "sm")} اصلاح موجودی</button>
          ${p.stock > 0 ? html`<button class="btn danger sm" data-a="out">${icon("ban", "sm")} ناموجود کن</button>` : ""}
          <button class="btn ghost sm" data-a="edit">${icon("settings", "sm")} ویرایش</button>
        </div>
        ${siteBlock(p)}` : ""}
      ${admin ? html`<div><h3 class="mt8">${icon("history", "sm")} تاریخچه موجودی</h3>
        <div class="table-wrap mt8"><table class="t">
          <thead><tr><th>تاریخ</th><th>نوع</th><th class="n">تغییر</th><th>شرح</th></tr></thead>
          <tbody>${moves.map((m) => html`<tr>
            <td class="nowrap small">${jdate(m.created_at.slice(0, 10), { year: false })} <span class="muted">${timeOf(m.created_at)}</span></td>
            <td><span class="badge ${m.qty > 0 ? "ok" : "coral"}">${MOVE_LABEL[m.kind] || m.kind}</span></td>
            <td class="n bold ${m.qty > 0 ? "ok-ink" : "bad-ink"}">${m.qty > 0 ? "+" : "−"}${fa(Math.abs(m.qty))}</td>
            <td class="small">${m.ref_code ? html`<a href="#/erp/${m.ref_type === "sale" ? "sales" : "purchases"}/${m.ref_id}">${m.ref_code}</a> ` : ""}${m.note || ""}
              ${m.user_name ? html`<span class="muted">، ${m.user_name}</span>` : ""}</td>
          </tr>`)}</tbody></table></div></div>` : ""}
    </div>`);
    s.p = p;
  };
  function siteBlock(p) {
    if (!p.woo_id) {
      return html`<div class="callout">${icon("unlink")}<div>به محصول سایت وصل نیست؛ فروش‌های این محصول موجودی سایت را تغییر نمی‌دهد.
        <a href="#/erp/site" data-close-drawer>وصل کردن از صفحه «اتصال سایت»</a></div></div>`;
    }
    const known = p.woo_stock !== null && p.woo_stock !== undefined;
    const mismatch = known && p.woo_stock !== Math.max(0, p.stock) && p.woo_state !== "pending";
    const st = WOO_STATE[p.woo_state];
    return html`<div class="inset stack s8">
      <div class="row between"><b>${icon("globe", "sm")} سایت</b>${p.woo_url ? html`<a class="btn xs ghost" href="${p.woo_url}" target="_blank" rel="noopener">${icon("external-link", "sm")} صفحه محصول</a>` : ""}</div>
      <div class="small">${p.woo_name || ""}</div>
      <div class="row small"><span>موجودی سایت: <b>${known ? fa(p.woo_stock) : p.woo_state === "nocount" ? (p.woo_in_stock ? "موجود (بدون عدد)" : "ناموجود") : "نامعلوم"}</b></span>
        <span>اینجا: <b>${fa(p.stock)}</b></span>${wooBadge(p)}
        ${p.woo_checked_at ? html`<span class="muted">بررسی ${jdate(p.woo_checked_at.slice(0, 10), { year: false })} ${timeOf(p.woo_checked_at)}</span>` : ""}</div>
      ${st && p.woo_state !== "ok" && p.woo_state !== "error" ? html`<div class="tiny muted">${st.tip}</div>` : ""}
      ${p.woo_error ? html`<div class="small bad-ink">${p.woo_error}</div>` : ""}
      <div class="row">
        <button class="btn xs soft" data-a="push" title="سایت دقیقاً همین عدد را بگیرد">${icon("cloud-upload", "sm")} عدد اینجا درست است</button>
        ${mismatch ? html`<button class="btn xs ghost" data-a="use-site">${icon("download", "sm")} عدد سایت درست است</button>` : ""}
        ${!p.woo_variation_id ? html`<button class="btn xs ghost" data-a="split">${icon("split", "sm")} تفکیک به رنگ‌ها</button>` : ""}
        <button class="btn xs ghost" data-a="unlink">${icon("unlink", "sm")} قطع اتصال</button>
      </div>
    </div>`;
  }
  load();
  const after = async () => { await load(); changed && changed(); };
  delegate(s.root, "click", "[data-close-drawer]", () => s.close());
  delegate(s.root, "click", "[data-a]", async (e, el) => {
    const p = s.p;
    const a = el.dataset.a;
    if (a === "adjust") openAdjust(p, after);
    if (a === "edit") openProductForm(p, after);
    if (a === "out") {
      if (!(await confirmBox(`موجودی «${p.name}» صفر شود؟`, { okText: "ناموجود کن", danger: true }))) return;
      await api(`/api/erp/products/${p.id}/adjust`, { method: "POST", body: { set_to: 0, reason: "ناموجود کردن سریع" } });
      toast("ناموجود شد"); after();
    }
    if (a === "push") {
      if (!(await confirmBox(`موجودی سایت دقیقاً ${fa(Math.max(0, p.stock))} شود؟`, { okText: "بله، روی سایت بگذار" }))) return;
      await api(`/api/erp/products/${p.id}/push`, { method: "POST" }); toast("در حال ارسال به سایت"); setTimeout(after, 2500);
    }
    if (a === "use-site") {
      if (!(await confirmBox(`موجودی اینجا ${fa(p.stock)} است و سایت ${fa(p.woo_stock)}. موجودی اینجا به ${fa(p.woo_stock)} تغییر کند؟`))) return;
      await api(`/api/erp/products/${p.id}/use-site-stock`, { method: "POST" }); toast("هماهنگ شد"); after();
    }
    if (a === "unlink") {
      if (!(await confirmBox("اتصال این محصول به سایت قطع شود؟ موجودی سایت دیگر خودکار تغییر نمی‌کند.", { danger: true, okText: "قطع اتصال" }))) return;
      await api("/api/erp/woo/unlink", { method: "POST", body: { product_id: p.id } }); after();
    }
    if (a === "split") openSplit(p, () => { s.close(); changed && changed(); });
  });
  off = on("live:erp", (ev) => { if (ev.type === "product" && ev.id === id) load(); });
  return s;
}

async function openSplit(p, done) {
  const catalog = await api("/api/erp/woo/catalog");
  const variations = (catalog.items || []).filter((e) => e.woo_id === p.woo_id && e.variation_id);
  if (!variations.length) {
    return toast(catalog.items?.length ? "این محصول در سایت رنگ/مدل ندارد" : "اول در صفحه «اتصال سایت» محصولات سایت را بخوانید", "info");
  }
  const s = sheet({
    title: `تفکیک «${p.name}» به رنگ‌ها`,
    size: "wide",
    body: html`<div class="stack s12">
      <div class="callout">${icon("info")}<div>از این به بعد هر رنگ جداگانه شمرده می‌شود و موجودی هر رنگ در سایت جدا تنظیم می‌شود.
        تعداد هر رنگ را از شمارش واقعی وارد کنید. موجودی فعلی: <b>${fa(p.stock)}</b></div></div>
      <div class="list">${variations.map((v) => html`<div class="list-item">${thumb(v, "sm")}
        <div class="grow"><input class="input sm" data-name="${v.variation_id}" value="${p.name} — ${v.variation_label || ""}"></div>
        <div class="stepper"><button type="button" data-inc="${v.variation_id}">${icon("plus", "sm")}</button>
          <input data-qty="${v.variation_id}" value="${fa(typeof v.stock === "number" && v.stock > 0 ? v.stock : 0)}" inputmode="numeric">
          <button type="button" data-dec="${v.variation_id}">${icon("minus", "sm")}</button></div></div>`)}</div>
      <div class="inset row between"><span>جمع رنگ‌ها</span><b id="sum" class="num"></b></div>
    </div>`,
    foot: html`<button class="btn primary" id="go">${icon("split")} تفکیک کن</button><button class="btn ghost" data-close>انصراف</button>`,
  });
  const sum = () => {
    const total = variations.reduce((t, v) => t + Math.round(parseNum(s.root.querySelector(`[data-qty="${v.variation_id}"]`).value)), 0);
    s.root.querySelector("#sum").textContent = `${fa(total)} از ${fa(p.stock)}`;
    return total;
  };
  sum();
  delegate(s.root, "click", "[data-inc],[data-dec]", (e, b) => {
    const vid = b.dataset.inc || b.dataset.dec;
    const inp = s.root.querySelector(`[data-qty="${vid}"]`);
    inp.value = fa(Math.max(0, Math.round(parseNum(inp.value)) + (b.dataset.inc ? 1 : -1)));
    sum();
  });
  delegate(s.root, "input", "[data-qty]", sum);
  s.root.querySelector("#go").onclick = async () => {
    const total = sum();
    if (total !== p.stock && !(await confirmBox(`جمع رنگ‌ها (${fa(total)}) با موجودی فعلی (${fa(p.stock)}) فرق دارد. ادامه می‌دهید؟`))) return;
    const variants = variations.map((v) => ({
      woo_variation_id: v.variation_id, woo_name: v.name, image: v.image, price: v.price || p.price,
      name: s.root.querySelector(`[data-name="${v.variation_id}"]`).value,
      qty: Math.round(parseNum(s.root.querySelector(`[data-qty="${v.variation_id}"]`).value)),
    }));
    await api(`/api/erp/products/${p.id}/split`, { method: "POST", body: { variants } });
    toast("تفکیک شد");
    s.close();
    done && done();
  };
}
export { esc };
