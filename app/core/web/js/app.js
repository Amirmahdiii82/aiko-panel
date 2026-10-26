// App shell: login, the top bar (sections), the tool dock, page tabs, routing, live updates and notifications.
//
// Layout (desktop): top bar = brand · sections (home + one per module) · bell and account; a dark dock on the start
// edge = search, activity, settings, theme; under the page title, the current section's pages as tabs.
// Phones: sections move to a bottom bar (with the section's main action in the middle), the dock to the account menu.
//
// Routes:  #/                    home                    (core)
//          #/activity|settings/<section>|profile         (core pages; settings holds every setting, incl. team)
//          #/<module>/<page>/<params...>?query          (a module page, e.g. #/erp/sales/12)
//
// Each module ships /m/<id>/index.js whose default export describes it to the shell:
//   { id, nav(role), pages: { "": () => import(...) }, settings?: () => import(...), allowed(role, page), enter(),
//     action(role), quick(role), glance(data, role), css: [] }
// A module's settings page is never routed on its own: it is a section of Settings (#/settings/<id>).
import { $, api, avatar, closeAllSheets, delegate, emit, emptyState, esc, feedItem, html, icon, isDark, isOwner, isPhone,
  moduleSettingsAllowed, on, popover, reducedMotion, sheet, state, toast, toggleTheme } from "./kit.js";

const CORE_PAGES = {
  "": () => import("./pages/home.js"),
  activity: () => import("./pages/activity.js"),
  settings: () => import("./pages/settings.js"),
  profile: () => import("./pages/profile.js"),
};
// pages that moved: old links (bookmarks, notifications, bot messages) still land in the right place
// (plus every #/<module>/settings…, which is now #/settings/<module>…)
const MOVED = { team: "settings/team" };
/** The core destinations: one list behind the dock (`dock`), the phone menu and the command palette. */
const corePages = () => [
  { href: "", label: "خانه", ico: "house" },
  { href: "activity", label: "رویدادها", ico: "history", dock: true },
  ...(isOwner() ? [{ href: "settings/team", label: "تیم و دسترسی‌ها", ico: "users", dock: true }] : []),
  ...(canSettings() ? [{ href: "settings", label: "تنظیمات", ico: "settings", dock: true }] : []),
  { href: "profile", label: "حساب من و رمز", ico: "user-cog" },
];
/** Owners see every setting; a module's manager sees that module's (see pages/settings.js). */
const canSettings = () => isOwner() || ordered().some((m) => moduleSettingsAllowed(m));

const modules = {};                 // id → { info, def }  (also state.registry, for core pages)
let current = null;                 // { mod, page, qs, cleanup, onParams, token }
let shownModule = null;
let unread = 0;
let source = null;
let titleObserver = null;
let topnav = null;
window.addEventListener("scroll", () => topnav?.classList.toggle("scrolled", window.scrollY > 4), { passive: true });
on("theme", () => { const b = $("#theme-btn"); if (b) b.innerHTML = String(icon(isDark() ? "sun" : "moon")); });

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
        <h1 style="text-align:center;font-size:22px">${document.title || "پنل آیکو"}</h1>
        <p class="muted small" style="text-align:center;margin-bottom:22px">فروشگاه و حسابداری، قیمت رقبا، استودیو محتوا</p>
        <div class="stack s12">
          <div class="field"><label for="u">نام کاربری</label>
            <input class="input ltr" id="u" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" enterkeyhint="next" required autofocus></div>
          <div class="field"><label for="p">رمز عبور</label>
            <input class="input ltr" id="p" name="password" type="password" autocomplete="current-password" enterkeyhint="go" required></div>
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
const mac = () => navigator.platform?.includes("Mac");
function renderShell() {
  const me = state.me;
  unread = me.unread || 0;
  $("#root").innerHTML = String(html`
    <div class="app">
      <header class="topnav">
        <a class="brand" href="#/" aria-label="خانه"><span class="brand-mark"><img src="/static/img/logo.png" alt=""></span>
          <span class="brand-name">${me.app.name}</span></a>
        <nav class="modnav" id="modnav" aria-label="بخش‌ها">
          <a href="#/" data-mod="">${icon("house")}خانه</a>
          ${ordered().map((m) => html`<a href="#/${m.info.id}" data-mod="${m.info.id}">${icon(m.info.icon)}${m.info.name}</a>`)}
        </nav>
        <div class="top-tools">
          <button class="icon-btn" id="bell-btn" aria-label="اعلان‌ها">${icon("bell")}<span class="badge-dot hidden" id="bell-count"></span></button>
          <button class="avatar-btn" id="me-btn" aria-label="حساب و منو">${avatar(me.user.name)}</button>
        </div>
      </header>
      <nav class="dock" id="dock" aria-label="ابزارها">
        <button class="dock-btn" id="search-btn" data-tip="رفتن به… (${mac() ? "⌘K" : "Ctrl K"})" aria-label="جستجو">${icon("search")}</button>
        ${corePages().filter((p) => p.dock).map((p) => html`<a class="dock-btn" href="#/${p.href}" data-page="${p.href}" data-tip="${p.label}"
          aria-label="${p.label}">${icon(p.ico)}</a>`)}
        <span class="dock-sep"></span>
        <button class="dock-btn" id="theme-btn" data-tip="روشن / تیره" aria-label="تغییر تم">${icon(isDark() ? "sun" : "moon")}</button>
      </nav>
      <main class="main">
        <button class="mini-bar" id="mini-bar" type="button" aria-label="رفتن به بالای صفحه"><span id="mini-title"></span></button>
        <div class="page-head">
          <div class="title"><h1 id="page-title"></h1><p id="page-sub"></p></div>
          <div class="head-tools">
            <span class="live-pill desk-only" title="اتصال زنده: اعداد بدون رفرش به‌روز می‌شوند"><span class="live-dot off" id="live-dot"></span><span id="live-text">در حال اتصال</span></span>
            <span id="top-action" class="desk-only"></span>
          </div>
        </div>
        <nav class="subnav" id="subnav" aria-label="صفحه‌های این بخش" hidden></nav>
        <div class="content" id="view"></div>
      </main>
      <nav class="bottom-nav" id="bottom-nav" aria-label="بخش‌ها"></nav>
    </div>`);
  updateBell();
  $("#bell-btn").onclick = openNotifications;
  $("#me-btn").onclick = (e) => openMenu(e.currentTarget);
  $("#theme-btn").onclick = (e) => toggleTheme(e.currentTarget);
  $("#search-btn").onclick = openPalette;
  bindTooltips($("#dock"));
  topnav = $(".topnav");
  // phones: once the big title scrolls away, a compact bar keeps "where am I" visible; tapping it goes back to top
  const mini = $("#mini-bar");
  titleObserver?.disconnect();
  titleObserver = new IntersectionObserver(([e]) => mini.classList.toggle("show", !e.isIntersecting && window.scrollY > 0));
  titleObserver.observe($(".page-head"));
  mini.onclick = () => window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" });
}

// ---------------------------------------------------------------- tooltips
// One fixed tooltip for [data-tip] elements (mouse only). The first waits a beat so passing over the dock doesn't
// flash labels; while one is showing, moving to a neighbour shows it instantly with no animation.
function bindTooltips(root) {
  let tip = document.querySelector("body > .tip");               // one for the page's life, not one per login
  if (!tip) {
    tip = Object.assign(document.createElement("div"), { className: "tip", role: "tooltip" });
    tip.dataset.state = "hidden";
    document.body.appendChild(tip);
  }
  let timer = null, warmUntil = 0;
  const show = (el) => {
    tip.textContent = el.dataset.tip;
    const r = el.getBoundingClientRect();
    tip.style.top = `${r.top + r.height / 2 - tip.offsetHeight / 2}px`;
    tip.style.left = `${r.left - tip.offsetWidth - 12}px`;
    delete tip.dataset.state;
  };
  root.addEventListener("pointerover", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el || e.pointerType !== "mouse") return;
    clearTimeout(timer);
    const warm = Date.now() < warmUntil || !tip.dataset.state;
    tip.toggleAttribute("data-instant", warm);
    if (warm) show(el);
    else timer = setTimeout(() => show(el), 450);
  });
  root.addEventListener("pointerout", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el || el.contains(e.relatedTarget)) return;
    clearTimeout(timer);
    if (!tip.dataset.state) warmUntil = Date.now() + 300;
    tip.dataset.state = "hidden";
  });
  root.addEventListener("click", () => { clearTimeout(timer); tip.dataset.state = "hidden"; });
}

// ---------------------------------------------------------------- command palette (Ctrl/⌘ K)
// Jump to any page of any module you can open. Keyboard-first and used often, so it opens and closes instantly.
const normFa = (s) => String(s || "").replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ").toLowerCase();
function paletteItems() {
  const items = [];
  corePages().forEach((it) => items.push({ label: it.label, group: "عمومی", ico: it.ico, href: `#/${it.href}` }));
  ordered().filter((m) => m.def).forEach((m) => {
    pagesOf(m.info.id).forEach((it) => items.push({ label: it.label, group: m.info.name, ico: it.ico, href: hrefFor(m.info.id, it.href) }));
    (m.def.quick ? m.def.quick(roleOf(m.info.id)) : []).forEach((q) =>
      items.push({ label: q.label, group: "میانبر", ico: q.ico, href: q.href, sub: q.sub }));
  });
  return items;
}
function openPalette() {
  if (document.querySelector(".palette-scrim")) return;
  const all = paletteItems();
  const opener = document.activeElement;
  const wrap = document.createElement("div");
  wrap.className = "palette-scrim";
  wrap.innerHTML = String(html`<div class="palette" role="dialog" aria-modal="true" aria-label="رفتن به صفحه">
    <div class="input-wrap">${icon("search")}<input class="input" id="pal-q" placeholder="نام صفحه یا کار…" autocomplete="off"
      enterkeyhint="go" role="combobox" aria-controls="pal-list" aria-expanded="true"></div>
    <div class="palette-list" id="pal-list" role="listbox"></div>
    <div class="palette-foot"><span><kbd class="kbd">↑↓</kbd> انتخاب</span><span><kbd class="kbd">Enter</kbd> رفتن</span><span><kbd class="kbd">Esc</kbd> بستن</span></div>
  </div>`);
  document.body.appendChild(wrap);
  const input = $("#pal-q", wrap), list = $("#pal-list", wrap);
  let shown = all, active = 0;
  const draw = () => {
    const terms = normFa(input.value).split(/\s+/).filter(Boolean);
    shown = all.filter((it) => terms.every((t) => normFa(`${it.label} ${it.group} ${it.sub || ""}`).includes(t)));
    active = Math.min(active, Math.max(0, shown.length - 1));
    list.innerHTML = shown.length ? String(html`${shown.map((it, i) => html`<button type="button" class="palette-item" role="option"
        aria-selected="${i === active}" data-i="${i}">${icon(it.ico || "chevron-left")}<span class="grow ellipsis">${it.label}</span>
        <span class="role-pill">${it.group}</span></button>`)}`)
      : `<div class="palette-empty">صفحه‌ای با این نام نیست</div>`;
  };
  const select = (i) => {
    active = i;
    list.querySelectorAll(".palette-item").forEach((b) => b.setAttribute("aria-selected", String(Number(b.dataset.i) === i)));
    list.querySelector(`[data-i="${i}"]`)?.scrollIntoView({ block: "nearest" });
  };
  const close = () => { wrap.remove(); if (opener && opener.isConnected) opener.focus({ preventScroll: true }); };
  const go = (i) => { const it = shown[i]; if (!it) return; close(); location.hash = it.href.replace(/^#?/, "#"); };
  input.addEventListener("input", () => { active = 0; draw(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); select(Math.min(shown.length - 1, active + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); select(Math.max(0, active - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); go(active); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
  });
  list.addEventListener("mousemove", (e) => { const b = e.target.closest("[data-i]"); if (b && Number(b.dataset.i) !== active) select(Number(b.dataset.i)); });
  list.addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) go(Number(b.dataset.i)); });
  wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) close(); });
  draw();
  input.focus();
}
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && !e.altKey && (e.key === "k" || e.key === "K" || e.code === "KeyK") && state.me && $("#view")) {
    e.preventDefault();
    const open = document.querySelector(".palette-scrim");
    if (open) open.remove(); else openPalette();
  }
});

async function logout() {
  await api("/api/logout", { method: "POST" });
  state.me = null;
  source && source.close();
  current = null;
  shownModule = null;
  showLogin();
}

// ---------------------------------------------------------------- the account menu (avatar): everything the dock has
function openMenu(anchor) {
  const me = state.me;
  const link = (p) => ({ href: `#/${p.href}`, ico: p.ico, label: p.label });
  const pages = corePages();
  const items = [
    ...(isPhone() ? [...pages.filter((p) => p.dock).map(link), { act: "search", ico: "search", label: "رفتن به…" }, { sep: true }] : []),
    link(pages.find((p) => p.href === "profile")),
    { act: "theme", ico: isDark() ? "sun" : "moon", label: isDark() ? "تم روشن" : "تم تیره" },
    { sep: true },
    { act: "logout", ico: "log-out", label: "خروج" },
  ];
  popover(anchor, String(html`<div class="menu">
    <div class="menu-head">${avatar(me.user.name, "sm")}<div style="min-width:0"><b class="ellipsis">${me.user.name}</b><span>${isOwner() ? "مدیر کل" : "کاربر"} · @${me.user.username}</span></div></div>
    ${items.map((it) => it.sep ? html`<div class="sep"></div>` : it.href
      ? html`<a href="${it.href}" data-close>${icon(it.ico)}${it.label}</a>`
      : html`<button type="button" data-act="${it.act}">${icon(it.ico)}${it.label}</button>`)}
  </div>`), (pop, close) => {
    pop.addEventListener("click", (e) => {
      const el = e.target.closest("[data-close], [data-act]");
      if (!el) return;
      close();
      if (el.dataset.act === "theme") toggleTheme(anchor);
      if (el.dataset.act === "logout") logout();
      if (el.dataset.act === "search") openPalette();
    });
  });
}

// ---------------------------------------------------------------- navigation model
/** A module's pages, shown as tabs under the page title. */
function pagesOf(mod) {
  const m = modules[mod];
  return m?.def ? m.def.nav(roleOf(mod)) : [];
}
function hrefFor(mod, page) {
  return mod ? `#/${mod}${page ? "/" + page : ""}` : `#/${page}`;
}
/** The module's main action (top of the page; middle of the phone bar), with a full href when it is a link. */
function mainAction(mod) {
  const a = mod ? modules[mod]?.def?.action?.(roleOf(mod)) : null;
  return a ? { ...a, ico: a.ico || "plus", href: a.href !== undefined ? hrefFor(mod, a.href) : null } : null;
}
/** The middle button of the phone bar: the module's main action, or on home the first quick action. */
function fabFor(mod) {
  if (mod) return mainAction(mod)?.href ? mainAction(mod) : null;
  const q = ordered().flatMap((m) => (m.def?.quick ? m.def.quick(roleOf(m.info.id)) : []))[0];
  return q ? { href: q.href, ico: "plus", label: q.label } : null;
}

/** Redraw the parts of the shell that depend on the current module (tabs, phone bar, page action). */
function showModule(mod) {
  if (shownModule === mod) return;
  shownModule = mod;
  document.querySelectorAll("#modnav [data-mod]").forEach((a) => a.classList.toggle("on", a.dataset.mod === mod));
  const pages = mod ? pagesOf(mod) : [];
  const sub = $("#subnav");
  sub.hidden = pages.length < 2;
  sub.innerHTML = String(html`${pages.map((it) => html`<a href="${hrefFor(mod, it.href)}" data-nav="${it.href}">${icon(it.ico)}<span>${it.label}</span></a>`)}`);

  const dest = [{ id: "", name: "خانه", short: "خانه", icon: "house" }, ...ordered().map((m) => m.info)].slice(0, 4);
  const fab = fabFor(mod);
  const cells = dest.map((d) => html`<a href="#/${d.id}" data-mod="${d.id}" class="${d.id === mod ? "on" : ""}" aria-label="${d.name}">${icon(d.icon)}<span>${d.short}</span></a>`);
  if (fab) cells.splice(Math.ceil(cells.length / 2), 0, html`<a href="${fab.href}" class="fab" aria-label="${fab.label}">${icon(fab.ico)}<span>${fab.label}</span></a>`);
  $("#bottom-nav").innerHTML = String(html`${cells}`);

  const action = mainAction(mod);
  $("#top-action").innerHTML = action ? String(html`<a class="btn primary sm" href="${action.href || "#"}" id="top-action-btn">${icon(action.ico)} ${action.label}</a>`) : "";
  if (action?.onClick) $("#top-action-btn").onclick = (e) => { e.preventDefault(); action.onClick(e); };
}

// ---------------------------------------------------------------- routing
function setTitle(title, sub = "") {
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;
  $("#mini-title").textContent = title;
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
  const [path, oldQs] = location.hash.replace(/^#\/?/, "").split("?");
  const [first, second, ...rest] = path.split("/");
  const moved = MOVED[first] ? [MOVED[first], second, ...rest] : modules[first] && second === "settings" ? ["settings", first, ...rest] : null;
  if (moved) { location.replace(`#/${moved.filter((x) => x !== undefined).join("/")}${oldQs ? `?${oldQs}` : ""}`); return; }
  let { mod, page, params, query, qs } = parseHash();
  let loader;
  if (mod) {
    const m = modules[mod];
    if (!m.def) return showError(`بخش «${m.info.name}» بارگذاری نشد`, m.error?.message);
    if (!m.def.pages[page] || (m.def.allowed && !m.def.allowed(roleOf(mod), page))) { page = ""; params = []; }
    loader = m.def.pages[page];
  } else {
    if (!CORE_PAGES[page] || (page === "settings" && !canSettings())) { page = ""; params = []; }
    loader = CORE_PAGES[page];
  }
  showModule(mod);
  // the home section is "on" for home only; activity/team/settings light up their dock button instead (the most
  // specific one: settings/team before settings)
  $('#modnav [data-mod=""]')?.classList.toggle("on", !mod && page === "");
  document.querySelector('#bottom-nav [data-mod=""]')?.classList.toggle("on", !mod && page === "");
  const corePath = mod ? null : [page, ...params].join("/");
  const lit = corePages().filter((p) => p.dock && corePath !== null && (corePath === p.href || corePath.startsWith(`${p.href}/`)))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;
  document.querySelectorAll("#dock [data-page]").forEach((a) => a.classList.toggle("on", a.dataset.page === lit));
  document.querySelectorAll("#subnav [data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === page));
  $("#subnav .on")?.scrollIntoView({ block: "nearest", inline: "nearest" });

  // same page, different sub-path (e.g. opening a detail): let the page handle it without re-rendering
  if (current && current.mod === mod && current.page === page && current.onParams && qs === current.qs) {
    current.onParams(params, query);
    return;
  }
  if (current && current.cleanup) current.cleanup();
  closeAllSheets();
  // a fresh #view for every page: listeners a page attached to it (delegate(view, …)) end with that page
  const stale = $("#view"), view = stale.cloneNode(false);
  stale.replaceWith(view);
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
function setLive(onLine) {
  state.live = onLine;
  $("#live-dot")?.classList.toggle("off", !onLine);
  const t = $("#live-text");
  if (t) t.textContent = onLine ? "زنده" : "قطع — دوباره وصل می‌شود";
}
function connectLive() {
  if (source) source.close();
  source = new EventSource("/api/stream");
  source.onopen = () => { setLive(true); emit("live-open"); };
  source.onerror = () => setLive(false);
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
