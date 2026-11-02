// Every product of the site against every competitor, with filters; a row opens the product detail.
import { $, api, debounce, delegate, emptyState, html, icon, storage } from "/static/js/kit.js";
import { P, POS, bindTips, img, ladder, n, openProduct, posGap, refreshMeta, siteName } from "../pricing.js";

const SORTS = [["gap", "گران‌ترین نسبت به رقبا"], ["gap_asc", "ارزان‌ترین نسبت به رقبا"], ["impact", "بیشترین اثر مالی"],
  ["sites", "بیشترین رقیب"], ["price", "قیمت (زیاد به کم)"], ["name", "نام"]];

export async function render(view, params, { setTitle }) {
  setTitle("محصولات", "قیمت شما در برابر همه رقبا؛ روی هر محصول بزنید تا جزئیات و همه فروشنده‌ها را ببینید");
  const f = P.filters;
  if (!P.meta) await refreshMeta();
  view.innerHTML = String(html`<div class="stack pricing">
    <div class="card tight"><div class="stack s12">
      <div class="row">
        <div class="input-wrap" style="flex:1 1 260px">${icon("search")}<input enterkeyhint="search" class="input" type="search" id="fq" placeholder="جستجوی نام یا برند…" value="${f.q}"></div>
        <select class="select" id="fbrand" style="width:auto;min-width:150px"><option value="">همه برندها</option></select>
        <select class="select" id="fsite" style="width:auto;min-width:140px"><option value="">همه رقبا</option>
          ${P.meta.sites.map((s) => html`<option value="${s.key}" ${f.site === s.key ? "selected" : ""}>${s.name}</option>`)}</select>
        <select class="select" id="fsort" style="width:auto;min-width:190px">${SORTS.map(([k, l]) => html`<option value="${k}" ${f.sort === k ? "selected" : ""}>${l}</option>`)}</select>
        <a class="btn soft" href="/api/pricing/export.csv">${icon("download", "sm")} اکسل</a>
      </div>
      <div class="chips scroll" id="fpos">
        <button class="chip ${!f.position && !f.opportunity ? "on" : ""}" data-p="">همه</button>
        ${Object.entries(POS).map(([k, p]) => html`<button class="chip ${f.position === k ? "on" : ""}" data-p="${k}"><span class="dot" style="color:${p.color}"></span>${p.label}</button>`)}
        <button class="chip ${f.opportunity === "raise" ? "on" : ""}" data-o="raise">${icon("piggy-bank", "sm")} فرصت افزایش قیمت</button>
      </div>
    </div></div>
    <section class="card"><div class="table-wrap" id="ptable"><div class="skeleton" style="height:300px"></div></div></section>
  </div>`);

  const load = async () => {
    storage("pricing-filters", P.filters);
    const qs = new URLSearchParams(Object.entries(P.filters).filter(([, v]) => v));
    const data = await api(`/api/pricing/products?${qs}`);
    const sel = $("#fbrand", view);
    if (sel && sel.options.length <= 1) {
      sel.innerHTML = String(html`<option value="">همه برندها</option>${data.brands.map((b) => html`<option ${P.filters.brand === b ? "selected" : ""}>${b}</option>`)}`);
    }
    $("#ptable", view).innerHTML = String(table(data.items, data.total));
    bindTips($("#ptable", view));
  };
  $("#fq", view).oninput = debounce((e) => { P.filters.q = e.target.value.trim(); load(); }, 250);
  $("#fbrand", view).onchange = (e) => { P.filters.brand = e.target.value; load(); };
  $("#fsite", view).onchange = (e) => { P.filters.site = e.target.value; load(); };
  $("#fsort", view).onchange = (e) => { P.filters.sort = e.target.value; load(); };
  delegate(view, "click", "#fpos .chip", (e, b) => {
    view.querySelectorAll("#fpos .chip").forEach((x) => x.classList.toggle("on", x === b));
    P.filters.position = b.dataset.p || "";
    P.filters.opportunity = b.dataset.o || "";
    load();
  });
  delegate(view, "click", "[data-pid]", (e, r) => openProduct(+r.dataset.pid, { onChange: load }));
  await load();
}

function table(items, total) {
  if (!items.length) {
    const filtered = ["q", "position", "brand", "site", "opportunity"].some((k) => P.filters[k]);
    return filtered ? emptyState("search", "محصولی با این فیلترها پیدا نشد", "فیلترها یا جستجو را تغییر دهید.")
      : emptyState("package", "هنوز محصولی خوانده نشده", "با «بروزرسانی قیمت‌ها» محصولات سایت و قیمت رقبا خوانده می‌شود.");
  }
  // thumbnails are decided for the whole list, not per row: either every row keeps the slot or none does
  const thumbs = items.some((r) => r.image);
  const pending = (r) => (r.n_pending ? html`، <span class="badge warn">${n(r.n_pending)} منتظر تأیید</span>` : "");
  return html`<table class="t desk-only"><thead><tr>
      <th>محصول</th><th class="n">قیمت شما</th><th class="n">ارزان‌ترین رقیب</th><th class="n">میانه بازار</th>
      <th title="هر نقطه یک رقیب، لوزی قیمت شما؛ راست‌تر یعنی ارزان‌تر">بازه قیمت بازار</th><th>جایگاه نسبت به ارزان‌ترین</th></tr></thead><tbody>
    ${items.map((r) => html`<tr class="clickable" data-pid="${r.id}">
      <td><div class="prod-cell">${thumbs ? img(r.image) : ""}<div style="min-width:0"><div class="name">${r.name}</div>
        <div class="meta">${r.brand || ""}${pending(r)}</div></div></div></td>
      <td class="n"><b>${n(r.my_price)}</b>${!r.in_stock ? html`<div class="small muted">ناموجود</div>` : ""}</td>
      <td class="n">${r.min ? html`${n(r.min)}<div class="small muted">${siteName(r.cheapest_site)}</div>` : html`<span class="muted">—</span>`}</td>
      <td class="n">${r.median ? html`${n(r.median)}<div class="small muted">${n(r.n_sites)} سایت، ${n(r.n_listings)} فروشنده</div>` : html`<span class="muted">—</span>`}</td>
      <td>${ladder(r)}</td>
      <td>${posGap(r.position, r.gap_min_pct)}</td></tr>`)}
    </tbody></table>
    <div class="p-mlist phone-only">${items.map((r) => html`<div class="list-item clickable" data-pid="${r.id}">
      ${thumbs ? img(r.image) : ""}
      <div class="grow"><div class="title">${r.name}</div>
        <div class="sub">شما <b class="num">${n(r.my_price)}</b>${r.min ? html`، ارزان‌ترین <span class="num">${n(r.min)}</span> در ${siteName(r.cheapest_site)}` : ""}${!r.in_stock ? "، ناموجود" : ""}${pending(r)}</div></div>
      ${posGap(r.position, r.gap_min_pct)}</div>`)}</div>
    <p class="small muted mt8">${n(total)} محصول، قیمت‌ها به تومان</p>`;
}
