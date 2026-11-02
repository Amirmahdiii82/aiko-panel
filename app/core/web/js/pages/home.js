// Home: the whole business on one calm screen. Today's date as the title, quick actions, the four numbers that matter
// in one strip (the first is the answer, larger),
// one list of what needs attention from every module (and, for owners, unfinished setup — each links to its section
// in Settings), and the latest activity beside it.
// Modules feed it through `glance(data, role)` → { headline?, stats?: [...], alerts?: [...] } (see ARCHITECTURE.md).
import { $, api, delegate, emptyState, fa, feedItem, html, mixedModules, icon, isOwner, jdate, kpi, on, state, todoBadge, todoList } from "../kit.js";
import { ITEMS } from "../setup.js";

export async function render(view, params, { setTitle }) {
  const me = state.me;
  // the title names the day, not the person: what the screen is about, read at a glance
  const date = jdate(me.today, { weekday: true, year: false });
  setTitle(date, "");
  const registry = state.registry || {};
  const mods = me.modules.map((m) => registry[m.id]).filter((m) => m && m.def);
  const quick = mods.flatMap((m) => (m.def.quick ? m.def.quick(m.info.role) : []));

  view.innerHTML = String(html`<div class="home">
    ${quick.length ? html`<nav class="quick" aria-label="کارهای سریع">${quick.slice(0, 5).map((q) => html`<a href="${q.href}">
      <span class="q-ico">${icon(q.ico)}</span><span>${q.label}</span></a>`)}</nav>` : ""}
    <section class="kpi-strip" id="stats" aria-label="آمار">${[0, 1, 2, 3].map(() => html`<div class="skeleton" style="height:112px"></div>`)}</section>
    <div class="home-cols">
      <section class="card">
        <div class="card-head"><h2>${icon("list-checks")} نیاز به توجه</h2><span class="spacer"></span><span id="todo-count"></span></div>
        <div id="todo"><div class="skeleton" style="height:120px"></div></div>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("history")} آخرین رویدادها</h2><span class="spacer"></span>
          <a class="btn xs ghost" href="#/activity">همه ${icon("chevron-left", "sm")}</a></div>
        <div class="feed" id="feed"><div class="skeleton" style="height:160px"></div></div>
      </section>
    </div>
    ${!mods.length ? emptyState("lock", "هنوز به بخشی دسترسی ندارید", "از مدیر بخواهید در «تنظیمات ← تیم و دسترسی‌ها» برایتان دسترسی فعال کند.") : ""}
  </div>`);

  let glances = [];
  const loadGlances = async () => {
    let data = {};
    try { data = await api("/api/home", { quiet: true }); } catch (e) { /* each module's part just stays empty */ }
    glances = mods.map((m) => {
      const d = data[m.info.id];
      if (!d || !m.def.glance) return { mod: m, error: d?.error };
      if (d.error) return { mod: m, error: d.error };
      try { return { mod: m, ...m.def.glance(d, m.info.role) }; } catch (e) { console.error(e); return { mod: m, error: "نمایش ناموفق بود" }; }
    });
    const headline = glances.find((g) => g.headline)?.headline;
    setTitle(date, headline || "");
    const stats = glances.flatMap((g) => g.stats || []).slice(0, 4);
    const el = $("#stats", view);
    if (!el) return;
    el.hidden = !stats.length;
    el.innerHTML = String(html`${stats.map((s, i) => kpi({ ...s, hero: i === 0, tone: i ? s.tone : "" }))}`);
  };
  let setup = null;
  const loadSetup = async () => { setup = isOwner() ? await api("/api/setup", { quiet: true }).catch(() => null) : null; };
  const drawTodo = () => {
    const el = $("#todo", view);
    if (!el) return;
    // what needs doing today, and separately what is still to set up: one-time setup must not drown a real problem
    const items = [], setupLeft = [];
    for (const g of glances) {
      if (g.error) items.push({ tone: "bad", ico: "circle-alert", text: `${g.mod.info.name}: ${g.error}`, href: `#/${g.mod.info.id}` });
      for (const a of g.alerts || []) (a.setup ? setupLeft.push(a.short || a.text) : items.push(a));
    }
    const du = setup?.drive?.ok && setup.drive.usage;
    if (du && (du.errors || du.held)) {
      items.push({ tone: "warn", ico: "folder", text: `${fa(du.errors + du.held)} رسید به گوگل درایو نرفته`,
        sub: du.held ? "سقف فضای رسیدها پر شده" : "ارسال ناموفق بود", href: "#/settings/drive" });
    }
    if (setup?.backup?.enabled && setup.backup.last_ok === false) {
      items.push({ tone: "bad", ico: "database", text: "پشتیبان به کانال نرسید", sub: setup.backup.last_error, href: "#/settings/backup" });
    }
    if (setup) {
      for (const it of ITEMS.filter((i) => !i.optional && !setup[i.key]?.ok)) setupLeft.unshift(it.title);
    }
    if (setupLeft.length) {
      items.push({ tone: "info", ico: "settings", text: `راه‌اندازی: ${fa(setupLeft.length)} مورد مانده`, sub: setupLeft.join("، "), href: "#/settings" });
    }
    $("#todo-count", view).innerHTML = String(todoBadge(items));
    el.innerHTML = String(todoList(items));
  };
  const loadFeed = async () => {
    const items = await api("/api/activity?limit=7", { quiet: true }).catch(() => []);
    const feed = $("#feed", view);
    if (feed) feed.innerHTML = items.length ? String(html`${items.map((a) => feedItem(a, { showModule: mixedModules(items) }))}`)
      : String(emptyState("history", "هنوز رویدادی نیست", "فروش، خرید و بروزرسانی‌ها اینجا می‌آیند."));
  };
  await Promise.all([loadGlances(), loadSetup(), loadFeed()]);
  drawTodo();
  delegate(view, "click", ".feed-item[data-link]", (e, el) => { if (el.dataset.link) location.hash = el.dataset.link; });

  let timer;
  const off = on("live", (ev) => {
    if (!["activity", "crawl", "generation", "refresh"].includes(ev.type)) return;
    clearTimeout(timer);
    timer = setTimeout(async () => { await loadGlances(); drawTodo(); loadFeed(); }, 1200);
  });
  return () => { off(); clearTimeout(timer); };
}
