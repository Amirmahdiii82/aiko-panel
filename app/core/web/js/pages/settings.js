// Settings (owners only). What every part of the app shares — site connection, proxy, notification bot, backups,
// OpenRouter — comes first, with the same checklist and forms as the home page (setup.js). Then system health and the
// settings of each module (rendered here from the module's own settings page).
import { $, api, fa, html, icon, jdate, raw, state, toast } from "../kit.js";
import { renderForm, setupCard } from "../setup.js";

const CORE_TABS = [
  { key: "setup", label: "راه‌اندازی", ico: "circle-check" },
  { key: "connections", label: "سایت و اتصال‌ها", ico: "plug" },
  { key: "notify", label: "اعلان‌ها", ico: "bot" },
  { key: "backup", label: "پشتیبان", ico: "database" },
  { key: "drive", label: "رسیدها در گوگل درایو", ico: "folder" },
  { key: "system", label: "سیستم", ico: "server" },
];
// module tabs: which modules have their own settings, and the label shown here
const MODULE_TABS = { erp: { label: "فروشگاه و حسابداری", ico: "store" }, media: { label: "استودیو", ico: "clapperboard" } };
const size = (b) => (b > 1048576 ? `${fa((b / 1048576).toFixed(1))} مگابایت` : `${fa(Math.max(1, Math.round(b / 1024)))} کیلوبایت`);

function tabs() {
  const mods = Object.entries(MODULE_TABS).filter(([id]) => state.registry?.[id]?.def?.pages?.settings)
    .map(([id, t]) => ({ key: id, ...t, module: true }));
  return [...CORE_TABS, ...mods];
}

export async function render(view, params, { setTitle }) {
  setTitle("تنظیمات", "تنظیمات مشترک همه بخش‌ها، و تنظیمات هر بخش");
  let tab = params[0] || "setup";
  let sub = params.slice(1);
  let cleanup = null;
  const draw = async () => {
    cleanup?.();
    cleanup = null;
    const all = tabs();
    if (!all.some((t) => t.key === tab)) tab = "setup";
    const chip = (t) => html`<a class="chip ${t.key === tab ? "on" : ""}" href="#/settings/${t.key}">${icon(t.ico, "sm")}${t.label}</a>`;
    view.innerHTML = String(html`<div class="stack">
      <div class="chips scroll">${all.filter((t) => !t.module).map(chip)}
        ${all.some((t) => t.module) ? html`<span class="small muted" style="align-self:center;padding:0 6px">بخش‌ها:</span>${all.filter((t) => t.module).map(chip)}` : ""}</div>
      <div id="tab"><div class="skeleton" style="height:300px"></div></div></div>`);
    const el = $("#tab", view);
    if (tab === "setup") await setupCard(el);
    else if (tab === "connections") connectionsTab(el);
    else if (tab === "notify") await notifyTab(el);
    else if (tab === "backup") await backupTab(el);
    else if (tab === "drive") { el.innerHTML = String(formCard("drive", "folder", "رسیدها در گوگل درایو")); fillForms(el); }
    else if (tab === "system") await systemTab(el);
    else cleanup = await moduleTab(el, tab, sub);
  };
  await draw();
  return {
    onParams: (p) => { tab = p[0] || "setup"; sub = p.slice(1); draw(); },
    cleanup: () => cleanup?.(),
  };
}

const formCard = (key, ico, title) => html`<section class="card"><div class="card-head"><h2>${icon(ico)} ${title}</h2></div>
  <div data-form="${key}"><div class="skeleton" style="height:180px"></div></div></section>`;
const fillForms = (el) => el.querySelectorAll("[data-form]").forEach((box) => renderForm(box.dataset.form, box));

/** A module's own settings page, shown inside the main settings (its tab links stay under #/settings/<id>). */
async function moduleTab(el, id, params) {
  const m = state.registry[id];
  if (!m.entered) { await m.def.enter?.(); m.entered = true; }
  const page = await m.def.pages.settings();
  const result = await page.render(el, params, { setTitle: () => {}, base: `#/settings/${id}`, embedded: true, module: id });
  return typeof result === "function" ? result : result?.cleanup || null;
}

function connectionsTab(el) {
  el.innerHTML = String(html`<div class="grid g2">
    ${formCard("woo", "globe", "سایت (ووکامرس)")}
    <div class="stack">${formCard("proxy", "shield", "پروکسی خروجی")}${formCard("openrouter", "key-round", "OpenRouter (استودیو محتوا)")}</div>
  </div>`);
  fillForms(el);
}

async function notifyTab(el) {
  const n = await api("/api/notify");
  const groups = {};
  for (const k of n.kinds) (groups[k.module_name] ||= []).push(k);
  el.innerHTML = String(html`<div class="grid g2">
    ${formCard("bot", "bot", "ربات اعلان‌ها")}
    <section class="card">
      <div class="card-head"><h2>${icon("bell")} برای چه چیزهایی پیام بیاید</h2></div>
      <div class="stack s12">${Object.entries(groups).map(([name, kinds]) => html`<div class="inset">
        <div class="label" style="margin-bottom:8px">${name}</div>
        <div class="stack s8">${kinds.map((k) => html`<label class="check small"><span class="switch"><input type="checkbox" data-kind="${k.key}" ${k.on ? raw("checked") : ""}><span></span></span>${k.label}</label>`)}</div>
      </div>`)}</div>
      <button class="btn primary mt16" id="kinds">${icon("check")} ذخیره</button>
    </section>
  </div>`);
  fillForms(el);
  $("#kinds", el).onclick = async () => {
    const kinds = {};
    el.querySelectorAll("[data-kind]").forEach((c) => { kinds[c.dataset.kind] = c.checked; });
    await api("/api/notify", { method: "PUT", body: { kinds } });
    toast("ذخیره شد");
  };
}

async function backupTab(el) {
  const s = await api("/api/system");
  el.innerHTML = String(html`<div class="grid g2">
    ${formCard("backup", "send", "پشتیبان در کانال تلگرام")}
    <section class="card">
      <div class="card-head"><h2>${icon("database")} پشتیبان روی سرور</h2><span class="spacer"></span>
        <button class="btn sm soft" id="now">${icon("database", "sm")} همین الان</button>
        <a class="btn sm primary" href="/api/system/backup.zip">${icon("download", "sm")} دانلود</a>
        <p>هر شب ساعت ۳:۱۵ از همه بخش‌ها (و عکس رسیدها و فایل‌های استودیو) پشتیبان گرفته و ${fa(s.backup_keep_days)} روز نگه داشته می‌شود.</p></div>
      ${s.backups.length ? html`<div class="table-wrap"><table class="t"><thead><tr><th>تاریخ</th><th class="n">حجم</th></tr></thead><tbody>
        ${s.backups.map((b) => html`<tr><td class="nowrap">${/^\d{4}-\d{2}-\d{2}$/.test(b.name) ? jdate(b.name) : html`<span class="ltr small">${b.name}</span>`}</td><td class="n">${size(b.size)}</td></tr>`)}
        </tbody></table></div>` : html`<p class="small muted">هنوز پشتیبانی گرفته نشده.</p>`}
    </section>
  </div>`);
  fillForms(el);
  $("#now", el).onclick = async (e) => {
    e.target.disabled = true;
    try {
      await api("/api/system/backup", { method: "POST" });
      toast("پشتیبان گرفته شد");
      backupTab(el);
    } finally { e.target.disabled = false; }
  };
}

async function systemTab(el) {
  const s = await api("/api/system");
  el.innerHTML = String(html`<section class="card" style="max-width:720px">
      <div class="card-head"><h2>${icon("server")} وضعیت سیستم</h2></div>
      <div class="list">
        <div class="list-item"><div class="grow">نسخه</div><b class="ltr">${s.version}</b></div>
        <div class="list-item"><div class="grow">Python / SQLite</div><span class="ltr small">${s.python} / ${s.sqlite}</span></div>
        <div class="list-item"><div class="grow">بخش‌های فعال</div><span class="small">${s.modules.map((m) => m.name).join("، ")}</span></div>
        ${s.databases.map((d) => html`<div class="list-item"><div class="grow"><span class="ltr">${d.name}.db</span> <span class="tiny muted">نسخه طرح ${fa(d.version)}</span></div><span class="small">${size(d.size)}</span></div>`)}
        ${s.public_url ? html`<div class="list-item"><div class="grow">آدرس</div><span class="ltr small">${s.public_url}</span></div>` : ""}
      </div>
    </section>`);
}
