// Unified home: deliberately quiet. The greeting and today's headline sit in the top bar; below it, the few things
// people actually do from here (quick actions), the four numbers that matter, one list of what needs attention from
// every module (and unfinished setup, for owners), and the latest activity.
// Modules feed it through `glance(data, role)` → { headline?, stats?: [...], alerts?: [...] } (see ARCHITECTURE.md).
import { $, api, delegate, emptyState, fa, feedItem, html, icon, isOwner, jdate, on, state } from "../kit.js";
import { ITEMS, openSetup } from "../setup.js";

export async function render(view, params, { setTitle }) {
  const me = state.me;
  const hour = new Date().getHours();
  const greet = hour < 5 ? "شب بخیر" : hour < 12 ? "صبح بخیر" : hour < 17 ? "روز بخیر" : "عصر بخیر";
  const date = jdate(me.today, { weekday: true, year: false });
  setTitle(`${greet}، ${me.user.name}`, date);
  const registry = state.registry || {};
  const mods = me.modules.map((m) => registry[m.id]).filter((m) => m && m.def);
  const quick = mods.flatMap((m) => (m.def.quick ? m.def.quick(m.info.role) : []));

  view.innerHTML = String(html`<div class="home">
    ${quick.length ? html`<nav class="actions" aria-label="کارهای سریع">${quick.slice(0, 5).map((q) => html`<a class="action" href="${q.href}">
      <span class="a-ico ${q.tone || "indigo"}">${icon(q.ico)}</span><span>${q.label}</span></a>`)}</nav>` : ""}
    <section class="stat-strip" id="stats" aria-label="آمار"><div class="skeleton" style="height:64px;width:100%"></div></section>
    <div class="home-cols">
      <section class="card">
        <div class="card-head"><h2>${icon("list-checks")} نیاز به توجه</h2><span id="todo-count"></span></div>
        <div class="todo" id="todo"><div class="skeleton" style="height:120px"></div></div>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("history")} آخرین رویدادها</h2><span class="spacer"></span><a class="btn xs ghost" href="#/activity">همه ${icon("chevron-left", "sm")}</a></div>
        <div class="feed" id="feed"><div class="skeleton" style="height:160px"></div></div>
      </section>
    </div>
    ${!mods.length ? emptyState("lock", "هنوز به بخشی دسترسی ندارید", "از مدیر بخواهید در «تیم و دسترسی‌ها» برایتان دسترسی فعال کند.") : ""}
  </div>`);
  delegate(view, "click", "[data-setup]", (e, el) => { e.preventDefault(); openSetup(el.dataset.setup, () => loadTodo()); });

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
    setTitle(`${greet}، ${me.user.name}`, headline ? `${date} — ${headline}` : date);
    const stats = glances.flatMap((g) => g.stats || []).slice(0, 4);
    const el = $("#stats", view);
    if (!el) return;
    el.hidden = !stats.length;
    el.innerHTML = String(html`${stats.map((s) => html`<a class="stat ${s.tone || ""}" ${s.href ? html`href="${s.href}"` : ""}>
      <span class="s-label">${s.label}</span><b class="s-value num">${s.value}</b><span class="s-unit">${s.unit || ""}</span></a>`)}`);
  };
  let setup = null;
  const loadSetup = async () => { setup = isOwner() ? await api("/api/setup", { quiet: true }).catch(() => null) : null; };
  const loadTodo = async () => {
    await loadSetup();
    drawTodo();
  };
  const drawTodo = () => {
    const el = $("#todo", view);
    if (!el) return;
    const items = [];
    for (const g of glances) {
      if (g.error) items.push({ tone: "bad", ico: "circle-alert", text: `${g.mod.info.name}: ${g.error}`, href: `#/${g.mod.info.id}` });
      for (const a of g.alerts || []) items.push(a);
    }
    if (setup) {
      for (const it of ITEMS.filter((i) => !i.optional && !setup[i.key]?.ok)) {
        items.push({ tone: "warn", ico: it.ico, text: `${it.title} تنظیم نشده`, sub: it.need, setup: it.key });
      }
    }
    const order = { bad: 0, warn: 1, info: 2, ok: 3 };
    items.sort((a, b) => (order[a.tone] ?? 2) - (order[b.tone] ?? 2));
    $("#todo-count", view).innerHTML = items.length ? String(html`<span class="badge ${items.some((i) => i.tone === "bad") ? "bad" : "warn"}">${fa(items.length)}</span>`) : "";
    el.innerHTML = items.length ? String(html`${items.map((a) => html`<a class="todo-item" href="${a.href || "#/settings"}" ${a.setup ? html`data-setup="${a.setup}"` : ""}>
        <span class="t-ico ${a.tone || "info"}">${icon(a.ico || "info", "sm")}</span>
        <span class="grow"><span class="t-text">${a.text}</span>${a.sub ? html`<span class="t-sub">${a.sub}</span>` : ""}</span>
        ${icon("chevron-left", "sm")}</a>`)}`)
      : String(html`<div class="todo-clear">${icon("circle-check")}<div><b>همه چیز مرتب است</b><p class="small muted">موردی برای رسیدگی نیست.</p></div></div>`);
  };
  const loadFeed = async () => {
    const items = await api("/api/activity?limit=6", { quiet: true }).catch(() => []);
    const feed = $("#feed", view);
    if (feed) feed.innerHTML = items.length ? String(html`${items.map((a) => feedItem(a, { showModule: true }))}`)
      : String(emptyState("history", "هنوز رویدادی نیست"));
  };
  await Promise.all([loadGlances(), loadSetup(), loadFeed()]);
  drawTodo();

  let timer;
  const off = on("live", (ev) => {
    if (!["activity", "crawl", "generation", "refresh"].includes(ev.type)) return;
    clearTimeout(timer);
    timer = setTimeout(async () => { await loadGlances(); drawTodo(); loadFeed(); }, 1200);
  });
  return () => { off(); clearTimeout(timer); };
}
