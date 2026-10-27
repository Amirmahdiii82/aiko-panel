// ERP settings (Settings → فروشگاه و حسابداری): staff profiles (commission, partner, default account), partners &
// accounts, channel defaults, categories, and the Excel export. Logins, module access, bot notifications, backups and
// passwords are other sections of Settings, or the profile page.
import { $, api, confirmBox, delegate, esc, fa, html, icon, isOwner, parseNum, sheet, toast } from "/static/js/kit.js";
import { avatar, emptyState, formData, selectOptions } from "/static/js/kit.js";
import { openAccount } from "./money.js";
import { accountOptions, CHANNEL_ICON, erp, refreshMe } from "../erp.js";

const TABS = [
  { key: "staff", label: "فروشنده‌ها و پورسانت", ico: "users" },
  { key: "partners", label: "شرکا و حساب‌ها", ico: "handshake" },
  { key: "lists", label: "دسته‌ها و کانال‌ها", ico: "tag" },
  { key: "data", label: "خروجی اکسل", ico: "file-spreadsheet" },
];

export async function render(view, params, { setTitle, base = "#/settings/erp" }) {
  setTitle("تنظیمات فروشگاه");
  let tab = params[0] || "staff";
  const draw = async () => {
    view.innerHTML = String(html`<div class="stack">
      <div class="chips scroll">${TABS.map((t) => html`<a class="chip ${t.key === tab ? "on" : ""}" href="${base}/${t.key}">${icon(t.ico, "sm")}${t.label}</a>`)}</div>
      <div id="tab"><div class="skeleton" style="height:300px"></div></div></div>`);
    const el = $("#tab", view);
    if (tab === "staff") await staffTab(el);
    if (tab === "partners") await partnersTab(el);
    if (tab === "lists") listsTab(el);
    if (tab === "data") dataTab(el);
  };
  await draw();
  return { onParams: (p) => { tab = p[0] || "staff"; draw(); } };
}

// ---------------------------------------------------------------- staff (ERP profile of each user)
async function staffTab(el) {
  const users = await api("/api/erp/staff");
  el.innerHTML = String(html`<div class="grid side">
    <section class="card">
      <div class="card-head"><h2>${icon("users")} افراد با دسترسی به فروشگاه</h2><span class="spacer"></span>
        ${isOwner() ? html`<a class="btn sm primary" href="#/settings/team">${icon("user-plus", "sm")} کاربر جدید / دسترسی‌ها</a>` : ""}
        <p>ساخت کاربر، رمز و اینکه هر نفر به کدام بخش‌ها دسترسی دارد در «تیم و دسترسی‌ها» است. اینجا فقط اطلاعات فروشگاهی هر نفر.</p></div>
      <div class="list">${users.map((u) => html`<div class="list-item clickable" data-user="${u.id}">
        ${avatar(u.name)}<div class="grow"><div class="title">${u.name} <span class="muted small ltr">@${u.username}</span></div>
          <div class="sub">${u.role === "admin" ? "مدیر فروشگاه" : "فروشنده (فقط ثبت فروش و دیدن موجودی)"}${u.commission_pct ? `، پورسانت ${fa(u.commission_pct)}٪` : ""}${u.account_name ? `، ${u.account_name}` : ""}</div></div>
        ${u.active ? "" : html`<span class="badge">غیرفعال</span>`}${icon("chevron-left", "sm")}</div>`)}</div>
    </section>
    <section class="card">
      <h3>${icon("info", "sm")} فروشنده چیست؟</h3>
      <p class="small mt8" style="line-height:2">برای دوستی که از طرف شما می‌فروشد در «تیم و دسترسی‌ها» یک کاربر بسازید و نقش فروشگاه را «فروشنده» بگذارید.
        او از گوشی وارد می‌شود، فروش را ثبت می‌کند و همان لحظه:</p>
      <ul class="small" style="line-height:2;padding-inline-start:20px">
        <li>موجودی انبار کم می‌شود و اگر تمام شد در سایت هم ناموجود می‌شود،</li>
        <li>به شما اعلان می‌آید (در برنامه و اگر تنظیم کرده باشید در بله/تلگرام)،</li>
        <li>پول آن فروش در حساب «پول نزد …» می‌ماند تا وقتی تحویل بدهد (منهای پورسانت).</li>
      </ul>
      <p class="small muted">فروشنده قیمت خرید، سود و حساب‌های شما را نمی‌بیند.</p>
    </section>
  </div>`);
  delegate(el, "click", "[data-user]", (e, row) => staffForm(users.find((u) => u.id === Number(row.dataset.user)), () => staffTab(el)));
}

function staffForm(u, done) {
  const s = sheet({
    title: `اطلاعات فروشگاهی ${u.name}`,
    body: html`<div class="stack s12" id="uf">
      <div class="field"><label>پورسانت از هر فروش (٪)</label><input class="input" name="commission_pct" data-num value="${fa(u.commission_pct || 0)}" inputmode="decimal"></div>
      ${u.role === "admin" ? html`<div class="form-grid">
        <div class="field"><label>شریک مربوط</label><select class="select" name="partner_id">${selectOptions(erp.me.partners.map((p) => ({ value: p.id, label: p.name })), u.partner_id, "—")}</select></div>
        <div class="field"><label>حساب پیش‌فرض پرداخت‌ها</label><select class="select" name="account_id">${accountOptions(u.account_id, { includeEmpty: "—" })}</select></div>
      </div>` : html`<p class="small muted">پول فروش‌های این فروشنده در حساب «پول نزد ${u.name}» ثبت می‌شود.</p>`}
    </div>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ذخیره</button><button class="btn ghost" data-close>انصراف</button>`,
  });
  s.root.querySelector("#save").onclick = async () => {
    const f = formData(s.root.querySelector("#uf"));
    const body = { commission_pct: f.commission_pct || 0 };
    if (u.role === "admin") Object.assign(body, { partner_id: Number(f.partner_id) || null, account_id: Number(f.account_id) || null });
    await api(`/api/erp/staff/${u.id}`, { method: "PUT", body });
    toast("ذخیره شد");
    s.close();
    await refreshMe();
    done && done();
  };
}

// ---------------------------------------------------------------- partners & accounts
async function partnersTab(el) {
  const money = await api("/api/erp/money");
  el.innerHTML = String(html`<div class="grid g2">
    <section class="card">
      <div class="card-head"><h2>${icon("handshake")} شرکا و سهم هر کدام</h2><p>جمع سهم‌ها باید ۱۰۰ باشد. تسویه شرکا بر همین اساس حساب می‌شود.</p></div>
      <div class="stack s12" id="pf">${erp.me.partners.map((p) => html`<div class="row nowrap" data-pid="${p.id}">
        ${avatar(p.name)}<input class="input" data-pname value="${p.name}" style="flex:1">
        <div class="input-wrap" style="width:120px"><input class="input has-suffix" data-pshare value="${fa(p.share)}" inputmode="decimal"><span class="suffix">٪</span></div></div>`)}</div>
      <button class="btn primary mt16" id="save-p">${icon("check")} ذخیره سهم‌ها</button>
    </section>
    <section class="card">
      <div class="card-head"><h2>${icon("wallet")} حساب‌ها</h2><span class="spacer"></span><button class="btn sm soft" id="add-acc">${icon("plus", "sm")} حساب جدید</button>
        <p>کارت‌های شخصی شرکا، درگاه سایت، صندوق نقدی و … — هر پرداخت و دریافتی به یکی از این‌ها نسبت داده می‌شود.</p></div>
      <div class="list">${money.accounts.map((a) => html`<div class="list-item clickable" data-acc="${a.id}">
        <span class="feed-icon">${icon(a.kind === "partner" ? "credit-card" : a.kind === "agent" ? "user" : "landmark")}</span>
        <div class="grow"><div class="title">${a.name}</div><div class="sub">${a.kind === "partner" ? `کارت شخصی ${a.partner_name || ""}` : a.kind === "agent" ? "پول نزد فروشنده" : "حساب فروشگاه"}${a.note ? "، " + a.note : ""}</div></div>
        ${a.active ? "" : html`<span class="badge">غیرفعال</span>`}${icon("pencil", "sm")}</div>`)}</div>
    </section>
  </div>`);
  $("#save-p", el).onclick = async () => {
    const body = [...el.querySelectorAll("[data-pid]")].map((r) => ({
      id: Number(r.dataset.pid), name: r.querySelector("[data-pname]").value, share: parseNum(r.querySelector("[data-pshare]").value),
    }));
    await api("/api/erp/partners", { method: "PUT", body });
    await refreshMe();
    toast("ذخیره شد");
  };
  $("#add-acc", el).onclick = () => openAccount(null, async () => { await refreshMe(); partnersTab(el); });
  delegate(el, "click", "[data-acc]", (e, row) => openAccount(money.accounts.find((a) => a.id === Number(row.dataset.acc)), async () => { await refreshMe(); partnersTab(el); }));
}

// ---------------------------------------------------------------- categories & channel defaults
function listsTab(el) {
  const st = erp.me.settings;
  const chanAcc = st.channel_accounts || {};
  const listEditor = (key, title, items) => html`<section class="card" data-list="${key}">
    <div class="card-head"><h2>${title}</h2></div>
    <div class="chips" data-items>${items.map((c) => html`<span class="chip">${c}<button class="btn icon xs ghost" data-del="${c}" aria-label="حذف ${c}" style="width:22px;height:22px">${icon("x", "sm")}</button></span>`)}</div>
    <div class="row nowrap mt12"><input class="input sm" data-new placeholder="مورد جدید"><button class="btn sm soft" data-add>${icon("plus", "sm")} افزودن</button></div>
  </section>`;
  el.innerHTML = String(html`<div class="stack">
    <section class="card">
      <div class="card-head"><h2>${icon("layers")} پول هر کانال فروش پیش‌فرض به کدام حساب می‌رود؟</h2>
        <p>موقع ثبت فروش همین حساب انتخاب می‌شود (قابل تغییر است). فروش دوستان همیشه به حساب «پول نزد …» خودشان می‌رود.</p></div>
      <div class="form-grid" id="chan">${Object.entries(erp.me.channels).filter(([k]) => k !== "agent").map(([k, label]) => html`<div class="field">
        <label>${icon(CHANNEL_ICON[k], "sm")} ${label}</label><select class="select" name="${k}">${accountOptions(chanAcc[k], { includeEmpty: "—" })}</select></div>`)}</div>
      <button class="btn primary mt16" id="save-chan">${icon("check")} ذخیره</button>
    </section>
    <div class="grid g2">
      ${listEditor("expense_categories", "دسته‌های هزینه", st.expense_categories || [])}
      ${listEditor("product_categories", "دسته‌های محصول", st.product_categories || [])}
    </div>
    <section class="card">
      <div class="card-head"><h2>${icon("store")} فروشگاه</h2></div>
      <div class="form-grid" id="shop">
        <div class="field"><label>نام فروشگاه</label><input class="input" name="name" value="${st.shop?.name || ""}"></div>
        <div class="field"><label>حد پیش‌فرض هشدار موجودی (برای محصولات جدید)</label><input class="input" name="low_stock" data-num value="${fa(st.shop?.low_stock ?? 2)}"></div>
      </div>
      <button class="btn primary mt16" id="save-shop">${icon("check")} ذخیره</button>
    </section>
  </div>`);
  $("#save-chan", el).onclick = async () => {
    const f = formData($("#chan", el));
    const body = {};
    Object.entries(f).forEach(([k, v]) => { if (v) body[k] = Number(v); });
    await api("/api/erp/settings/channel_accounts", { method: "PUT", body });
    await refreshMe(); toast("ذخیره شد");
  };
  $("#save-shop", el).onclick = async () => {
    const f = formData($("#shop", el));
    await api("/api/erp/settings/shop", { method: "PUT", body: { name: f.name, low_stock: f.low_stock || 2 } });
    await refreshMe(); toast("ذخیره شد");
  };
  const saveList = async (key, items) => {
    await api(`/api/erp/settings/${key}`, { method: "PUT", body: items });
    await refreshMe();
    listsTab(el);
  };
  delegate(el, "click", "[data-list] [data-del]", (e, b) => {
    const key = b.closest("[data-list]").dataset.list;
    saveList(key, (erp.me.settings[key] || []).filter((c) => c !== b.dataset.del));
  });
  delegate(el, "click", "[data-list] [data-add]", (e, b) => {
    const box = b.closest("[data-list]");
    const v = box.querySelector("[data-new]").value.trim();
    if (v) saveList(box.dataset.list, [...(erp.me.settings[box.dataset.list] || []), v]);
  });
}

// ---------------------------------------------------------------- data
function dataTab(el) {
  el.innerHTML = String(html`<div class="grid g2">
    <section class="card"><h2>${icon("file-spreadsheet")} خروجی اکسل</h2>
      <p class="small muted mt8">همه محصولات، فروش‌ها، خریدها، هزینه‌ها و حساب‌ها در یک فایل اکسل (تاریخ‌ها شمسی).</p>
      <a class="btn soft mt16" href="/api/erp/export.xlsx">${icon("download")} دانلود اکسل</a></section>
    <section class="card"><h2>${icon("database")} نسخه پشتیبان</h2>
      <p class="small muted mt8">پشتیبان همه بخش‌ها هر شب خودکار گرفته می‌شود و هر چند ساعت در کانال بله یا تلگرام هم می‌رود.</p>
      ${isOwner() ? html`<a class="btn soft mt16" href="#/settings/backup">${icon("database")} پشتیبان‌ها</a>` : ""}</section>
  </div>`);
}

export { esc, confirmBox, emptyState };
