// Running costs (packaging, ads, hosting, ...) with receipt photos. Stock purchases belong in "خرید کالا".
import { $, api, compact, confirmBox, debounce, delegate, fa, html, icon, jdate, num, on, sheet, toast, toman } from "/static/js/kit.js";
import { barList, bindChoices, bindDates, bindMoney, bindUploads, choiceChips, dateField, emptyState, formData, moneyField, receiptLink, uploadField } from "/static/js/kit.js";
import { periodChips, periodRange } from "/static/js/kit.js";
import { accountChoice, erp } from "../erp.js";

export async function render(view, params, { setTitle }) {
  setTitle("هزینه‌ها", "رسید کارت‌خوان یا فاکتور را عکس بگیرید و ثبت کنید");
  const f = { period: "month", category: "", q: "" };
  let rows = [];
  view.innerHTML = String(html`<div class="stack">
    <div class="card tight stack s12">
      <div class="row">
        <div class="input-wrap" style="flex:1;min-width:220px">${icon("search")}<input class="input" id="q" placeholder="شرح، دسته یا یادداشت…"></div>
        <button class="btn primary" id="new">${icon("plus")} ثبت هزینه</button>
      </div>
      <div id="periods"></div>
    </div>
    <div class="grid side">
      <section class="card" id="list"></section>
      <section class="card" id="cats"></section>
    </div>
  </div>`);
  async function load() {
    const r = periodRange(f.period);
    rows = await api(`/api/erp/expenses?${new URLSearchParams({ start: r.start, end: r.end, q: f.q })}`, { quiet: true });
    draw();
  }
  function draw() {
    $("#periods", view).innerHTML = String(periodChips(f.period));
    const running = rows.filter((r) => !r.is_inventory);
    const byCat = {};
    running.forEach((r) => { byCat[r.category] = (byCat[r.category] || 0) + r.amount; });
    const cats = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
    const total = running.reduce((s, r) => s + r.amount, 0);
    const stock = rows.filter((r) => r.is_inventory).reduce((s, r) => s + r.amount, 0);
    $("#cats", view).innerHTML = String(html`<div class="card-head"><h2>${icon("chart-pie")} بر اساس دسته</h2></div>
      <div class="money-big">${num(total)} <span class="small muted">تومان</span></div>
      <p class="small muted">هزینه‌های جاری این بازه${stock ? html`، به‌علاوه ${compact(stock)} خرید کالا (قدیمی)` : ""}</p>
      <div class="mt16">${cats.length ? barList(cats, { label: (c) => c[0], value: (c) => c[1] }) : ""}</div>
      ${f.category ? html`<button class="btn sm ghost mt12" data-cat="">${icon("x", "sm")} حذف فیلتر دسته</button>` : ""}`);
    const list = rows.filter((r) => !f.category || r.category === f.category);
    const el = $("#list", view);
    if (!list.length) {
      el.innerHTML = String(emptyState("receipt", "هزینه‌ای در این بازه نیست", "", html`<button class="btn primary mt8" data-new>${icon("plus")} ثبت هزینه</button>`));
      return;
    }
    el.innerHTML = String(html`<div class="chips scroll" style="margin-bottom:12px">
        <button class="chip ${!f.category ? "on" : ""}" data-cat="">همه</button>
        ${cats.map(([c]) => html`<button class="chip ${f.category === c ? "on" : ""}" data-cat="${c}">${c}</button>`)}</div>
      <div class="table-wrap"><table class="t responsive">
      <thead><tr><th>تاریخ</th><th>دسته</th><th>شرح</th><th>پرداخت از</th><th class="n">مبلغ</th><th></th></tr></thead>
      <tbody>${list.map((r) => html`<tr class="clickable" data-open="${r.id}">
        <td class="nowrap">${jdate(r.date, { year: false })}</td>
        <td><span class="badge ${r.is_inventory ? "info" : "orchid"}">${r.category}</span></td>
        <td class="m-full small">${r.description || ""}${r.note ? html` <span class="muted">، <bdi>${r.note}</bdi></span>` : ""}</td>
        <td class="small">${r.account_name || "—"}</td>
        <td class="n bold">${num(r.amount)}</td>
        <td>${receiptLink(r.receipt)}</td></tr>`)}</tbody></table></div>`);
  }
  await load();
  $("#q", view).addEventListener("input", debounce((e) => { f.q = e.target.value; load(); }, 300));
  delegate(view, "click", "[data-period]", (e, el) => { f.period = el.dataset.period; load(); });
  delegate(view, "click", "[data-cat]", (e, el) => { f.category = el.dataset.cat; draw(); });
  delegate(view, "click", "[data-open]", (e, el) => { if (!e.target.closest("a")) location.hash = `#/erp/expenses/${el.dataset.open}`; });
  delegate(view, "click", "#new, [data-new]", () => { location.hash = "#/erp/expenses/new"; });

  let drawer = null;
  const openFromParams = (p) => {
    if (drawer) { drawer.close(); drawer = null; }
    if (p[0] === "new") drawer = openExpenseForm(null, load);
    else if (p[0]) {
      const row = rows.find((r) => r.id === Number(p[0]));
      if (row) drawer = openExpenseForm(row, load);
    }
  };
  openFromParams(params);
  const off = on("live:erp", (ev) => { if (ev.type === "refresh" && ev.scope === "expenses") load(); });
  return { cleanup: () => { off(); drawer && drawer.close(); }, onParams: openFromParams };
}

export function openExpenseForm(e = null, done) {
  const cats = erp.me.settings.expense_categories || [];
  const allCats = e && !cats.includes(e.category) ? [...cats, e.category] : cats;
  const s = sheet({
    title: e ? "ویرایش هزینه" : "ثبت هزینه",
    onClose: () => { if (/^#\/expenses\/./.test(location.hash)) history.replaceState(null, "", "#/erp/expenses"); },
    body: html`<div class="stack s12" id="ef">
      ${moneyField({ name: "amount", label: "مبلغ", value: e?.amount || "", big: true, required: true, autofocus: !e })}
      <div class="field"><label>دسته *</label>${choiceChips("category", allCats.map((c) => ({ value: c, label: c })), e?.category || "")}</div>
      <div class="field"><label>شرح</label><input class="input" name="description" value="${e?.description || ""}" placeholder="مثلاً: ۱۰۰ عدد جعبه پستی"></div>
      <div class="field"><label>از کدام حساب پرداخت شد؟</label>${accountChoice("account_id", e ? e.account_id : erp.me.user.account_id)}</div>
      <div class="form-grid">
        ${dateField({ name: "date", label: "تاریخ", value: e?.date || erp.me.today })}
        ${uploadField({ name: "receipt", value: e?.receipt || "" })}
      </div>
      <div class="field"><label>یادداشت</label><input class="input" name="note" value="${e?.note || ""}"></div>
      <label class="check small"><input type="checkbox" name="is_inventory" ${e?.is_inventory ? "checked" : ""}> این پول برای خرید کالای فروشی بوده (در سود و زیان حساب نمی‌شود)</label>
      ${e?.sale_id ? html`<div class="callout">${icon("info")}<div>این پورسانت خودکار فروش است.</div></div>` : ""}
    </div>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ${e ? "ذخیره" : "ثبت هزینه"}</button><button class="btn ghost" data-close>انصراف</button>
      ${e && !e.sale_id ? html`<span class="spacer"></span><button class="btn danger sm" id="del">${icon("trash-2", "sm")} حذف</button>` : ""}`,
  });
  const root = s.root;
  bindMoney(root); bindDates(root); bindChoices(root); bindUploads(root);
  root.querySelector("#save").onclick = async () => {
    const f = formData(root.querySelector("#ef"));
    if (!f.amount) return toast("مبلغ را وارد کنید", "error");
    if (!f.category) return toast("دسته را انتخاب کنید", "error");
    const body = { ...f, account_id: Number(f.account_id) || null };
    const btn = root.querySelector("#save");
    btn.disabled = true;
    try {
      if (e) await api(`/api/erp/expenses/${e.id}`, { method: "PUT", body });
      else await api("/api/erp/expenses", { method: "POST", body });
      toast(e ? "ذخیره شد" : `هزینه ${toman(f.amount)} ثبت شد`);
      s.close();
      done && done();
    } catch (err) { btn.disabled = false; }
  };
  root.querySelector("#del")?.addEventListener("click", async () => {
    if (!(await confirmBox(`هزینه «${e.category}» به مبلغ ${toman(e.amount)} حذف شود؟`, { danger: true, okText: "حذف" }))) return;
    await api(`/api/erp/expenses/${e.id}`, { method: "DELETE" });
    toast("حذف شد");
    s.close();
    done && done();
  });
  return s;
}
export { fa };
