// System settings (owners only): Bale/Telegram notifications for every module, system health and backups.
import { $, api, bindChoices, choiceChips, delegate, fa, formData, html, icon, jdate, raw, toast } from "../kit.js";

const TABS = [
  { key: "notify", label: "اعلان در بله / تلگرام", ico: "bot" },
  { key: "system", label: "سیستم و پشتیبان", ico: "server" },
];
const size = (b) => (b > 1048576 ? `${fa((b / 1048576).toFixed(1))} مگابایت` : `${fa(Math.max(1, Math.round(b / 1024)))} کیلوبایت`);

export async function render(view, params, { setTitle }) {
  setTitle("تنظیمات", "اعلان‌ها، وضعیت سیستم و پشتیبان‌ها");
  let tab = params[0] || "notify";
  const draw = async () => {
    view.innerHTML = String(html`<div class="stack">
      <div class="chips scroll">${TABS.map((t) => html`<a class="chip ${t.key === tab ? "on" : ""}" href="#/settings/${t.key}">${icon(t.ico, "sm")}${t.label}</a>`)}</div>
      <div id="tab"><div class="skeleton" style="height:300px"></div></div></div>`);
    const el = $("#tab", view);
    if (tab === "notify") await notifyTab(el);
    if (tab === "system") await systemTab(el);
  };
  await draw();
  return { onParams: (p) => { tab = p[0] || "notify"; draw(); } };
}

async function notifyTab(el) {
  const n = await api("/api/notify");
  const groups = {};
  for (const k of n.kinds) (groups[k.module_name] ||= []).push(k);
  el.innerHTML = String(html`<div class="grid side">
    <section class="card">
      <div class="card-head"><h2>${icon("bot")} پیام فوری در بله یا تلگرام</h2>
        <p>هر وقت فروشی ثبت شد، محصولی تمام شد، قیمت رقبا بروز شد یا ویدیویی آماده شد، یک پیام کوتاه می‌آید. «بله» در ایران بدون فیلترشکن کار می‌کند.</p></div>
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
        <div class="step"><div class="s-body small">در بله با <b class="ltr">@botfather</b> گفتگو کنید، «/newbot» بزنید و یک ربات بسازید. توکنی که می‌دهد را اینجا بچسبانید و ذخیره کنید.</div></div>
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

async function systemTab(el) {
  const s = await api("/api/system");
  el.innerHTML = String(html`<div class="grid side">
    <div class="stack">
      <section class="card">
        <div class="card-head"><h2>${icon("database")} پشتیبان‌ها</h2><span class="spacer"></span>
          <button class="btn sm soft" id="now">${icon("database", "sm")} همین الان</button>
          <a class="btn sm primary" href="/api/system/backup.zip">${icon("download", "sm")} دانلود همه پایگاه‌داده‌ها</a>
          <p>هر شب ساعت ۳:۱۵ از همه بخش‌ها (و عکس رسیدها و فایل‌های استودیو) پشتیبان گرفته و ${fa(s.backup_keep_days)} روز نگه داشته می‌شود.
            ${s.next_backup ? `پشتیبان بعدی: ${jdate(s.next_backup.slice(0, 10), { year: false })} ساعت ${fa(s.next_backup.slice(11, 16))}` : ""}</p></div>
        ${s.backups.length ? html`<div class="table-wrap"><table class="t"><thead><tr><th>تاریخ</th><th>فایل‌ها</th><th class="n">حجم</th></tr></thead><tbody>
          ${s.backups.map((b) => html`<tr><td class="nowrap">${jdate(b.name)}</td><td class="small ltr" style="text-align:right">${b.files.join("، ")}</td><td class="n">${size(b.size)}</td></tr>`)}
          </tbody></table></div>` : html`<p class="small muted">هنوز پشتیبانی گرفته نشده.</p>`}
        <div class="callout warn mt16">${icon("triangle-alert")}<div>پشتیبان‌ها روی همین سرور هستند. هر چند وقت یک بار «دانلود همه پایگاه‌داده‌ها» را بزنید و جای امن (مثلاً گوگل‌درایو یا هارد) نگه دارید.</div></div>
      </section>
    </div>
    <section class="card">
      <div class="card-head"><h2>${icon("server")} وضعیت سیستم</h2></div>
      <div class="list">
        <div class="list-item"><div class="grow">نسخه</div><b class="ltr">${s.version}</b></div>
        <div class="list-item"><div class="grow">Python / SQLite</div><span class="ltr small">${s.python} / ${s.sqlite}</span></div>
        <div class="list-item"><div class="grow">بخش‌های فعال</div><span class="small">${s.modules.map((m) => m.name).join("، ")}</span></div>
        ${s.databases.map((d) => html`<div class="list-item"><div class="grow"><span class="ltr">${d.name}.db</span> <span class="tiny muted">نسخه طرح ${fa(d.version)}</span></div><span class="small">${size(d.size)}</span></div>`)}
        ${s.public_url ? html`<div class="list-item"><div class="grow">آدرس</div><span class="ltr small">${s.public_url}</span></div>` : ""}
      </div>
    </section>
  </div>`);
  $("#now", el).onclick = async (e) => {
    e.target.disabled = true;
    try {
      await api("/api/system/backup", { method: "POST" });
      toast("پشتیبان گرفته شد");
      systemTab(el);
    } finally { e.target.disabled = false; }
  };
}
