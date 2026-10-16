// Purchases (stock in): list and the purchase form. Shipping is spread over items to get the landed cost.
import { $, api, compact, confirmBox, debounce, delegate, fa, html, icon, jdate, num, on, parseNum, sheet, toast, toman } from "/static/js/kit.js";
import { bindChoices, bindDates, bindMoney, bindUploads, dateField, emptyState, formData, moneyField, receiptLink, selectOptions, thumb, uploadField } from "/static/js/kit.js";
import { periodChips, periodRange } from "/static/js/kit.js";
import { accountChoice, erp, refreshMe } from "../erp.js";

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
      el.innerHTML = String(emptyState("truck", "خریدی در این بازه نیست", "کالایی که می‌خرید را اینجا ثبت کنید تا به انبار اضافه شود."));
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
  $("#new", view).onclick = () => { location.hash = "#/erp/purchases/new"; };

  let drawer = null;
  const openFromParams = (p) => {
    if (drawer) { drawer.close(); drawer = null; }
    if (p[0] === "new") drawer = openPurchaseForm(load);
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

export function openPurchaseForm(done) {
  let products = [];
  const lines = [{ key: 1 }];
  let nextKey = 2;
  const s = sheet({
    title: "ثبت خرید کالا",
    size: "xwide",
    onClose: () => { if (location.hash.startsWith("#/erp/purchases/new")) history.replaceState(null, "", "#/erp/purchases"); },
    body: html`<div class="stack" id="pform">
      <div class="form-grid">
        ${dateField({ name: "date", label: "تاریخ خرید", value: erp.me.today })}
        <div class="field"><label>تأمین‌کننده / فروشنده</label><input class="input" name="supplier" list="sup-list" placeholder="مثلاً بازار، دیجی‌کالا، …">
          <datalist id="sup-list">${erp.me.suppliers.map((x) => html`<option value="${x}">`)}</datalist></div>
      </div>
      <div><div class="row between"><h3>${icon("package", "sm")} کالاها</h3><button type="button" class="btn sm soft" id="add-line">${icon("plus", "sm")} ردیف جدید</button></div>
        <div class="stack s8 mt12" id="lines"></div></div>
      <div class="form-grid">
        ${moneyField({ name: "shipping", label: "هزینه حمل / پیک / سایر (بین کالاها تقسیم می‌شود)", value: "" })}
        <div class="field"><label>جمع</label><div class="inset row between"><span class="muted" id="sum-sub"></span><b class="num" id="sum-total" style="font-size:18px"></b></div></div>
        <div class="field full"><label>پول از کدام حساب پرداخت شد؟</label>${accountChoice("account_id", erp.me.user.account_id)}</div>
        ${uploadField({ name: "receipt" })}
        <div class="field"><label>یادداشت</label><textarea class="textarea" name="note" rows="2"></textarea></div>
      </div>
    </div>`,
    foot: html`<button class="btn primary lg" id="save">${icon("check")} ثبت خرید و افزودن به انبار</button><button class="btn ghost" data-close>انصراف</button>`,
  });
  const root = s.root;
  bindMoney(root);
  bindDates(root);
  bindChoices(root);
  bindUploads(root);
  api("/api/erp/products").then((p) => { products = p; });

  const lineHtml = (l) => html`<div class="inset" data-line="${l.key}" style="padding:12px">
    <div class="row nowrap" style="align-items:flex-start;gap:10px">
      <div style="flex:2;min-width:0;position:relative">
        <input class="input sm" data-pick="${l.key}" placeholder="نام کالا را بنویسید…" value="${l.label || ""}" autocomplete="off">
        <div class="pick-list hidden" data-list="${l.key}"></div>
        ${l.isNew ? html`<div class="form-grid mt8" style="grid-template-columns:1fr 1fr 1fr">
          <input class="input sm" data-new-brand="${l.key}" placeholder="برند" value="${l.brand || ""}">
          <select class="select sm" data-new-cat="${l.key}">${selectOptions((erp.me.settings.product_categories || []).map((c) => ({ value: c, label: c })), l.category, "دسته")}</select>
          <input class="input sm money" data-new-price="${l.key}" data-money placeholder="قیمت فروش" value="${l.price ? num(l.price) : ""}" inputmode="numeric">
        </div><div class="tiny orchid-ink mt8" style="color:var(--orchid-ink)">${icon("sparkles", "sm")} محصول جدید ساخته می‌شود</div>` : ""}
      </div>
      <div style="width:84px"><input class="input sm" data-qty="${l.key}" placeholder="تعداد" value="${l.qty ? fa(l.qty) : ""}" inputmode="numeric"></div>
      <div style="flex:1;min-width:110px"><input class="input sm money" data-cost="${l.key}" data-money placeholder="قیمت خرید هر عدد" value="${l.unit_cost ? num(l.unit_cost) : ""}" inputmode="numeric"></div>
      <button type="button" class="btn icon xs ghost" data-remove="${l.key}" aria-label="حذف ردیف">${icon("x", "sm")}</button>
    </div>
  </div>`;
  const drawLines = () => {
    root.querySelector("#lines").innerHTML = String(html`${lines.map(lineHtml)}`);
    updateSum();
  };
  const updateSum = () => {
    const sub = lines.reduce((t, l) => t + (l.qty || 0) * (l.unit_cost || 0), 0);
    const ship = parseNum(root.querySelector("[name=shipping]").value);
    root.querySelector("#sum-sub").textContent = `${fa(lines.reduce((t, l) => t + (l.qty || 0), 0))} عدد`;
    root.querySelector("#sum-total").textContent = toman(sub + ship);
  };
  drawLines();

  const style = document.createElement("style");
  style.textContent = `.pick-list{position:absolute;z-index:5;top:44px;inset-inline:0;max-height:280px;overflow:auto;background:var(--clay);border-radius:18px;box-shadow:var(--clay-shadow-lg);padding:6px}
    .pick-list button{display:flex;gap:10px;align-items:center;width:100%;border:0;background:transparent;padding:8px;border-radius:12px;text-align:start}
    .pick-list button:hover,.pick-list button.act{background:var(--primary-soft)}`;
  root.appendChild(style);

  const lineOf = (key) => lines.find((l) => l.key === Number(key));
  const showList = (key, text) => {
    const box = root.querySelector(`[data-list="${key}"]`);
    const terms = norm(text).split(/\s+/).filter(Boolean);
    const matches = products.filter((p) => !terms.length || terms.every((t) => norm(`${p.name} ${p.brand || ""} ${p.sku || ""}`).includes(t))).slice(0, 8);
    box.innerHTML = String(html`${matches.map((p) => html`<button type="button" data-choose="${key}" data-pid="${p.id}">${thumb(p, "sm")}
        <span class="grow small" style="flex:1">${p.name}<br><span class="muted tiny">موجودی ${fa(p.stock)}، آخرین قیمت خرید ${num(p.avg_cost)}</span></span></button>`)}
      ${text.trim() ? html`<button type="button" data-choose="${key}" data-new="1"><span class="thumb sm">${icon("package-plus", "sm")}</span>
        <span class="small">محصول جدید: <b>«${text.trim()}»</b></span></button>` : ""}`);
    box.classList.toggle("hidden", !matches.length && !text.trim());
  };
  delegate(root, "input", "[data-pick]", (e, el) => {
    const l = lineOf(el.dataset.pick);
    l.label = el.value;
    if (l.product_id) { l.product_id = null; }
    showList(el.dataset.pick, el.value);
  });
  delegate(root, "focusin", "[data-pick]", (e, el) => showList(el.dataset.pick, el.value));
  delegate(root, "mousedown", "[data-choose]", (e, b) => {
    e.preventDefault();
    const l = lineOf(b.dataset.choose);
    if (b.dataset.new) {
      Object.assign(l, { isNew: true, product_id: null });
    } else {
      const p = products.find((x) => x.id === Number(b.dataset.pid));
      Object.assign(l, { isNew: false, product_id: p.id, label: p.name, unit_cost: l.unit_cost || Math.round(p.avg_cost) || null });
    }
    drawLines();
    root.querySelector(`[data-qty="${l.key}"]`)?.focus();
  });
  root.addEventListener("focusout", (e) => {
    if (e.target.matches("[data-pick]")) setTimeout(() => root.querySelector(`[data-list="${e.target.dataset.pick}"]`)?.classList.add("hidden"), 150);
  });
  delegate(root, "input", "[data-qty]", (e, el) => { lineOf(el.dataset.qty).qty = Math.round(parseNum(el.value)) || 0; updateSum(); });
  delegate(root, "input", "[data-cost]", (e, el) => { lineOf(el.dataset.cost).unit_cost = parseNum(el.value) || 0; updateSum(); });
  delegate(root, "input", "[data-new-brand]", (e, el) => { lineOf(el.dataset.newBrand).brand = el.value; });
  delegate(root, "change", "[data-new-cat]", (e, el) => { lineOf(el.dataset.newCat).category = el.value; });
  delegate(root, "input", "[data-new-price]", (e, el) => { lineOf(el.dataset.newPrice).price = parseNum(el.value); });
  delegate(root, "input", "[name=shipping]", updateSum);
  delegate(root, "click", "[data-remove]", (e, el) => {
    const i = lines.findIndex((l) => l.key === Number(el.dataset.remove));
    lines.splice(i, 1);
    if (!lines.length) lines.push({ key: nextKey++ });
    drawLines();
  });
  root.querySelector("#add-line").onclick = () => { lines.push({ key: nextKey++ }); drawLines(); root.querySelector(`[data-pick="${nextKey - 1}"]`).focus(); };

  root.querySelector("#save").onclick = async () => {
    const f = formData(root.querySelector("#pform"));
    const items = [];
    for (const l of lines) {
      if (!l.product_id && !l.isNew && !(l.label || "").trim()) continue;
      if (!l.product_id && !l.isNew) return toast(`«${l.label}» را از فهرست انتخاب کنید یا «محصول جدید» را بزنید`, "error");
      if (!l.qty) return toast("تعداد هر ردیف را وارد کنید", "error");
      items.push(l.product_id ? { product_id: l.product_id, qty: l.qty, unit_cost: l.unit_cost || 0 }
        : { qty: l.qty, unit_cost: l.unit_cost || 0, new_product: { name: l.label, brand: l.brand, category: l.category, price: l.price || 0 } });
    }
    if (!items.length) return toast("حداقل یک کالا وارد کنید", "error");
    const btn = root.querySelector("#save");
    btn.disabled = true;
    try {
      await api("/api/erp/purchases", { method: "POST", body: { ...f, account_id: Number(f.account_id) || null, items } });
      toast("خرید ثبت شد و موجودی اضافه شد");
      s.close();
      refreshMe();
      done && done();
    } catch (e) { btn.disabled = false; }
  };
  return s;
}
