// App shell: login, module rail + navigation panel, routing, live updates and the notification bell.
//
// Routes:  #/                    unified home            (core)
//          #/activity|team|settings|profile             (core pages)
//          #/<module>/<page>/<params...>?query          (a module page, e.g. #/erp/sales/12)
//
// Each module ships /m/<id>/index.js whose default export describes it to the shell:
//   { id, nav(role), mobile(role), pages: { "": () => import(...) }, allowed(role, page), enter(), action(role),
//     quick(role), home(data, role), css: [] }
import { $, api, avatar, closeAllSheets, delegate, emit, emptyState, esc, feedItem, html, icon, isOwner, on, sheet, state, toast } from "./kit.js";

const CORE_PAGES = {
  "": () => import("./pages/home.js"),
  activity: () => import("./pages/activity.js"),
  team: () => import("./pages/team.js"),
  settings: () => import("./pages/settings.js"),
  profile: () => import("./pages/profile.js"),
};
const OWNER_ONLY = new Set(["team", "settings"]);
const homeNav = () => [
  { href: "", label: "خانه", ico: "house" },
  { href: "activity", label: "رویدادها", ico: "history" },
  ...(isOwner() ? [{ section: "مدیریت" }, { href: "team", label: "تیم و دسترسی‌ها", ico: "users" },
    { href: "settings", label: "تنظیمات و پشتیبان", ico: "settings" }] : []),
  { section: "شما" },
  { href: "profile", label: "حساب من", ico: "user-cog" },
];
const homeMobile = () => [
  { href: "", label: "خانه", ico: "house" },
  { href: "activity", label: "رویدادها", ico: "history" },
  ...(isOwner() ? [{ href: "team", label: "تیم", ico: "users" }] : []),
  { href: "profile", label: "حساب من", ico: "user-cog" },
];

const modules = {};                 // id → { info, def }  (also state.registry, for core pages)
let current = null;                 // { mod, page, qs, cleanup, onParams, token }
let shownModule = null;
let unread = 0;
let source = null;

// ---------------------------------------------------------------- boot
async function boot() {
  try {
    state.me = await api("/api/me", { quiet: true });
  } catch (e) {
    return showLogin();
  }
  await loadModules();
  renderShell();
  connectLive();
  route();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}
on("logout", () => { if (state.me) { state.me = null; source && source.close(); showLogin(); } });
window.addEventListener("hashchange", route);
// remote images (product photos from other sites) that fail to load are hidden instead of showing a broken icon;
// done here rather than with inline onerror="" so the Content-Security-Policy can forbid inline scripts
document.addEventListener("error", (e) => {
  if (e.target instanceof HTMLImageElement && e.target.hasAttribute("data-hide-broken")) e.target.style.visibility = "hidden";
}, true);

async function loadModules() {
  for (const k of Object.keys(modules)) delete modules[k];
  state.registry = modules;
  await Promise.all(state.me.modules.map(async (info) => {
    try {
      const def = (await import(`${info.web}?v=${window.AIKO_VERSION || ""}`)).default;
      modules[info.id] = { info, def, entered: false };
      for (const href of def.css || []) {
        if (!document.querySelector(`link[data-mod-css="${href}"]`)) {
          const link = Object.assign(document.createElement("link"), { rel: "stylesheet", href: `${href}?v=${window.AIKO_VERSION || ""}` });
          link.dataset.modCss = href;
          document.head.appendChild(link);
        }
      }
    } catch (e) {
      console.error(`module ${info.id} failed to load`, e);
      modules[info.id] = { info, def: null, error: e };
    }
  }));
}
const ordered = () => state.me.modules.map((m) => modules[m.id]).filter(Boolean);
const roleOf = (id) => state.me.user.modules[id];

// ---------------------------------------------------------------- login
function showLogin() {
  document.body.style.overflow = "";
  $("#root").innerHTML = String(html`
    <div class="login-wrap">
      <form class="card login-card page-enter" id="login">
        <img class="login-logo" src="/static/img/logo.png" alt="Aiko">
        <h1 style="text-align:center">${document.title || "پنل آیکو"}</h1>
        <p class="muted small" style="text-align:center;margin-bottom:22px">فروشگاه و حسابداری، قیمت رقبا، استودیو محتوا</p>
        <div class="stack s12">
          <div class="field"><label for="u">نام کاربری</label>
            <input class="input ltr" id="u" name="username" autocomplete="username" required autofocus></div>
          <div class="field"><label for="p">رمز عبور</label>
            <input class="input ltr" id="p" name="password" type="password" autocomplete="current-password" required></div>
          <button class="btn primary lg block mt8" type="submit">${icon("log-in")} ورود</button>
          <p class="small muted" id="login-err" role="alert" style="text-align:center;min-height:22px"></p>
        </div>
      </form>
    </div>`);
  $("#login").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const btn = f.querySelector("button");
    btn.disabled = true;
    try {
      await api("/api/login", { method: "POST", body: { username: f.username.value, password: f.password.value }, quiet: true });
      if (!location.hash || location.hash === "#") location.hash = "#/";
      current = null;
      shownModule = null;
      boot();
    } catch (err) {
      $("#login-err").textContent = err.message;
      btn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------- shell
function renderShell() {
  const me = state.me;
  unread = me.unread || 0;
  const rail = ordered().map((m) => html`<a class="rail-btn" data-mod="${m.info.id}" href="#/${m.info.id}" data-tip="${m.info.name}"
      aria-label="${m.info.name}">${icon(m.info.icon)}</a>`);
  $("#root").innerHTML = String(html`
    <div class="app">
      <nav class="rail" aria-label="بخش‌ها">
        <a class="brand-mark" href="#/" aria-label="خانه"><img src="/static/img/logo.png" alt=""></a>
        <a class="rail-btn" data-mod="" href="#/" data-tip="خانه" aria-label="خانه">${icon("house")}</a>
        ${rail}
        <span class="spacer"></span>
        <button class="rail-btn" id="theme-btn" data-tip="روشن / تیره" aria-label="تغییر تم">${icon("moon")}</button>
        <a class="rail-btn" href="#/profile" data-tip="${me.user.name}" aria-label="حساب من">${avatar(me.user.name, "sm")}</a>
        <button class="rail-btn" id="logout-btn" data-tip="خروج" aria-label="خروج">${icon("log-out")}</button>
      </nav>
      <aside class="sidebar">
        <div class="panel-head" id="panel-head"></div>
        <nav class="nav" id="panel-nav"></nav>
        <div class="panel-foot">${me.app.name} · <span class="ltr">${(window.AIKO_VERSION || "").slice(0, 7)}</span></div>
      </aside>
      <main class="main">
        <header class="topbar">
          <a class="brand-mark mobile-brand" href="#/" aria-label="خانه"><img src="/static/img/logo.png" alt=""></a>
          <div class="title"><h1 id="page-title"></h1><p id="page-sub"></p></div>
          <div class="spacer"></div>
          <span class="live-dot off" id="live-dot" title="اتصال زنده"></span>
          <button class="btn icon has-dot" id="bell-btn" aria-label="اعلان‌ها">${icon("bell")}<span class="badge-dot hidden" id="bell-count"></span></button>
          <span id="top-action"></span>
        </header>
        <div class="content" id="view"></div>
      </main>
      <nav class="bottom-nav" id="bottom-nav"></nav>
    </div>`);
  updateBell();
  $("#bell-btn").onclick = openNotifications;
  $("#logout-btn").onclick = logout;
  $("#theme-btn").onclick = toggleTheme;
  delegate($("#bottom-nav"), "click", "[data-menu]", (e) => { e.preventDefault(); openMenu(); });
}

async function logout() {
  await api("/api/logout", { method: "POST" });
  state.me = null;
  source && source.close();
  current = null;
  shownModule = null;
  showLogin();
}

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("aiko-theme", root.dataset.theme); } catch (e) {}
  emit("theme");
}

function navFor(mod) {
  if (!mod) return homeNav();
  const m = modules[mod];
  return m?.def ? m.def.nav(roleOf(mod)) : [];
}
function hrefFor(mod, page) {
  return mod ? `#/${mod}${page ? "/" + page : ""}` : `#/${page}`;
}

/** Redraw the parts of the shell that depend on the current module (panel, bottom nav, top action). */
function showModule(mod) {
  if (shownModule === mod) return;
  shownModule = mod;
  document.querySelectorAll(".rail-btn[data-mod]").forEach((a) => a.classList.toggle("on", a.dataset.mod === mod));
  const m = mod ? modules[mod] : null;
  const role = mod ? roleOf(mod) : null;
  const roleLabel = m ? (m.info.roles[role] || role) : "";
  $("#panel-head").innerHTML = String(html`<span class="panel-ico">${icon(m ? m.info.icon : "house")}</span>
    <div style="min-width:0"><div class="panel-title ellipsis">${m ? m.info.name : "خانه"}</div>
      <div class="panel-sub ellipsis">${m ? roleLabel : `سلام ${state.me.user.name}`}</div></div>`);
  $("#panel-nav").innerHTML = String(html`${navFor(mod).map((it) => it.section
    ? html`<div class="nav-label">${it.section}</div>`
    : html`<a href="${hrefFor(mod, it.href)}" data-nav="${it.href}">${icon(it.ico)}<span>${it.label}</span></a>`)}`);
  const mobile = m?.def ? m.def.mobile(role) : homeMobile();
  $("#bottom-nav").innerHTML = String(html`${mobile.slice(0, 4).map((it) => html`<a href="${hrefFor(mod, it.href)}"
      data-nav="${it.fab ? "" : it.href}" class="${it.fab ? "fab" : ""}" aria-label="${it.label}">${icon(it.ico)}<span>${it.label}</span></a>`)}
    <a href="#" data-menu aria-label="منو">${icon("menu")}<span>منو</span></a>`);
  const action = m?.def?.action ? m.def.action(role) : null;
  const slot = $("#top-action");
  slot.innerHTML = action ? String(html`<a class="btn brand desk-only" href="${action.href !== undefined ? hrefFor(mod, action.href) : "#"}"
    id="top-action-btn">${icon(action.ico || "plus")} ${action.label}</a>`) : "";
  if (action?.onClick) $("#top-action-btn").onclick = (e) => { e.preventDefault(); action.onClick(e); };
}

function openMenu() {
  const mod = shownModule;
  const items = navFor(mod).filter((i) => !i.section);
  const s = sheet({
    title: "منو",
    body: html`<div class="module-grid">
        <a class="module-tile ${mod === "" ? "on" : ""}" href="#/" data-close><span class="panel-ico">${icon("house")}</span>خانه</a>
        ${ordered().map((m) => html`<a class="module-tile ${mod === m.info.id ? "on" : ""}" href="#/${m.info.id}" data-close>
          <span class="panel-ico">${icon(m.info.icon)}</span>${m.info.name}</a>`)}
      </div>
      ${mod ? html`<div class="nav-label mt16">${modules[mod]?.info.name}</div>
      <div class="nav">${items.map((it) => html`<a href="${hrefFor(mod, it.href)}" data-close>${icon(it.ico)}<span>${it.label}</span></a>`)}</div>` : ""}
      <div class="divider"></div>
      <div class="nav">
        ${mod ? homeNav().filter((i) => !i.section && i.href).map((it) => html`<a href="#/${it.href}" data-close>${icon(it.ico)}<span>${it.label}</span></a>`) : ""}
        <a href="#" id="m-theme">${icon("moon")}<span>روشن / تیره</span></a>
        <a href="#" id="m-logout">${icon("log-out")}<span>خروج (${state.me.user.name})</span></a>
      </div>`,
  });
  s.root.querySelectorAll("a[data-close]").forEach((a) => a.addEventListener("click", () => s.close()));
  s.root.querySelector("#m-theme").onclick = (e) => { e.preventDefault(); toggleTheme(); };
  s.root.querySelector("#m-logout").onclick = (e) => { e.preventDefault(); s.close(); logout(); };
}

// ---------------------------------------------------------------- routing
function setTitle(title, sub = "") {
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;
  document.title = `${title} — ${state.me?.app?.name || "آیکو"}`;
}

function parseHash() {
  const [path, qs] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const query = new URLSearchParams(qs || "");
  if (parts[0] && modules[parts[0]]) return { mod: parts[0], page: parts[1] || "", params: parts.slice(2), query, qs: qs || "" };
  return { mod: "", page: parts[0] || "", params: parts.slice(1), query, qs: qs || "" };
}

async function route() {
  if (!state.me || !$("#view")) return;
  let { mod, page, params, query, qs } = parseHash();
  let loader;
  if (mod) {
    const m = modules[mod];
    if (!m.def) return showError(`بخش «${m.info.name}» بارگذاری نشد`, m.error?.message);
    if (!m.def.pages[page] || (m.def.allowed && !m.def.allowed(roleOf(mod), page))) { page = ""; params = []; }
    loader = m.def.pages[page];
  } else {
    if (!CORE_PAGES[page] || (OWNER_ONLY.has(page) && !isOwner())) { page = ""; params = []; }
    loader = CORE_PAGES[page];
  }
  showModule(mod);
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === page && !a.classList.contains("fab")));

  // same page, different sub-path (e.g. opening a detail): let the page handle it without re-rendering
  if (current && current.mod === mod && current.page === page && current.onParams && qs === current.qs) {
    current.onParams(params, query);
    return;
  }
  if (current && current.cleanup) current.cleanup();
  closeAllSheets();
  const view = $("#view");
  view.innerHTML = `<div class="stack"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:320px"></div></div>`;
  window.scrollTo({ top: 0 });
  const token = Symbol();
  current = { mod, page, qs, cleanup: null, onParams: null, token };
  try {
    if (mod && !modules[mod].entered) {
      await modules[mod].def.enter?.();
      modules[mod].entered = true;
    }
    const pageModule = await loader();
    if (current.token !== token) return;
    const result = await pageModule.render(view, params, { setTitle, query, role: mod ? roleOf(mod) : null, module: mod });
    if (current.token !== token) {
      // the user navigated away while this page was loading
      (typeof result === "function" ? result : result?.cleanup)?.();
      return;
    }
    if (typeof result === "function") current.cleanup = result;
    else if (result) { current.cleanup = result.cleanup || null; current.onParams = result.onParams || null; }
    view.firstElementChild?.classList.add("page-enter");
  } catch (e) {
    console.error(e);
    if (current.token === token) showError("این صفحه باز نشد", e.message);
  }
}
function showError(title, detail = "") {
  $("#view").innerHTML = String(emptyState("triangle-alert", title, esc(detail || "")));
}

// ---------------------------------------------------------------- live updates & notifications
function connectLive() {
  if (source) source.close();
  source = new EventSource("/api/stream");
  source.onopen = () => { state.live = true; $("#live-dot")?.classList.remove("off"); emit("live-open"); };
  source.onerror = () => { state.live = false; $("#live-dot")?.classList.add("off"); };
  source.onmessage = (msg) => {
    let ev;
    try { ev = JSON.parse(msg.data); } catch (e) { return; }
    emit("live", ev);
    if (ev.module) emit(`live:${ev.module}`, ev);
    if (ev.type === "activity" && ev.item.notify && ev.item.user_id !== state.me.user.id) {
      unread++;
      updateBell();
      const item = ev.item;
      toast(item.title, item.level === "danger" ? "error" : item.level === "warning" ? "info" : "success", {
        timeout: 7000, action: item.link ? { label: "نمایش", fn: () => (location.hash = item.link) } : null,
      });
    }
  };
}
function updateBell() {
  const el = $("#bell-count");
  if (!el) return;
  el.textContent = unread > 9 ? "۹+" : new Intl.NumberFormat("fa-IR").format(unread);
  el.classList.toggle("hidden", !unread);
}
async function openNotifications() {
  const items = await api("/api/activity?only_notify=true&limit=40");
  const s = sheet({
    title: "اعلان‌ها",
    side: true,
    body: items.length ? html`<div class="feed">${items.map((a) => feedItem(a, { showModule: true }))}</div>`
      : emptyState("bell", "اعلانی نیست", "فروش‌ها، تمام شدن موجودی، نتیجه بروزرسانی قیمت‌ها و آماده شدن ویدیوها اینجا می‌آید."),
    foot: html`<a class="btn ghost sm" href="#/activity" data-close>همه رویدادها</a>`,
  });
  delegate(s.root, "click", ".feed-item[data-link]", (e, el) => { if (el.dataset.link) { location.hash = el.dataset.link; s.close(); } });
  if (items.length) {
    api("/api/activity/seen", { method: "POST", body: { id: items[0].id }, quiet: true });
    unread = 0;
    updateBell();
  }
}

boot();
