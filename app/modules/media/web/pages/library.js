// Library: everything the team generated (shared), with filters; an item opens its detail.
import { $, api, delegate, emptyState, fa, html, icon } from "/static/js/kit.js";
import { TERMINAL, onMedia, openGeneration, statusBadge, usd } from "../media.js";

const FILTERS = [
  { key: "", label: "همه" }, { key: "video", label: "ویدیو", ico: "video" }, { key: "image", label: "تصویر", ico: "image" },
  { key: "favorite", label: "علاقه‌مندی‌ها", ico: "heart" }, { key: "mine", label: "ساخته‌های من", ico: "user" },
  { key: "active", label: "در حال ساخت", ico: "hourglass" },
];

export async function render(view, params, { setTitle }) {
  setTitle("کتابخانه", "همه ویدیوها و تصویرهایی که تیم ساخته");
  let filter = "", items = [], done = false;
  const qs = (before) => {
    const p = new URLSearchParams({ limit: "36" });
    if (filter === "video" || filter === "image") p.set("kind", filter);
    if (filter === "favorite") p.set("favorite", "true");
    if (filter === "mine") p.set("mine", "true");
    if (filter === "active") p.set("status", "active");
    if (before) p.set("before", before);
    return p;
  };
  const draw = () => {
    view.innerHTML = String(html`<div class="stack">
      <div class="chips scroll">${FILTERS.map((f) => html`<button class="chip ${f.key === filter ? "on" : ""}" data-f="${f.key}">${f.ico ? icon(f.ico, "sm") : ""}${f.label}</button>`)}</div>
      ${items.length ? html`<div class="lib-grid">${items.map(tile)}</div>
        ${done ? "" : html`<div class="row" style="justify-content:center"><button class="btn sm ghost" id="more">${icon("chevron-down", "sm")} بیشتر</button></div>`}`
        : html`<section class="card">${emptyState("library", "چیزی اینجا نیست", "ساخته‌های استودیو اینجا جمع می‌شوند.", html`<a class="btn soft mt8" href="#/media">${icon("wand-sparkles", "sm")} رفتن به استودیو</a>`)}</section>`}
    </div>`);
  };
  const load = async () => {
    items = await api(`/api/media/generations?${qs()}`);
    done = items.length < 36;
    draw();
  };
  await load();
  delegate(view, "click", "[data-f]", (e, b) => { filter = b.dataset.f; load(); });
  delegate(view, "click", "#more", async () => {
    const more = await api(`/api/media/generations?${qs(items[items.length - 1].id)}`);
    done = more.length < 36;
    items = items.concat(more);
    draw();
  });
  delegate(view, "click", "[data-open]", (e, b) => { location.hash = `#/media/library/${b.dataset.open}`; });
  // the detail sheet has its own URL (#/media/library/<id>); closing it goes back to the list URL
  const open = (id) => openGeneration(id, {
    onChanged: load,
    onClose: () => { if (location.hash.startsWith("#/media/library/")) history.replaceState(null, "", "#/media/library"); },
  }).catch(() => {});
  if (params[0]) open(Number(params[0]));
  const off = onMedia((ev) => {
    if (ev.type === "generation_deleted") { items = items.filter((g) => g.id !== ev.id); draw(); return; }
    if (ev.type !== "generation" || !ev.item) return;
    const i = items.findIndex((g) => g.id === ev.item.id);
    if (i >= 0) { items[i] = ev.item; draw(); } else if (!filter || filter === ev.item.kind || filter === "active") { items.unshift(ev.item); draw(); }
  });
  return { cleanup: off, onParams: (p) => { if (p[0]) open(Number(p[0])); } };
}

function tile(g) {
  const thumb = g.status === "completed" && g.kind === "image" && g.outputs?.[0]
    ? html`<img src="${g.outputs[0].url}" alt="" loading="lazy">`
    : g.status === "completed" && g.kind === "video" ? html`<video src="${g.outputs?.[0]?.url || `/api/media/generations/${g.id}/files/0`}#t=0.5" preload="metadata" muted playsinline></video>`
      : html`<span>${icon(TERMINAL.has(g.status) ? "circle-alert" : "hourglass", "lg")}</span>`;
  return html`<button class="lib-item" data-open="${g.id}">
    <span class="lib-thumb">${thumb}<span class="kind badge">${icon(g.kind === "video" ? "video" : "image", "sm")}${g.kind === "image" && g.outputs?.length > 1 ? fa(g.outputs.length) : ""}</span>
      ${g.favorite ? html`<span class="fav">${icon("heart")}</span>` : ""}</span>
    <span class="lib-body"><span class="t">${g.prompt}</span>
      <span class="m">${g.model_name || g.model_id}${g.cost != null ? ` · ${usd(g.cost)}` : ""}${g.created_by_name ? ` · ${g.created_by_name}` : ""}</span>
      ${g.status !== "completed" ? statusBadge(g.status) : ""}</span>
  </button>`;
}
