// Purchases (stock in): the list and each purchase. New purchases are entered on the quick-entry page (sell.js, «خرید کالا»).
import { $, api, confirmBox, debounce, delegate, fa, html, icon, jdate, num, on, sheet, toast, toman } from "/static/js/kit.js";
import { emptyState, receiptLink, thumb } from "/static/js/kit.js";
import { periodChips, periodRange } from "/static/js/kit.js";
import { erp } from "../erp.js";

const norm = (s) => String(s || "").replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ").toLowerCase();

export async function render(view, params, { setTitle }) {
  setTitle("خرید کالا", "هر خرید موجودی را زیاد و میانگین قیمت تمام‌شده را به‌روز می‌کند");
  const f = { period: "3m", q: "" };
  let rows = [];
  view.innerHTML = String(html`<div class="stack">
    <div class="card tight stack s12">
      <div class="row">
        <div class="input-wrap" style="flex:1;min-width:220px">${icon("search")}<input class="input" id="q" placeholder="کد، تأمین‌کننده یا نام کالا…"></div>
        <button class="btn primary" id="new">${icon("plus")} ثبت خرید</button>
      </div>
      <div id="periods"></div>
    </div>
    <section class="card" id="list"></section>
  </div>`);
  async function load() {
    const r = periodRange(f.period);
    rows = await api(`/api/erp/purchases?${new URLSearchParams({ start: r.start, end: r.end, q: f.q })}`, { quiet: true });
    $("#periods", view).innerHTML = String(periodChips(f.period));
    const done = rows.filter((x) => x.status === "done");
    const el = $("#list", view);
    if (!rows.length) {
      el.innerHTML = String(emptyState("truck", "خریدی در این بازه نیست", "کالایی که می‌خرید را با «ثبت خرید» وارد کنید تا به انبار اضافه شود."));
      return;
    }
    el.innerHTML = String(html`<div class="card-head"><h3>${fa(done.length)} خرید</h3>
      <span class="muted small">، ${fa(done.reduce((s, x) => s + (x.items_count || 0), 0))} عدد، ${toman(done.reduce((s, x) => s + x.total, 0))}</span></div>
      <div class="table-wrap"><table class="t responsive">
      <thead><tr><th>تاریخ</th><th>کد</th><th>تأمین‌کننده</th><th>اقلام</th><th class="n">مبلغ</th><th>پرداخت از</th><th></th></tr></thead>
      <tbody>${rows.map((r) => html`<tr class="clickable ${r.status === "void" ? "void" : ""}" data-open="${r.id}">
        <td class="nowrap">${jdate(r.date, { year: false })}</td><td class="small muted">${r.code}</td>
        <td><b>${r.supplier || "—"}</b></td>
        <td class="m-full small muted" style="max-width:340px"><div class="ellipsis">${fa(r.items_text || "")}</div></td>
        <td class="n bold">${num(r.total)}</td>
        <td class="small">${r.account_name || html`<span class="muted">جداگانه</span>`}</td>
        <td>${receiptLink(r.receipt)}</td></tr>`)}</tbody></table></div>`);
  }
  await load();
  $("#q", view).addEventListener("input", debounce((e) => { f.q = e.target.value; load(); }, 300));
  delegate(view, "click", "[data-period]", (e, el) => { f.period = el.dataset.period; load(); });
  delegate(view, "click", "[data-open]", (e, el) => { if (!e.target.closest("a")) location.hash = `#/erp/purchases/${el.dataset.open}`; });
  $("#new", view).onclick = () => { location.hash = "#/erp/sell?mode=buy"; };

  let drawer = null;
  const openFromParams = (p) => {
    if (drawer) { drawer.close(); drawer = null; }
    if (p[0] === "new") location.replace("#/erp/sell?mode=buy");     // purchases are entered on the quick-entry page
    else if (p[0]) drawer = openPurchase(Number(p[0]), load);
  };
  openFromParams(params);
  const off = on("live:erp", (ev) => { if (ev.type === "refresh" && ev.scope === "purchases") load(); });
  return { cleanup: () => { off(); drawer && drawer.close(); }, onParams: openFromParams };
}

function openPurchase(id, changed) {
  const s = sheet({ title: "خرید", side: true, body: '<div class="skeleton" style="height:240px"></div>',
    onClose: () => { if (location.hash.startsWith("#/erp/purchases/")) history.replaceState(null, "", "#/erp/purchases"); } });
  const load = async () => {
    const { purchase: p, items } = await api(`/api/erp/purchases/${id}`);
    s.root.querySelector(".sheet-head h2").textContent = `خرید ${p.code}`;
    s.root.querySelector(".sheet-body").innerHTML = String(html`<div class="stack">
      <div class="row"><span class="small muted">${jdate(p.date, { weekday: true })}</span>${p.status === "void" ? html`<span class="badge bad">باطل شده</span>` : ""}
        <span class="spacer"></span>${receiptLink(p.receipt)}</div>
      <div class="list">${items.map((it) => html`<div class="list-item">${thumb(it, "sm")}
        <div class="grow"><a class="title small" href="#/erp/products/${it.product_id}">${it.name}</a>
          <div class="sub">${fa(it.qty)} × ${num(it.unit_cost)}${Math.round(it.landed_cost) !== Math.round(it.unit_cost) ? `، تمام‌شده با حمل ${num(it.landed_cost)}` : ""}</div></div>
        <b class="num">${num(it.line_total)}</b></div>`)}</div>
      <div class="inset totals">
        <div class="t-row"><span class="muted">جمع کالاها</span><span class="num">${num(p.subtotal)}</span></div>
        ${p.shipping ? html`<div class="t-row"><span class="muted">حمل و هزینه‌ها</span><span class="num">${num(p.shipping)}</span></div>` : ""}
        <div class="t-row t-grand"><span>جمع</span><span class="num">${toman(p.total)}</span></div>
      </div>
      <div class="list small">
        <div class="list-item"><span class="grow muted">تأمین‌کننده</span><span>${p.supplier || "—"}</span></div>
        <div class="list-item"><span class="grow muted">پرداخت از</span><span>${p.account_name || "جداگانه ثبت شده"}</span></div>
        ${p.note ? html`<div class="list-item"><span class="grow muted">یادداشت</span><span>${p.note}</span></div>` : ""}
      </div>
    </div>`);
    if (p.status === "done" && !s.root.querySelector(".sheet-foot")) {
      const foot = document.createElement("div");
      foot.className = "sheet-foot";
      foot.innerHTML = String(html`<span class="spacer"></span><button class="btn danger" id="void">${icon("undo-2")} ابطال این خرید</button>`);
      s.root.appendChild(foot);
      foot.querySelector("#void").onclick = async () => {
        if (!(await confirmBox("این خرید باطل شود؟ کالاها از موجودی کم و میانگین قیمت دوباره حساب می‌شود.", { danger: true, okText: "ابطال" }))) return;
        await api(`/api/erp/purchases/${id}/void`, { method: "POST" });
        toast("خرید باطل شد");
        foot.remove();
        load(); changed && changed();
      };
    }
  };
  load();
  return s;
}
