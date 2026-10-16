// Sales list across all channels, with a detail drawer (edit payment info, void/return).
import { $, api, compact, confirmBox, debounce, delegate, fa, html, icon, jdate, num, on, sheet, storage, timeOf, toast, toman } from "/static/js/kit.js";
import { bindDates, dateField, emptyState, formData, selectOptions, thumb } from "/static/js/kit.js";
import { periodChips, periodRange } from "/static/js/kit.js";
import { accountOptions, CHANNEL_ICON, erp, isAdmin } from "../erp.js";

export async function render(view, params, { setTitle, query }) {
  const admin = isAdmin();
  setTitle(admin ? "فروش‌ها" : "فروش‌های من", "همه کانال‌ها: سایت، دایرکت، حضوری و دوستان");
  const f = { period: query.get("unpaid") ? "all" : storage("sales-period") || "month", channel: "", q: "", unpaid: !!query.get("unpaid"), voids: false };
  let rows = [];

  view.innerHTML = String(html`<div class="stack">
    <div class="card tight stack s12">
      <div class="row">
        <div class="input-wrap" style="flex:1;min-width:220px">${icon("search")}<input class="input" id="q" placeholder="کد، مشتری، تلفن یا نام محصول…"></div>
        <a class="btn brand" href="#/erp/sell">${icon("plus")} فروش جدید</a>
      </div>
      <div id="periods"></div>
      <div class="row">
        <div class="chips scroll" id="channels" style="flex:1"></div>
        <label class="check small"><span class="switch"><input type="checkbox" id="unpaid" ${f.unpaid ? "checked" : ""}><span></span></span>فقط پرداخت‌نشده</label>
        <label class="check small"><span class="switch"><input type="checkbox" id="voids"><span></span></span>باطل‌شده‌ها هم</label>
      </div>
    </div>
    <div class="grid g4" id="summary"></div>
    <section class="card" id="list"></section>
  </div>`);

  const drawFilters = () => {
    $("#periods", view).innerHTML = String(periodChips(f.period));
    const chans = [{ value: "", label: "همه کانال‌ها" }, ...Object.entries(erp.me.channels).map(([value, label]) => ({ value, label }))];
    $("#channels", view).innerHTML = String(html`${chans.map((c) => html`<button class="chip ${f.channel === c.value ? "on" : ""}" data-ch="${c.value}">
      ${c.value ? icon(CHANNEL_ICON[c.value], "sm") : ""}${c.label}</button>`)}`);
  };
  async function load() {
    const r = periodRange(f.period);
    const qs = new URLSearchParams({ start: r.start, end: r.end, channel: f.channel, q: f.q, unpaid: f.unpaid ? "true" : "false" });
    if (!f.voids) qs.set("status", "done");
    rows = await api(`/api/erp/sales?${qs}`, { quiet: true });
    draw();
  }
  function draw() {
    const done = rows.filter((r) => r.status === "done");
    const revenue = done.reduce((s, r) => s + r.total, 0);
    const profit = done.reduce((s, r) => s + r.total - (r.cogs || 0), 0);
    const unpaid = done.filter((r) => !r.paid).reduce((s, r) => s + r.total, 0);
    const items = done.reduce((s, r) => s + (r.items_count || 0), 0);
    $("#summary", view).innerHTML = String(html`
      <div class="kpi indigo"><div class="k-label">تعداد فروش</div><div class="k-value">${fa(done.length)}</div><div class="k-foot">${fa(items)} عدد کالا</div></div>
      <div class="kpi orchid" title="${toman(revenue)}"><div class="k-label">مبلغ فروش</div><div class="k-value">${compact(revenue)}<span class="k-unit">تومان</span></div>
        <div class="k-foot">میانگین هر سفارش ${compact(done.length ? revenue / done.length : 0)}</div></div>
      ${admin ? html`<div class="kpi mint" title="${toman(profit)}"><div class="k-label">سود ناخالص</div><div class="k-value">${compact(profit)}<span class="k-unit">تومان</span></div>
        <div class="k-foot">قبل از هزینه‌های جاری</div></div>` : ""}
      <div class="kpi ${unpaid ? "coral" : "sand"}"><div class="k-label">پرداخت‌نشده</div><div class="k-value">${compact(unpaid)}<span class="k-unit">تومان</span></div>
        <div class="k-foot">${fa(done.filter((r) => !r.paid).length)} فروش</div></div>`);
    const el = $("#list", view);
    if (!rows.length) {
      el.innerHTML = String(emptyState("receipt", "فروشی در این بازه نیست", "", html`<a class="btn primary mt8" href="#/erp/sell">${icon("plus")} ثبت فروش</a>`));
      return;
    }
    el.innerHTML = String(html`<div class="table-wrap"><table class="t responsive">
      <thead><tr><th>تاریخ</th><th>مشتری / کد</th><th>اقلام</th><th>کانال</th>${admin ? html`<th>فروشنده</th>` : ""}<th class="n">مبلغ</th><th>پرداخت</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr class="clickable ${r.status === "void" ? "void" : ""}" data-open="${r.id}">
        <td class="nowrap">${jdate(r.date, { year: false })}</td>
        <td class="m-full"><b>${r.customer_name || "—"}</b> <span class="muted small">${r.code}</span></td>
        <td class="m-full small muted" style="max-width:320px"><div class="ellipsis">${fa(r.items_text || "")}</div></td>
        <td><span class="badge primary">${icon(CHANNEL_ICON[r.channel] || "tag")}${erp.me.channels[r.channel] || r.channel}</span></td>
        ${admin ? html`<td class="small m-hide">${r.seller_name || (r.channel === "website" ? "سایت" : "—")}</td>` : ""}
        <td class="n bold">${num(r.total)}</td>
        <td>${r.status === "void" ? html`<span class="badge">باطل</span>` : r.paid ? html`<span class="badge ok">${icon("check")}${r.account_name || "پرداخت شد"}</span>` : html`<span class="badge warn">${icon("clock")}نسیه</span>`}</td>
      </tr>`)}</tbody></table></div>`);
  }
  drawFilters();
  await load();

  $("#q", view).addEventListener("input", debounce((e) => { f.q = e.target.value; load(); }, 300));
  delegate(view, "click", "[data-period]", (e, el) => { f.period = el.dataset.period; storage("sales-period", f.period); drawFilters(); load(); });
  delegate(view, "click", "[data-ch]", (e, el) => { f.channel = el.dataset.ch; drawFilters(); load(); });
  $("#unpaid", view).addEventListener("change", (e) => { f.unpaid = e.target.checked; load(); });
  $("#voids", view).addEventListener("change", (e) => { f.voids = e.target.checked; load(); });
  delegate(view, "click", "[data-open]", (e, el) => { location.hash = `#/erp/sales/${el.dataset.open}`; });

  let drawer = null;
  const openFromParams = (p) => {
    if (drawer) { drawer.close(); drawer = null; }
    if (p[0]) drawer = openSale(Number(p[0]), load);
  };
  openFromParams(params);
  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "refresh" && ev.scope === "sales") { clearTimeout(timer); timer = setTimeout(load, 500); }
  });
  return { cleanup: () => { off(); drawer && drawer.close(); }, onParams: openFromParams };
}

export function openSale(id, changed) {
  const admin = isAdmin();
  const s = sheet({ title: "فروش", side: true, body: '<div class="skeleton" style="height:300px"></div>',
    onClose: () => { if (location.hash.startsWith(`#/erp/sales/${id}`)) history.replaceState(null, "", "#/erp/sales"); } });
  const load = async () => {
    const { sale, items } = await api(`/api/erp/sales/${id}`);
    s.sale = sale;
    s.root.querySelector(".sheet-head h2").textContent = `فروش ${sale.code}`;
    const profit = sale.total - (sale.cogs || 0);
    const siteUrl = erp.me.site.url;
    s.root.querySelector(".sheet-body").innerHTML = String(html`<div class="stack">
      <div class="row">
        <span class="badge primary">${icon(CHANNEL_ICON[sale.channel] || "tag")}${erp.me.channels[sale.channel]}</span>
        ${sale.status === "void" ? html`<span class="badge bad">باطل شده</span>` : sale.paid ? html`<span class="badge ok">پرداخت شده</span>` : html`<span class="badge warn">پرداخت نشده</span>`}
        ${sale.woo_order_id ? html`<a class="badge info" href="${siteUrl}/wp-admin/post.php?post=${sale.woo_order_id}&action=edit" target="_blank" rel="noopener">${icon("external-link")}سفارش سایت (${sale.woo_status})</a>` : ""}
        ${sale.source === "sheet" ? html`<span class="badge">از اکسل</span>` : ""}
        <span class="spacer"></span><span class="small muted">${jdate(sale.date, { weekday: true })}</span>
      </div>
      <div class="list">${items.map((it) => html`<div class="list-item">${thumb(it, "sm")}
        <div class="grow"><div class="title small">${it.name}</div><div class="sub">${fa(it.qty)} × ${num(it.unit_price)}
          ${admin && it.unit_cost ? html`، قیمت خرید ${num(it.unit_cost)}` : ""}</div></div>
        <div style="text-align:left"><b class="num">${num(it.line_total)}</b>${it.discount ? html`<div class="tiny muted num">تخفیف −${num(it.discount)}</div>` : ""}</div></div>`)}</div>
      <div class="inset totals">
        <div class="t-row"><span class="muted">جمع اقلام</span><span class="num">${num(sale.subtotal)}</span></div>
        ${sale.discount ? html`<div class="t-row"><span class="muted">تخفیف</span><span class="num">−${num(sale.discount)}</span></div>` : ""}
        ${sale.shipping ? html`<div class="t-row"><span class="muted">ارسال</span><span class="num">+${num(sale.shipping)}</span></div>` : ""}
        ${sale.fees ? html`<div class="t-row"><span class="muted">کارمزد / هزینه اضافه سایت</span><span class="num">${sale.fees > 0 ? "+" : "−"}${num(Math.abs(sale.fees))}</span></div>` : ""}
        ${sale.refunded ? html`<div class="t-row"><span class="muted">برگشت وجه در سایت</span><span class="num bad-ink">−${num(sale.refunded)}</span></div>` : ""}
        <div class="t-row t-grand"><span>مبلغ نهایی</span><span class="num">${toman(sale.total)}</span></div>
        ${admin ? html`<div class="t-row small"><span class="muted">سود ناخالص</span><span class="num ${profit < 0 ? "bad-ink" : "ok-ink"}">${num(profit)}</span></div>` : ""}
        ${sale.commission ? html`<div class="t-row small"><span class="muted">پورسانت فروشنده</span><span class="num">${num(sale.commission)}</span></div>` : ""}
      </div>
      ${admin && sale.status === "done" ? html`<form class="form-grid" id="meta">
          <div class="field"><label>مشتری</label><input class="input" name="customer_name" value="${sale.customer_name || ""}"></div>
          <div class="field"><label>تلفن</label><input class="input ltr" name="customer_phone" value="${sale.customer_phone || ""}"></div>
          ${dateField({ name: "date", label: "تاریخ", value: sale.date })}
          <div class="field"><label>کانال</label><select class="select" name="channel">${selectOptions(Object.entries(erp.me.channels).map(([value, label]) => ({ value, label })), sale.channel)}</select></div>
          <div class="field"><label>پول به کدام حساب رفت</label><select class="select" name="account_id">${accountOptions(sale.account_id, { includeEmpty: "—" })}</select></div>
          <div class="field"><label>فروشنده</label><select class="select" name="seller_id">${selectOptions(erp.me.users.map((u) => ({ value: u.id, label: u.name })), sale.seller_id, "—")}</select></div>
          <label class="check full"><span class="switch"><input type="checkbox" name="paid" ${sale.paid ? "checked" : ""}><span></span></span>پول دریافت شده</label>
          <div class="field full"><label>یادداشت</label><input class="input" name="note" value="${sale.note || ""}"></div>
        </form>` : html`<div class="list small">
          <div class="list-item"><span class="grow muted">مشتری</span><span>${sale.customer_name || "—"} ${sale.customer_phone ? html`<span class="ltr">${sale.customer_phone}</span>` : ""}</span></div>
          <div class="list-item"><span class="grow muted">فروشنده</span><span>${sale.seller_name || "—"}</span></div>
          <div class="list-item"><span class="grow muted">حساب دریافت</span><span>${sale.account_name || "—"}</span></div>
          ${sale.note ? html`<div class="list-item"><span class="grow muted">یادداشت</span><span>${sale.note}</span></div>` : ""}
        </div>`}
      <p class="tiny muted">ثبت ${sale.created_by_name ? `توسط ${sale.created_by_name}` : "خودکار"}، ${jdate(sale.created_at.slice(0, 10))} ${timeOf(sale.created_at)}</p>
    </div>`);
    const foot = s.root.querySelector(".sheet-foot") || Object.assign(document.createElement("div"), { className: "sheet-foot" });
    foot.innerHTML = String(html`${admin && sale.status === "done" ? html`<button class="btn primary" data-a="save">${icon("check")} ذخیره تغییرات</button>` : ""}
      ${sale.status === "done" ? html`<span class="spacer"></span><button class="btn danger" data-a="void">${icon("undo-2")} ابطال / مرجوعی</button>` : ""}`);
    if (!foot.parentElement) s.root.appendChild(foot);
    bindDates(s.root);
  };
  load();
  delegate(s.root, "click", "[data-a]", async (e, el) => {
    if (el.dataset.a === "save") {
      const f = formData(s.root.querySelector("#meta"));
      await api(`/api/erp/sales/${id}`, { method: "PUT", body: f });
      toast("ذخیره شد");
      load(); changed && changed();
    }
    if (el.dataset.a === "void") {
      const r = await confirmBox("این فروش باطل شود؟ کالاها به انبار برمی‌گردند (و در سایت هم موجود می‌شوند).", { danger: true, okText: "ابطال فروش", input: "دلیل (مثلاً مرجوعی مشتری)" });
      if (!r) return;
      await api(`/api/erp/sales/${id}/void`, { method: "POST", body: { reason: r.value } });
      toast("فروش باطل شد و موجودی برگشت");
      load(); changed && changed();
    }
  });
  return s;
}
