// Every event from every module (filtered to what this user may see), newest first, live.
import { $, api, delegate, emptyState, feedItem, html, icon, on, state } from "../kit.js";

export async function render(view, params, { setTitle, query }) {
  setTitle("رویدادها", "هر چه در فروشگاه، قیمت‌ها و استودیو اتفاق افتاده");
  let module = query.get("module") || "";
  let items = [];
  const mods = [{ id: "", name: "همه" }, ...state.me.modules.map((m) => ({ id: m.id, name: m.name })),
    ...(state.me.user.is_admin ? [{ id: "core", name: "سیستم" }] : [])];

  const draw = () => {
    view.innerHTML = String(html`<div class="stack">
      <div class="chips scroll">${mods.map((m) => html`<button class="chip ${m.id === module ? "on" : ""}" data-m="${m.id}">${m.name}</button>`)}</div>
      <section class="card">
        ${items.length ? html`<div class="feed" id="feed">${items.map((a) => feedItem(a, { showModule: !module }))}</div>
          <div class="row mt16" style="justify-content:center"><button class="btn sm ghost" id="more">${icon("chevron-down", "sm")} قدیمی‌تر</button></div>`
          : emptyState("history", "رویدادی نیست")}
      </section></div>`);
    $("#more", view)?.addEventListener("click", async () => {
      const older = await api(`/api/activity?limit=60&before=${items[items.length - 1].id}${module ? `&module=${module}` : ""}`);
      if (!older.length) { $("#more", view).remove(); return; }
      items = items.concat(older);
      draw();
    });
  };
  const load = async () => {
    items = await api(`/api/activity?limit=60${module ? `&module=${module}` : ""}`);
    draw();
  };
  await load();
  delegate(view, "click", "[data-m]", (e, b) => { module = b.dataset.m; load(); });
  delegate(view, "click", ".feed-item[data-link]", (e, el) => { if (el.dataset.link) location.hash = el.dataset.link; });
  const off = on("live", (ev) => {
    if (ev.type !== "activity" || (module && ev.item.module !== module)) return;
    items.unshift(ev.item);
    draw();
    view.querySelector(".feed-item")?.classList.add("fresh");
  });
  return off;
}
