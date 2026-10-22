// Financial statements: balance sheet, income statement and cash flow — one at a time, as plain accounting tables
// (labels right, amounts left, negatives in parentheses, a single rule above subtotals, a double rule under totals).
// The numbers come from the same ledger as every other page (statements.py).
import { $, api, delegate, fa, html, icon, num, storage } from "/static/js/kit.js";

const PERIODS = [
  { key: "month", label: "این ماه" }, { key: "last_month", label: "ماه قبل" }, { key: "3m", label: "سه ماه اخیر" },
  { key: "year", label: "امسال" }, { key: "all", label: "از ابتدا" },
];
const VIEWS = [
  { key: "balance", label: "ترازنامه", ico: "scale" },
  { key: "income", label: "سود و زیان", ico: "chart-column" },
  { key: "cash", label: "جریان نقدی", ico: "wallet" },
];
const money = (n) => (n == null ? "" : n < 0 ? `(${num(-n)})` : num(n));

export async function render(view, params, { setTitle }) {
  setTitle("صورت‌های مالی", "ترازنامه، سود و زیان و جریان نقدی — به تومان");
  let period = storage("fs-period") || "month";
  let which = storage("fs-view") || "balance";
  let data = null;
  view.innerHTML = String(html`<div class="stack">
    <div class="fs-bar">
      <div class="seg" id="views" role="tablist"></div>
      <div class="chips scroll" id="periods"></div>
      <a class="btn sm soft" id="xlsx" download>${icon("file-spreadsheet", "sm")} اکسل</a>
    </div>
    <section class="card fs-card" id="body"><div class="skeleton" style="height:360px"></div></section>
  </div>`);

  const draw = () => {
    $("#views", view).innerHTML = String(html`${VIEWS.map((v) => html`<button role="tab" aria-selected="${v.key === which}" class="${v.key === which ? "on" : ""}" data-view="${v.key}">${icon(v.ico, "sm")}${v.label}</button>`)}`);
    $("#periods", view).innerHTML = String(html`${PERIODS.map((p) => html`<button class="chip ${p.key === period ? "on" : ""}" data-p="${p.key}">${p.label}</button>`)}`);
    $("#xlsx", view).href = `/api/erp/statements.xlsx?period=${period}`;
    if (!data) return;
    $("#body", view).innerHTML = String(which === "balance" ? balance(data) : which === "income" ? income(data) : cash(data));
  };
  const load = async () => {
    data = null;
    draw();
    $("#body", view).innerHTML = '<div class="skeleton" style="height:360px"></div>';
    data = await api(`/api/erp/statements?period=${period}`);
    draw();
  };
  await load();
  delegate(view, "click", "[data-p]", (e, el) => { period = el.dataset.p; storage("fs-period", period); load(); });
  delegate(view, "click", "[data-view]", (e, el) => { which = el.dataset.view; storage("fs-view", which); draw(); });
}

function table(rows) {
  return html`<table class="fs"><tbody>${rows.map((r) => html`<tr class="${r.kind}">
    <th scope="row" style="padding-inline-start:${8 + r.indent * 18}px">${r.label}${r.hint ? html`<small>${r.hint}</small>` : ""}</th>
    <td class="${r.amount < 0 ? "neg" : ""}">${money(r.amount)}</td></tr>`)}</tbody></table>`;
}

function head(title, sub, extra = "") {
  return html`<div class="fs-head"><div><h2>${title}</h2><p>${sub}</p></div>${extra}</div>`;
}

function balance(d) {
  const b = d.balance;
  const left = b.assets.at(-1).amount, right = b.liabilities_equity.at(-1).amount;
  const ok = Math.abs(left - right) < 1;
  return html`${head("ترازنامه", `در ${d.as_of_label} — تومان`,
      html`<span class="badge ${ok ? "ok" : "bad"}">${icon(ok ? "check" : "triangle-alert")}${ok ? "تراز است" : "تراز نیست"}</span>`)}
    <div class="fs-split">
      <div>${table(b.assets)}</div>
      <div>${table(b.liabilities_equity)}</div>
    </div>`;
}

function income(d) {
  const mc = d.income.missing_cost || {};
  return html`${head("صورت سود و زیان", `${d.label} — تومان`)}
    ${mc.lines ? html`<div class="callout warn">${icon("triangle-alert")}<div>${fa(mc.lines)} ردیف فروش در این بازه قیمت خرید ندارد؛ سود بیشتر از واقع است.
      <a href="#/erp/products?f=nocost">وارد کردن قیمت خرید</a></div></div>` : ""}
    <div class="fs-narrow">${table(d.income.rows)}</div>`;
}

function cash(d) {
  return html`${head("صورت جریان نقدی", `${d.label} — حساب‌های فروشگاه و پول نزد فروشنده‌ها، تومان`)}
    <div class="fs-narrow">${table(d.cash.rows)}</div>
    <p class="tiny muted">کارت شخصی شرکا جزو نقد فروشگاه نیست؛ پرداخت از آن، آورده همان شریک حساب می‌شود.</p>`;
}
