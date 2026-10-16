// System settings (owners only), one place for the whole app: shared connections (WooCommerce, proxy, OpenRouter),
// Bale/Telegram notifications, backups (on the server and in a Telegram channel), system health, and the
// settings of every module (rendered here from the module's own settings page).
import { $, api, bindChoices, choiceChips, delegate, fa, formData, html, icon, jdate, raw, state, timeOf, toast } from "../kit.js";

const CORE_TABS = [
  { key: "connections", label: "اتصال‌ها", ico: "plug" },
  { key: "notify", label: "اعلان در بله / تلگرام", ico: "bot" },
  { key: "backup", label: "پشتیبان", ico: "database" },
  { key: "system", label: "سیستم", ico: "server" },
];
// module tabs: which modules have settings, and the label shown here
const MODULE_TABS = { erp: { label: "فروشگاه و حسابداری", ico: "store" }, media: { label: "استودیو", ico: "clapperboard" } };
const size = (b) => (b > 1048576 ? `${fa((b / 1048576).toFixed(1))} مگابایت` : `${fa(Math.max(1, Math.round(b / 1024)))} کیلوبایت`);
const when = (ts) => (ts ? `${jdate(ts.slice(0, 10), { year: false })} ساعت ${timeOf(ts)}` : "—");

function tabs() {
  const mods = Object.entries(MODULE_TABS).filter(([id]) => state.registry?.[id]?.def?.pages?.settings)
    .map(([id, t]) => ({ key: id, ...t, module: true }));
  return [...CORE_TABS, ...mods];
}

export async function render(view, params, { setTitle }) {
  setTitle("تنظیمات", "اتصال‌ها، اعلان‌ها، پشتیبان و تنظیمات همه بخش‌ها");
  let tab = params[0] || "connections";
  let sub = params.slice(1);
  let cleanup = null;
  const draw = async () => {
    cleanup?.();
    cleanup = null;
    const all = tabs();
    if (!all.some((t) => t.key === tab)) tab = "connections";
    view.innerHTML = String(html`<div class="stack">
      <div class="chips scroll">${all.map((t) => html`<a class="chip ${t.key === tab ? "on" : ""}" href="#/settings/${t.key}">${icon(t.ico, "sm")}${t.label}</a>`)}</div>
      <div id="tab"><div class="skeleton" style="height:300px"></div></div></div>`);
    const el = $("#tab", view);
    if (tab === "connections") await connectionsTab(el);
    else if (tab === "notify") await notifyTab(el);
    else if (tab === "backup") await backupTab(el);
    else if (tab === "system") await systemTab(el);
    else cleanup = await moduleTab(el, tab, sub);
  };
  await draw();
  return {
    onParams: (p) => { tab = p[0] || "connections"; sub = p.slice(1); draw(); },
    cleanup: () => cleanup?.(),
  };
}

/** A module's own settings page, shown inside the main settings (its tab links stay under #/settings/<id>). */
async function moduleTab(el, id, params) {
  const m = state.registry[id];
  if (!m.entered) { await m.def.enter?.(); m.entered = true; }
  const page = await m.def.pages.settings();
  const result = await page.render(el, params, { setTitle: () => {}, base: `#/settings/${id}`, embedded: true, module: id });
  return typeof result === "function" ? result : result?.cleanup || null;
}

// ---------------------------------------------------------------- connections
async function connectionsTab(el) {
  const c = await api("/api/integrations");
  const w = c.woo;
  el.innerHTML = String(html`<div class="grid side">
    <div class="stack">
      <section class="card">
        <div class="card-head"><h2>${icon("globe")} سایت (ووکامرس)</h2>
          ${w.configured ? html`<span class="badge ok">${icon("check")}وصل</span>` : html`<span class="badge warn">کلید وارد نشده</span>`}
          <p>یک بار وارد کنید؛ «فروشگاه و حسابداری» (موجودی، سفارش‌ها و فروش‌ها) و «قیمت رقبا» (محصولات خودمان) هر دو از همین اتصال استفاده می‌کنند.</p></div>
        <form class="stack s12" id="woo" autocomplete="off">
          <div class="field"><label>آدرس سایت</label><input class="input ltr" name="url" value="${w.url || ""}" placeholder="https://aikocosmetics.ir"></div>
          <div class="form-grid">
            <div class="field"><label>Consumer key</label><input class="input ltr" name="key" value="${w.key || ""}" placeholder="ck_…"></div>
            <div class="field"><label>Consumer secret</label><input class="input ltr" name="secret" type="password" placeholder="${w.secret_set ? "ذخیره شده (برای تغییر، جدید را بنویسید)" : "cs_…"}"></div>
          </div>
          <label class="check small"><input type="checkbox" name="query_auth" ${w.query_auth ? "checked" : ""}> ارسال کلید در آدرس (اگر خطای ۴۰۱ گرفتید)</label>
          <p class="hint">پیشخوان وردپرس ← ووکامرس ← پیکربندی ← پیشرفته ← REST API ← «افزودن کلید»، دسترسی <b>خواندن/نوشتن</b>.${w.currency ? html` واحد پول سایت: <b class="ltr">${w.currency}</b>` : ""}</p>
          <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره و آزمایش</button>
            <a class="btn ghost" href="#/erp/site">${icon("refresh-cw", "sm")} همگام‌سازی با سایت</a></div>
        </form>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("shield")} پروکسی خروجی</h2>
          <p>تلگرام و OpenRouter از ایران فیلتر هستند. هر ارتباطی با سرویس‌های خارجی (ربات تلگرام، پشتیبان در کانال تلگرام، استودیو محتوا) از این پروکسی می‌رود.
            سایت خودمان، بله و سایت‌های رقبا مستقیم و بدون پروکسی خوانده می‌شوند.</p></div>
        <form class="stack s12" id="proxy" autocomplete="off">
          <div class="field"><label>آدرس پروکسی</label><input class="input ltr" name="proxy_url" value="${c.proxy_url || ""}" placeholder="socks5://user:pass@host:1080 یا http://host:8080"></div>
          <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره</button>
            <button class="btn soft" type="button" id="ptest">${icon("zap", "sm")} آزمایش (تلگرام و OpenRouter)</button></div>
          <div class="hint" id="presult"></div>
        </form>
      </section>
    </div>
    <section class="card">
      <div class="card-head"><h2>${icon("key-round")} OpenRouter (استودیو محتوا)</h2>
        <p>کلید فقط روی سرور می‌ماند و به مرورگر برنمی‌گردد. سقف هزینه ماهانه در تب «استودیو» است.</p></div>
      <form class="stack s12" id="or" autocomplete="off">
        <div class="field"><label>کلید API ${c.openrouter.key_set ? html`<span class="badge ok">${icon("check")}ذخیره شده <span class="ltr">${c.openrouter.key_hint}</span></span>` : html`<span class="badge warn">تنظیم نشده</span>`}</label>
          <input class="input ltr" name="openrouter_key" placeholder="${c.openrouter.key_set ? "برای تغییر، کلید جدید را بچسبانید" : "sk-or-v1-…"}"></div>
        <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره</button>
          ${c.openrouter.key_set ? html`<button class="btn ghost" type="button" id="orclear">${icon("trash-2", "sm")} حذف کلید</button>` : ""}</div>
      </form>
    </section>
  </div>`);
  const save = (body) => api("/api/integrations", { method: "PUT", body });
  $("#woo", el).onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    await save({ woo: { url: f.url.value, key: f.key.value, secret: f.secret.value, query_auth: f.query_auth.checked } });
    toast("ذخیره شد؛ در حال آزمایش اتصال…", "info");
    try {
      const r = await api("/api/integrations/woo/test", { method: "POST" });
      toast(`اتصال برقرار شد ✓${r.products != null ? ` ${fa(r.products)} محصول` : ""}${r.currency ? `، واحد پول ${r.currency}` : ""}`);
    } catch (err) { /* toast already shown */ }
    connectionsTab(el);
  };
  $("#proxy", el).onsubmit = async (e) => { e.preventDefault(); await save({ proxy_url: e.target.proxy_url.value.trim() }); toast("ذخیره شد"); };
  $("#ptest", el).onclick = async (e) => {
    e.target.disabled = true;
    $("#presult", el).textContent = "در حال آزمایش…";
    try {
      await save({ proxy_url: $("#proxy", el).proxy_url.value.trim() });
      const r = await api("/api/integrations/proxy/test", { method: "POST" });
      const mark = (v) => (v === "ok" ? "✓ وصل" : `✗ ${v}`);
      $("#presult", el).textContent = `${r.proxy ? "با پروکسی" : "بدون پروکسی"} — تلگرام: ${mark(r.telegram)}، OpenRouter: ${mark(r.openrouter)}`;
    } finally { e.target.disabled = false; }
  };
  $("#or", el).onsubmit = async (e) => {
    e.preventDefault();
    const key = e.target.openrouter_key.value.trim();
    if (!key) return toast("کلید را وارد کنید", "error");
    await save({ openrouter_key: key });
    toast("ذخیره شد");
    connectionsTab(el);
  };
  $("#orclear", el)?.addEventListener("click", async () => { await save({ clear_openrouter_key: true }); toast("کلید حذف شد"); connectionsTab(el); });
}

// ---------------------------------------------------------------- notifications
async function notifyTab(el) {
  const n = await api("/api/notify");
  const groups = {};
  for (const k of n.kinds) (groups[k.module_name] ||= []).push(k);
  el.innerHTML = String(html`<div class="grid side">
    <section class="card">
      <div class="card-head"><h2>${icon("bot")} پیام فوری در بله یا تلگرام</h2>
        <p>هر وقت فروشی ثبت شد، محصولی تمام شد، قیمت رقبا بروز شد یا ویدیویی آماده شد، یک پیام کوتاه می‌آید. «بله» در ایران بدون فیلترشکن کار می‌کند؛ تلگرام از «پروکسی خروجی» (تب اتصال‌ها) می‌رود.</p></div>
      <div class="stack s12" id="nf">
        <div class="field"><label>پیام‌رسان</label>${choiceChips("bot", [{ value: "bale", label: "بله" }, { value: "telegram", label: "تلگرام" }], n.bot || "bale")}</div>
        <div class="field"><label>توکن ربات</label><input class="input ltr" name="token" placeholder="${n.token_set ? "ذخیره شده (برای تغییر، توکن جدید را بچسبانید)" : "123456789:ABC…"}" autocomplete="off"></div>
        <div class="field"><label>شناسه چت‌ها (با کاما جدا کنید)</label>
          <div class="row nowrap"><input class="input ltr" name="chat_ids" value="${n.chat_ids || ""}" style="flex:1"><button class="btn sm soft" id="find" type="button">${icon("search", "sm")} پیدا کن</button></div>
          <div class="hint" id="chats"></div></div>
        ${Object.entries(groups).map(([name, kinds]) => html`<div class="inset">
          <div class="label" style="margin-bottom:8px">${name}</div>
          <div class="stack s8">${kinds.map((k) => html`<label class="check small"><span class="switch"><input type="checkbox" data-kind="${k.key}" ${k.on ? raw("checked") : ""}><span></span></span>${k.label}</label>`)}</div>
        </div>`)}
      </div>
      <div class="row mt16"><button class="btn primary" id="save">${icon("check")} ذخیره</button><button class="btn ghost" id="test">${icon("send", "sm")} پیام آزمایشی</button></div>
    </section>
    <section class="card">
      <h3>راه‌اندازی در ۲ دقیقه</h3>
      <div class="steps mt12">
        <div class="step"><div class="s-body small">در بله (یا تلگرام) با <b class="ltr">@botfather</b> گفتگو کنید، «/newbot» بزنید و یک ربات بسازید. توکنی که می‌دهد را اینجا بچسبانید و ذخیره کنید.</div></div>
        <div class="step"><div class="s-body small">ربات خودتان را باز کنید و «/start» یا هر پیامی بفرستید (هر شریک جدا). برای گروه، ربات را به گروه اضافه کنید و در گروه پیامی بفرستید.</div></div>
        <div class="step"><div class="s-body small">دکمه «پیدا کن» را بزنید و چت‌ها را انتخاب کنید، ذخیره و «پیام آزمایشی».</div></div>
      </div>
    </section>
  </div>`);
  bindChoices(el);
  const body = () => {
    const f = formData($("#nf", el));
    const kinds = {};
    el.querySelectorAll("[data-kind]").forEach((c) => { kinds[c.dataset.kind] = c.checked; });
    return { bot: f.bot, token: f.token, chat_ids: f.chat_ids, kinds };
  };
  $("#save", el).onclick = async () => { await api("/api/notify", { method: "PUT", body: body() }); toast("ذخیره شد"); };
  $("#test", el).onclick = async () => { await api("/api/notify/test", { method: "POST" }); toast("پیام فرستاده شد؛ بله/تلگرام را ببینید"); };
  $("#find", el).onclick = async () => {
    await api("/api/notify", { method: "PUT", body: body() });
    const chats = await api("/api/notify/chats");
    $("#chats", el).innerHTML = chats.length ? String(html`${chats.map((c) => html`<button type="button" class="chip" data-chat="${c.id}" style="margin:4px">${c.name || c.id} <span class="ltr tiny">${c.id}</span></button>`)}`)
      : "پیامی پیدا نشد. اول به ربات پیام بدهید و دوباره بزنید.";
  };
  delegate(el, "click", "[data-chat]", (e, b) => {
    const input = el.querySelector("[name=chat_ids]");
    const ids = input.value.split(",").map((x) => x.trim()).filter(Boolean);
    if (!ids.includes(b.dataset.chat)) ids.push(b.dataset.chat);
    input.value = ids.join(", ");
  });
}

// ---------------------------------------------------------------- backups
async function backupTab(el) {
  const s = await api("/api/system");
  const t = s.telegram;
  el.innerHTML = String(html`<div class="grid side">
    <section class="card">
      <div class="card-head"><h2>${icon("send")} پشتیبان در کانال تلگرام</h2>
        ${t.enabled ? html`<span class="badge ok">${icon("check")}روشن — هر ${fa(t.hours)} ساعت</span>` : html`<span class="badge">خاموش</span>`}
        <p>یک فایل فشرده از همه پایگاه‌داده‌ها (فروش‌ها، انبار، حساب‌ها، کاربران، قیمت‌ها، استودیو) به یک کانال خصوصی تلگرام فرستاده می‌شود؛ اگر سرور از دست برود، داده‌ها آنجا هست.
          ارسال از «پروکسی خروجی» (تب اتصال‌ها) انجام می‌شود.</p></div>
      ${!t.proxy ? html`<div class="callout warn" style="margin-bottom:12px">${icon("triangle-alert")}<div>پروکسی خروجی تنظیم نشده؛ از سرور ایران تلگرام در دسترس نیست. <a href="#/settings/connections">تنظیم پروکسی</a></div></div>` : ""}
      <form class="stack s12" id="tg" autocomplete="off">
        <label class="check bold"><span class="switch"><input type="checkbox" name="enabled" ${t.enabled ? "checked" : ""}><span></span></span> ارسال خودکار</label>
        <div class="field"><label>توکن ربات تلگرام</label>
          <input class="input ltr" name="token" placeholder="${t.token_set ? "ذخیره شده (برای تغییر، توکن جدید را بچسبانید)" : t.uses_notify_token ? "خالی = همان ربات اعلان‌ها" : "123456789:ABC…"}"></div>
        <div class="field"><label>شناسه کانال</label>
          <div class="row nowrap"><input class="input ltr" name="chat_id" value="${t.chat_id || ""}" placeholder="-1001234567890 یا @mychannel" style="flex:1">
            <button class="btn sm soft" type="button" id="tgfind">${icon("search", "sm")} پیدا کن</button></div>
          <div class="hint" id="tgchats">ربات را در کانال «مدیر» (با اجازه ارسال پیام) کنید، یک پیام در کانال بفرستید و «پیدا کن» را بزنید.</div></div>
        <div class="field"><label>هر چند ساعت یک بار</label><input class="input" name="hours" value="${fa(t.hours || 1)}" inputmode="numeric" style="max-width:120px"></div>
        <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره</button>
          <button class="btn soft" type="button" id="tgsend">${icon("send", "sm")} همین الان بفرست</button></div>
      </form>
      <div class="inset small mt16">
        ${t.last_at ? html`آخرین ارسال: ${when(t.last_at)} — ${t.last_ok ? html`<span class="ok-ink">موفق (${size(t.last_size || 0)})</span>` : html`<span class="bad-ink">ناموفق: ${t.last_error}</span>`}` : "هنوز ارسالی انجام نشده."}
      </div>
      <p class="tiny muted mt8">کانال را خصوصی نگه دارید: فایل‌ها شامل همه داده‌ها و کلیدهای اتصال هستند.</p>
    </section>
    <section class="card">
      <div class="card-head"><h2>${icon("database")} پشتیبان روی سرور</h2><span class="spacer"></span>
        <button class="btn sm soft" id="now">${icon("database", "sm")} همین الان</button>
        <a class="btn sm primary" href="/api/system/backup.zip">${icon("download", "sm")} دانلود همه پایگاه‌داده‌ها</a>
        <p>هر شب ساعت ۳:۱۵ از همه بخش‌ها (و عکس رسیدها و فایل‌های استودیو) پشتیبان گرفته و ${fa(s.backup_keep_days)} روز نگه داشته می‌شود.
          ${s.next_backup ? `پشتیبان بعدی: ${jdate(s.next_backup.slice(0, 10), { year: false })} ساعت ${fa(s.next_backup.slice(11, 16))}` : ""}</p></div>
      ${s.backups.length ? html`<div class="table-wrap"><table class="t"><thead><tr><th>تاریخ</th><th>فایل‌ها</th><th class="n">حجم</th></tr></thead><tbody>
        ${s.backups.map((b) => html`<tr><td class="nowrap">${/^\d{4}-\d{2}-\d{2}$/.test(b.name) ? jdate(b.name) : b.name}</td><td class="small ltr" style="text-align:right">${b.files.join("، ")}</td><td class="n">${size(b.size)}</td></tr>`)}
        </tbody></table></div>` : html`<p class="small muted">هنوز پشتیبانی گرفته نشده.</p>`}
    </section>
  </div>`);
  const form = $("#tg", el);
  const body = () => ({ enabled: form.enabled.checked, chat_id: form.chat_id.value.trim(), token: form.token.value.trim(),
    hours: Number(String(form.hours.value).replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d))) || 1 });
  form.onsubmit = async (e) => { e.preventDefault(); await api("/api/backup/telegram", { method: "PUT", body: body() }); toast("ذخیره شد"); backupTab(el); };
  $("#tgsend", el).onclick = async (e) => {
    e.target.disabled = true;
    try {
      await api("/api/backup/telegram", { method: "PUT", body: body() });
      await api("/api/backup/telegram/send", { method: "POST" });
      toast("پشتیبان در کانال فرستاده شد");
    } finally { e.target.disabled = false; backupTab(el); }
  };
  $("#tgfind", el).onclick = async () => {
    await api("/api/backup/telegram", { method: "PUT", body: body() });
    const chats = await api("/api/backup/telegram/chats");
    $("#tgchats", el).innerHTML = chats.length ? String(html`${chats.map((c) => html`<button type="button" class="chip" data-tgchat="${c.id}" style="margin:4px">${c.name || c.id} <span class="ltr tiny">${c.id}</span></button>`)}`)
      : "چیزی پیدا نشد. ربات را مدیر کانال کنید، یک پیام در کانال بفرستید و دوباره بزنید.";
  };
  delegate(el, "click", "[data-tgchat]", (e, b) => { form.chat_id.value = b.dataset.tgchat; });
  $("#now", el).onclick = async (e) => {
    e.target.disabled = true;
    try {
      await api("/api/system/backup", { method: "POST" });
      toast("پشتیبان گرفته شد");
      backupTab(el);
    } finally { e.target.disabled = false; }
  };
}

// ---------------------------------------------------------------- system
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
