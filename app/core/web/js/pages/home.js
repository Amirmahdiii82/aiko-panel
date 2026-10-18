// Unified home: greeting, quick actions from every module, one summary card per module, recent activity.
import { $, api, delegate, emptyState, esc, feedItem, html, icon, isOwner, jdate, on, state } from "../kit.js";
import { setupCard } from "../setup.js";

const COLORS = ["", "c2", "c3", "c4"];

export async function render(view, params, { setTitle }) {
  const me = state.me;
  const hour = new Date().getHours();
  const greet = hour < 12 ? "صبح بخیر" : hour < 17 ? "روز بخیر" : "عصر بخیر";
  setTitle("خانه", jdate(me.today, { weekday: true }));
  const registry = state.registry || {};
  const mods = me.modules.map((m) => registry[m.id]).filter((m) => m && m.def);
  const quick = mods.flatMap((m) => (m.def.quick ? m.def.quick(m.info.role) : []));

  view.innerHTML = String(html`<div class="stack">
    <section class="hero">
      <span class="blob-deco" style="width:200px;height:200px;top:-80px;left:-60px"></span>
      <span class="blob-deco" style="width:90px;height:90px;bottom:-30px;left:120px;opacity:.1"></span>
      <h1>${greet}، ${me.user.name}</h1>
      <p class="muted mt8">همه بخش‌های آیکو در یک جا: ${mods.map((m) => m.info.name).join("، ") || "—"}</p>
      ${quick.length ? html`<div class="quick">${quick.slice(0, 4).map((q) => html`<button data-link="${q.href}">
        <span class="q-ico" style="background:linear-gradient(135deg,${q.color || "#ADA4DC"},#5B4B87)">${icon(q.ico)}</span>
        <span>${q.label}<small>${q.sub || ""}</small></span></button>`)}</div>` : ""}
    </section>
    ${isOwner() ? html`<div id="setup"></div>` : ""}
    <div class="grid g2" id="mod-cards">
      ${mods.map((m, i) => html`<section class="card mod-card" data-mod-card="${m.info.id}">
        <div class="card-head"><span class="m-ico ${COLORS[i % COLORS.length]}">${icon(m.info.icon)}</span>
          <div><h2>${m.info.name}</h2><div class="small muted">${m.info.roles[m.info.role] || ""}</div></div>
          <span class="spacer"></span><a class="btn sm soft" href="#/${m.info.id}">ورود ${icon("chevron-left", "sm")}</a></div>
        <div class="mod-body"><div class="skeleton" style="height:84px"></div></div>
      </section>`)}
    </div>
    ${!mods.length ? emptyState("lock", "هنوز به بخشی دسترسی ندارید", "از مدیر بخواهید در «تیم و دسترسی‌ها» برایتان دسترسی فعال کند.") : ""}
    <section class="card">
      <div class="card-head"><h2>${icon("history")} آخرین رویدادها</h2><span class="spacer"></span><a class="btn xs ghost" href="#/activity">همه</a></div>
      <div class="feed" id="feed"><div class="skeleton" style="height:160px"></div></div>
    </section>
  </div>`);
  delegate(view, "click", "[data-link]", (e, el) => { if (el.dataset.link) location.hash = el.dataset.link; });

  const loadCards = async () => {
    let data = {};
    try { data = await api("/api/home", { quiet: true }); } catch (e) { /* cards show their own error */ }
    for (const m of mods) {
      const body = view.querySelector(`[data-mod-card="${m.info.id}"] .mod-body`);
      if (!body) continue;
      const d = data[m.info.id];
      try {
        body.innerHTML = !d ? `<p class="small muted">خلاصه‌ای برای این بخش نیست.</p>`
          : d.error ? `<p class="small bad-ink">${esc(d.error)}</p>`
            : m.def.home ? String(m.def.home(d, m.info.role)) : "";
      } catch (e) {
        console.error(e);
        body.innerHTML = `<p class="small bad-ink">نمایش خلاصه ناموفق بود</p>`;
      }
    }
  };
  const loadFeed = async () => {
    const items = await api("/api/activity?limit=10", { quiet: true }).catch(() => []);
    const feed = $("#feed", view);
    if (feed) feed.innerHTML = items.length ? String(html`${items.map((a) => feedItem(a, { showModule: true }))}`)
      : String(emptyState("history", "هنوز رویدادی نیست"));
  };
  const setupEl = $("#setup", view);
  await Promise.all([loadCards(), loadFeed(), setupEl ? setupCard(setupEl, { compact: true }) : null]);

  let timer;
  const off = on("live", (ev) => {
    if (ev.type !== "activity" && ev.type !== "crawl" && ev.type !== "generation" && ev.type !== "refresh") return;
    clearTimeout(timer);
    timer = setTimeout(() => { loadCards(); loadFeed(); }, 1200);
  });
  return () => { off(); clearTimeout(timer); };
}
