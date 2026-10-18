// Shared setup (owners): everything the whole app shares, as one checklist with one small form per item.
// The home page shows the checklist; each row opens its form in a sheet, right there. The Settings page
// shows the same forms, so there is exactly one place in the code (and one way for the owner) to set each thing.
import { $, api, delegate, fa, html, icon, jdate, raw, sheet, timeOf, toast } from "./kit.js";

const when = (ts) => (ts ? `${jdate(ts.slice(0, 10), { year: false })} ساعت ${timeOf(ts)}` : "");
const digits = (v) => String(v || "").replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d));

export const ITEMS = [
  { key: "woo", ico: "globe", title: "سایت (ووکامرس)", need: "برای موجودی، سفارش‌ها و فروش‌های سایت و قیمت رقبا",
    done: (s) => `وصل — ${s.woo.url.replace(/^https?:\/\//, "")}` },
  { key: "proxy", ico: "shield", title: "پروکسی خروجی", need: "لازم برای تلگرام و OpenRouter (از ایران فیلترند)",
    done: () => "تلگرام و OpenRouter از این مسیر می‌روند" },
  { key: "bot", ico: "bot", title: "ربات اعلان‌ها", need: "پیام فوری برای فروش، تمام شدن موجودی و…",
    done: (s) => `${s.bot.bot === "telegram" ? "تلگرام" : "بله"} — پیام‌ها به ${fa(s.bot.chat_ids.split(",").filter(Boolean).length)} چت می‌رود` },
  { key: "backup", ico: "database", title: "پشتیبان در کانال تلگرام", need: "هر ساعت یک نسخه از همه داده‌ها بیرون از سرور",
    done: (s) => (s.backup.last_at ? `آخرین ارسال ${when(s.backup.last_at)}` : `روشن — هر ${fa(s.backup.hours)} ساعت`) },
  { key: "openrouter", ico: "key-round", title: "OpenRouter (استودیو محتوا)", optional: true, need: "فقط برای ساخت تصویر و ویدیو",
    done: (s) => `کلید ذخیره شده ${s.openrouter.key_hint}` },
];

function rowState(it, s) {
  if (it.key === "backup" && s.backup.enabled && s.backup.last_ok === false) return { cls: "bad", label: "خطا", text: s.backup.last_error };
  if (s[it.key].ok) return { cls: "ok", label: "آماده", text: it.done(s) };
  return { cls: it.optional ? "" : "warn", label: it.optional ? "اختیاری" : "تنظیم نشده", text: it.need };
}

/** The checklist card. `compact` hides it behind one line once everything required is ready. */
export async function setupCard(el, { compact = false } = {}) {
  const s = await api("/api/setup", { quiet: true }).catch(() => null);
  if (!s) { el.innerHTML = ""; return; }
  const required = ITEMS.filter((i) => !i.optional);
  const ready = required.filter((i) => rowState(i, s).cls === "ok").length;
  const allOk = ready === required.length;
  const rows = html`<div class="list">${ITEMS.map((it) => {
    const st = rowState(it, s);
    return html`<div class="list-item">
      <span class="m-ico sm">${icon(it.ico)}</span>
      <div class="grow" style="min-width:0"><div class="title small">${it.title}</div>
        <div class="sub ellipsis ${st.cls === "bad" ? "bad-ink" : ""}" title="${st.text}">${st.text}</div></div>
      <span class="badge ${st.cls}">${st.cls === "ok" ? icon("check") : ""}${st.label}</span>
      <button class="btn xs ${st.cls === "ok" ? "ghost" : "primary"}" data-setup="${it.key}">${st.cls === "ok" ? "ویرایش" : "تنظیم"}</button>
    </div>`;
  })}</div>`;
  el.innerHTML = String(html`<section class="card">
    <div class="card-head"><h2>${icon("settings")} راه‌اندازی و وضعیت</h2>
      <span class="badge ${allOk ? "ok" : "warn"}">${allOk ? html`${icon("check")}همه آماده` : `${fa(ready)} از ${fa(required.length)} آماده`}</span>
      <span class="spacer"></span><a class="btn xs ghost" href="#/settings">همه تنظیمات ${icon("chevron-left", "sm")}</a>
      <p>تنظیماتی که همه بخش‌ها با هم استفاده می‌کنند. هر کدام را با یک دکمه همین‌جا تنظیم کنید.</p></div>
    ${compact && allOk ? html`<details><summary class="small muted" style="cursor:pointer">نمایش جزئیات</summary>${rows}</details>` : rows}
  </section>`);
  delegate(el, "click", "[data-setup]", (e, b) => openSetup(b.dataset.setup, () => setupCard(el, { compact })));
}

/** One item's form in a sheet. */
export function openSetup(key, onDone) {
  const it = ITEMS.find((i) => i.key === key);
  const s = sheet({ title: it.title, body: '<div class="skeleton" style="height:220px"></div>' });
  const body = s.root.querySelector(".sheet-body");
  renderForm(key, body, { onSaved: () => onDone?.(), close: s.close });
  return s;
}

/** Render one item's form into any element (a sheet on the home page, a card on the Settings page). */
export async function renderForm(key, el, opts = {}) {
  await FORMS[key](el, opts);
}

const FORMS = {
  async woo(el, { onSaved }) {
    const w = (await api("/api/integrations")).woo;
    el.innerHTML = String(html`<form class="stack s12" autocomplete="off">
      <p class="small muted">یک بار وارد کنید؛ «فروشگاه و حسابداری» و «قیمت رقبا» هر دو از همین اتصال استفاده می‌کنند.</p>
      <div class="field"><label>آدرس سایت</label><input class="input ltr" name="url" value="${w.url || ""}" placeholder="https://aikocosmetics.ir"></div>
      <div class="field"><label>Consumer key</label><input class="input ltr" name="key" value="${w.key || ""}" placeholder="ck_…"></div>
      <div class="field"><label>Consumer secret</label><input class="input ltr" name="secret" type="password" placeholder="${w.secret_set ? "ذخیره شده (برای تغییر، جدید را بنویسید)" : "cs_…"}"></div>
      <label class="check small"><input type="checkbox" name="query_auth" ${w.query_auth ? raw("checked") : ""}> ارسال کلید در آدرس (فقط اگر خطای ۴۰۱ گرفتید)</label>
      <p class="hint">کلید را از: پیشخوان وردپرس ← ووکامرس ← پیکربندی ← پیشرفته ← REST API ← «افزودن کلید» با دسترسی <b>خواندن/نوشتن</b>.</p>
      <button class="btn primary" type="submit">${icon("check")} ذخیره و آزمایش</button>
    </form>`);
    $("form", el).onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target;
      await api("/api/integrations", { method: "PUT", body: { woo: { url: f.url.value, key: f.key.value, secret: f.secret.value, query_auth: f.query_auth.checked } } });
      try {
        const r = await api("/api/integrations/woo/test", { method: "POST" });
        toast(`سایت وصل شد ✓${r.products != null ? ` — ${fa(r.products)} محصول` : ""}`);
      } catch (err) { /* the error toast is already shown */ }
      onSaved?.();
      FORMS.woo(el, { onSaved });
    };
  },

  async proxy(el, { onSaved }) {
    const c = await api("/api/integrations");
    el.innerHTML = String(html`<form class="stack s12" autocomplete="off">
      <p class="small muted">تلگرام و OpenRouter از ایران فیلترند؛ هر ارتباطی با آن‌ها (ربات تلگرام، پشتیبان در کانال، استودیو) از این پروکسی می‌رود.
        سایت خودمان، بله و سایت‌های رقبا مستقیم خوانده می‌شوند.</p>
      <div class="field"><label>آدرس پروکسی</label><input class="input ltr" name="proxy_url" value="${c.proxy_url || ""}" placeholder="http://127.0.0.1:10809"></div>
      <button class="btn primary" type="submit">${icon("check")} ذخیره و آزمایش</button>
      <div class="inset small" id="presult" hidden></div>
    </form>`);
    $("form", el).onsubmit = async (e) => {
      e.preventDefault();
      const btn = e.target.querySelector("button");
      btn.disabled = true;
      const out = $("#presult", el);
      try {
        await api("/api/integrations", { method: "PUT", body: { proxy_url: e.target.proxy_url.value.trim() } });
        out.hidden = false;
        out.textContent = "در حال آزمایش…";
        const r = await api("/api/integrations/proxy/test", { method: "POST" });
        const mark = (v) => (v === "ok" ? "✓ وصل" : `✗ ${v}`);
        out.textContent = `${r.proxy ? "با پروکسی" : "بدون پروکسی"} — تلگرام: ${mark(r.telegram)}، OpenRouter: ${mark(r.openrouter)}`;
        onSaved?.();
      } finally { btn.disabled = false; }
    };
  },

  async openrouter(el, { onSaved }) {
    const c = await api("/api/integrations");
    el.innerHTML = String(html`<form class="stack s12" autocomplete="off">
      <p class="small muted">فقط برای «استودیو محتوا». کلید روی سرور می‌ماند و دیگر نشان داده نمی‌شود. سقف هزینه ماهانه در تنظیمات استودیو است.</p>
      <div class="field"><label>کلید API ${c.openrouter.key_set ? html`<span class="badge ok">${icon("check")}ذخیره شده <span class="ltr">${c.openrouter.key_hint}</span></span>` : ""}</label>
        <input class="input ltr" name="key" placeholder="${c.openrouter.key_set ? "برای تغییر، کلید جدید را بچسبانید" : "sk-or-v1-…"}"></div>
      <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره</button>
        ${c.openrouter.key_set ? html`<button class="btn ghost" type="button" data-clear>${icon("trash-2", "sm")} حذف کلید</button>` : ""}</div>
    </form>`);
    $("form", el).onsubmit = async (e) => {
      e.preventDefault();
      const key = e.target.key.value.trim();
      if (!key) return toast("کلید را وارد کنید", "error");
      await api("/api/integrations", { method: "PUT", body: { openrouter_key: key } });
      toast("ذخیره شد");
      onSaved?.();
      FORMS.openrouter(el, { onSaved });
    };
    $("[data-clear]", el)?.addEventListener("click", async () => {
      await api("/api/integrations", { method: "PUT", body: { clear_openrouter_key: true } });
      toast("کلید حذف شد");
      onSaved?.();
      FORMS.openrouter(el, { onSaved });
    });
  },

  async bot(el, { onSaved }) {
    const n = await api("/api/notify");
    el.innerHTML = String(html`<form class="stack s12" autocomplete="off">
      <div class="field"><label>پیام‌رسان</label><select class="select" name="bot">
        <option value="bale" ${n.bot !== "telegram" ? raw("selected") : ""}>بله (داخلی، بدون پروکسی)</option>
        <option value="telegram" ${n.bot === "telegram" ? raw("selected") : ""}>تلگرام (از پروکسی)</option></select></div>
      <div class="field"><label>توکن ربات</label><input class="input ltr" name="token" placeholder="${n.token_set ? "ذخیره شده (برای تغییر، توکن جدید را بچسبانید)" : "123456789:ABC…"}"></div>
      <div class="field"><label>چه کسانی پیام بگیرند (شناسه چت)</label>
        <div class="row nowrap"><input class="input ltr" name="chat_ids" value="${n.chat_ids || ""}" style="flex:1"><button class="btn sm soft" type="button" data-find>${icon("search", "sm")} پیدا کن</button></div>
        <div class="hint" data-chats>ربات را باز کنید و «/start» بفرستید، بعد «پیدا کن» را بزنید.</div></div>
      <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره</button>
        <button class="btn soft" type="button" data-test>${icon("send", "sm")} پیام آزمایشی</button></div>
      <p class="tiny muted">کدام رویدادها پیام بدهند را در «تنظیمات ← اعلان‌ها» انتخاب کنید.</p>
    </form>`);
    const form = $("form", el);
    const body = () => ({ bot: form.bot.value, token: form.token.value.trim(), chat_ids: form.chat_ids.value.trim() });
    const save = () => api("/api/notify", { method: "PUT", body: body() });
    form.onsubmit = async (e) => { e.preventDefault(); await save(); toast("ذخیره شد"); onSaved?.(); };
    $("[data-test]", el).onclick = async () => { await save(); await api("/api/notify/test", { method: "POST" }); toast("پیام آزمایشی فرستاده شد"); onSaved?.(); };
    $("[data-find]", el).onclick = async () => {
      await save();
      const chats = await api("/api/notify/chats");
      $("[data-chats]", el).innerHTML = chats.length
        ? String(html`${chats.map((c) => html`<button type="button" class="chip" data-chat="${c.id}" style="margin:4px">${c.name || c.id} <span class="ltr tiny">${c.id}</span></button>`)}`)
        : "پیامی پیدا نشد. اول به ربات «/start» بفرستید و دوباره بزنید.";
    };
    delegate(el, "click", "[data-chat]", (e, b) => {
      const ids = form.chat_ids.value.split(",").map((x) => x.trim()).filter(Boolean);
      if (!ids.includes(b.dataset.chat)) ids.push(b.dataset.chat);
      form.chat_ids.value = ids.join(", ");
    });
  },

  async backup(el, { onSaved }) {
    const t = await api("/api/backup/telegram");
    el.innerHTML = String(html`<form class="stack s12" autocomplete="off">
      ${!t.proxy ? html`<div class="callout warn">${icon("triangle-alert")}<div>اول «پروکسی خروجی» را تنظیم کنید؛ بدون آن تلگرام از سرور در دسترس نیست.</div></div>` : ""}
      <div class="steps">
        <div class="step"><div class="s-body small">در تلگرام یک کانال <b>خصوصی</b> بسازید.</div></div>
        <div class="step"><div class="s-body small">ربات را در کانال <b>مدیر</b> کنید (اجازه ارسال پیام) و یک پیام در کانال بفرستید.</div></div>
        <div class="step"><div class="s-body small">«پیدا کن» را بزنید، کانال را انتخاب کنید و «ذخیره و ارسال آزمایشی».</div></div>
      </div>
      <div class="field"><label>ربات</label><input class="input ltr" name="token"
        placeholder="${t.token_set ? "ربات جدا ذخیره شده (برای تغییر، توکن جدید)" : t.uses_notify_token ? "خالی = همان ربات اعلان‌ها (پیشنهادی)" : "توکن ربات تلگرام: 123456789:ABC…"}"></div>
      <div class="field"><label>کانال</label>
        <div class="row nowrap"><input class="input ltr" name="chat_id" value="${t.chat_id || ""}" placeholder="-1001234567890" style="flex:1">
          <button class="btn sm soft" type="button" data-find>${icon("search", "sm")} پیدا کن</button></div>
        <div class="hint" data-chans></div></div>
      <div class="row">
        <label class="check bold"><span class="switch"><input type="checkbox" name="enabled" ${t.enabled || !t.chat_id ? raw("checked") : ""}><span></span></span> ارسال خودکار</label>
        <label class="small row nowrap">هر <input class="input sm" name="hours" value="${fa(t.hours || 1)}" style="width:56px" inputmode="numeric"> ساعت</label>
      </div>
      <button class="btn primary" type="submit">${icon("send")} ذخیره و ارسال آزمایشی</button>
      <div class="inset small" data-status>${t.last_at
        ? html`آخرین ارسال: ${when(t.last_at)} — ${t.last_ok ? html`<span class="ok-ink">موفق</span>` : html`<span class="bad-ink">ناموفق: ${t.last_error}</span>`}`
        : "هنوز ارسالی انجام نشده."}</div>
      <p class="tiny muted">فایل‌ها همه داده‌ها و کلیدهای اتصال را دارند؛ کانال باید خصوصی بماند.</p>
    </form>`);
    const form = $("form", el);
    const body = () => ({ enabled: form.enabled.checked, chat_id: form.chat_id.value.trim(), token: form.token.value.trim(),
      hours: Number(digits(form.hours.value)) || 1 });
    const save = () => api("/api/backup/telegram", { method: "PUT", body: body() });
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (!form.chat_id.value.trim()) return toast("اول کانال را با «پیدا کن» انتخاب کنید", "error");
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      $("[data-status]", el).textContent = "در حال ارسال…";
      try {
        await save();
        await api("/api/backup/telegram/send", { method: "POST" });
        toast("پشتیبان در کانال فرستاده شد ✓");
      } catch (err) { /* error toast shown; the status line below explains */ }
      finally { btn.disabled = false; onSaved?.(); FORMS.backup(el, { onSaved }); }
    };
    $("[data-find]", el).onclick = async () => {
      await save();
      const chats = await api("/api/backup/telegram/chats");
      $("[data-chans]", el).innerHTML = chats.length
        ? String(html`${chats.map((c) => html`<button type="button" class="chip" data-chan="${c.id}" style="margin:4px">${c.name || c.id} <span class="ltr tiny">${c.id}</span></button>`)}`)
        : "کانالی پیدا نشد. ربات را مدیر کانال کنید، یک پیام در کانال بفرستید و دوباره بزنید.";
    };
    delegate(el, "click", "[data-chan]", (e, b) => { form.chat_id.value = b.dataset.chan; });
  },
};
