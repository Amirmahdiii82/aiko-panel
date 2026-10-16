// Media studio state and shared pieces: live model capabilities, pricing, generation cards, the detail sheet.
// Generations live on the server (shared team library); the browser only remembers composer preferences.
import { api, confirmBox, esc, fa, html, icon, moduleRole, on, raw, sheet, toast } from "/static/js/kit.js";

export const M = {
  config: null,
  models: { video: [], image: [] },
  loaded: new Set(),
  pricingRequested: new Set(),
};
export const canCreate = () => moduleRole("media") === "creator";
export const TERMINAL = new Set(["completed", "failed", "cancelled", "expired"]);
export const STATUS = {
  queued: ["در صف", "info"], submitting: ["در حال ارسال", "info"], pending: ["در صف OpenRouter", "info"],
  in_progress: ["در حال ساخت", "primary"], completed: ["آماده", "ok"], failed: ["ناموفق", "bad"],
  cancelled: ["لغو شد", "warn"], expired: ["منقضی شد", "warn"],
};
export const statusBadge = (s) => html`<span class="badge ${(STATUS[s] || [s, ""])[1]}">${!TERMINAL.has(s) ? html`<span class="spin" style="width:11px;height:11px;border-width:2px"></span>` : ""}${(STATUS[s] || [s])[0]}</span>`;

// ---------------------------------------------------------------- providers & money
export const provider = (id) => String(id || "model").split("/")[0] || "model";
function hue(v) { let h = 0; for (const c of String(v)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return 190 + (h % 150); }
export const provAvatar = (id, cls = "") => html`<span class="prov ${cls}" style="--h:${hue(provider(id))}">${provider(id).split(/[-_\s]+/).map((p) => p[0]).join("").slice(0, 2)}</span>`;
export function usd(v) {
  if (!Number.isFinite(v)) return null;
  if (v === 0) return "$0";
  if (v >= 1) return `$${v.toFixed(v % 1 === 0 ? 0 : 2)}`;
  if (v >= 0.01) return `$${v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}`;
  return `$${v.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
}
const humanize = (s) => String(s).replace(/[_-]+/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
export function pricingEntries(model) {
  return Object.entries(model?.pricing_skus || {}).map(([sku, raw_]) => ({ sku, value: Number.parseFloat(raw_) }))
    .filter((e) => Number.isFinite(e.value) && e.value >= 0).sort((a, b) => a.value - b.value);
}
export function describePricing(model, limit = 3) {
  const e = pricingEntries(model);
  if (!e.length) return "قیمت اعلام‌شده‌ای نیست";
  const shown = e.slice(0, limit).map((x) => `${humanize(x.sku)}: ${usd(x.value)}`);
  if (e.length > limit) shown.push(`+${e.length - limit}`);
  return shown.join(" · ");
}

// ---------------------------------------------------------------- live capabilities
const arr = (v) => (Array.isArray(v) ? [...new Set(v.filter((x) => x !== null && x !== undefined).map(String))] : []);
export function common(models, field) {
  if (!models.length) return [];
  const lists = models.map((m) => arr(m[field]));
  if (lists.some((l) => !l.length)) return [];
  return lists[0].filter((x) => lists.slice(1).every((l) => l.includes(x)));
}
const enumOf = (m, key) => (m?.supported_parameters?.[key]?.type === "enum" ? arr(m.supported_parameters[key].values) : []);
const rangeOf = (m, key) => {
  const d = m?.supported_parameters?.[key];
  if (d?.type !== "range") return null;
  const min = Number(d.min), max = Number(d.max);
  return Number.isFinite(min) && Number.isFinite(max) ? { min, max } : null;
};
export const supports = (m, key) => m?.supported_parameters?.[key] != null;
export function commonEnum(models, key) {
  if (!models.length) return [];
  const lists = models.map((m) => enumOf(m, key));
  if (lists.some((l) => !l.length)) return [];
  return lists[0].filter((x) => lists.slice(1).every((l) => l.includes(x)));
}
export function commonRange(models, key) {
  if (!models.length) return null;
  let min = -Infinity, max = Infinity;
  for (const m of models) {
    const r = rangeOf(m, key);
    if (!r) return null;
    min = Math.max(min, r.min);
    max = Math.min(max, r.max);
  }
  return min <= max ? { min, max } : null;
}
export function capabilityTags(m) {
  if (m.supported_parameters) {
    const tags = [];
    const res = enumOf(m, "resolution"), n = rangeOf(m, "n"), refs = rangeOf(m, "input_references");
    if (res.length) tags.push(res.slice(-2).join(" / "));
    if (n && n.max > 1) tags.push(`up to ${n.max}`);
    if (refs && refs.max > 0) tags.push("image input");
    return tags;
  }
  const tags = [];
  const res = arr(m.supported_resolutions), dur = arr(m.supported_durations);
  if (res.length) tags.push(res.slice(-2).join(" / "));
  if (dur.length) tags.push(`${dur.join(", ")}s`);
  if (m.generate_audio === true) tags.push("audio");
  return tags;
}

export async function loadConfig() {
  M.config = await api("/api/media/config");
  return M.config;
}
export async function loadModels(kind, { force = false } = {}) {
  if (!force && M.loaded.has(kind)) return M.models[kind];
  const r = await api(`/api/media/models?kind=${kind}`);
  M.models[kind] = (Array.isArray(r?.data) ? r.data : []).filter((m) => m && typeof m.id === "string");
  M.loaded.add(kind);
  return M.models[kind];
}
/** Image model records omit pricing; the per-endpoint record carries it (fetched once per model). */
export async function ensureImagePricing(model, onDone) {
  if (!model || model.pricing_skus || M.pricingRequested.has(model.id)) return;
  const [a, s] = model.id.split("/");
  if (!a || !s) return;
  M.pricingRequested.add(model.id);
  try {
    const r = await api(`/api/media/models/${encodeURIComponent(a)}/${encodeURIComponent(s)}/endpoints`, { quiet: true });
    const skus = {};
    let passthrough = [];
    for (const ep of Array.isArray(r?.endpoints) ? r.endpoints : []) {
      for (const line of Array.isArray(ep?.pricing) ? ep.pricing : []) {
        const cost = Number.parseFloat(line?.cost_usd);
        if (!Number.isFinite(cost) || cost < 0) continue;
        const key = `${line.billable ?? "usage"}_per_${line.unit ?? "unit"}`;
        if (skus[key] === undefined || cost < Number(skus[key])) skus[key] = String(cost);
      }
      passthrough = passthrough.concat(arr(ep?.allowed_passthrough_parameters));
    }
    if (passthrough.length) model.allowed_passthrough_parameters = [...new Set(passthrough)];
    if (Object.keys(skus).length) { model.pricing_skus = skus; onDone && onDone(); }
  } catch (e) { /* pricing detail is optional */ }
}

// ---------------------------------------------------------------- generation cards
export function specs(g) {
  const r = g.request || {};
  const parts = [r.resolution || r.size || "پیش‌فرض", r.aspect_ratio || "پیش‌فرض"];
  if (g.kind === "image") parts.push(`${fa(r.n || 1)} تصویر`);
  else parts.push(r.duration ? `${fa(r.duration)} ثانیه` : "پیش‌فرض");
  return parts.join(" · ");
}
const ratioCss = (g) => {
  const r = g.request?.aspect_ratio || g.request?.size?.replace("x", ":") || (g.kind === "image" ? "1:1" : "16:9");
  return /^\d+(\.\d+)?:\d+(\.\d+)?$/.test(r) ? r.replace(":", " / ") : "16 / 9";
};
export function elapsed(g) {
  const start = new Date(g.created_at).getTime();
  const end = TERMINAL.has(g.status) && g.finished_at ? new Date(g.finished_at).getTime() : Date.now();
  const s = Math.max(0, Math.floor((end - start) / 1000));
  return fa(`${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`);
}
function stateCopy(g) {
  const noun = g.kind === "image" ? "تصویر" : "ویدیو";
  return {
    queued: ["در صف ساخت", "به‌زودی شروع می‌شود"],
    submitting: ["در حال ارسال درخواست", "ارسال به OpenRouter"],
    pending: ["در صف OpenRouter", "کار پذیرفته شد؛ منتظر نوبت"],
    in_progress: [`در حال ساخت ${noun}`, g.kind === "image" ? "معمولاً کمتر از یک دقیقه" : "ممکن است چند دقیقه طول بکشد؛ می‌توانید صفحه را ببندید"],
  }[g.status] || ["در حال آماده‌سازی", ""];
}
export function mediaView(g, { large = false } = {}) {
  if (g.status === "completed" && g.kind === "image") {
    const outs = g.outputs || [];
    return html`<div class="img-grid ${outs.length === 1 ? "one" : ""}">${outs.map((o, i) => html`<div class="img-tile">
      <img src="${o.url}" alt="${(g.prompt || "").slice(0, 160)}" loading="lazy" data-zoom="${o.url}">
      <a class="btn xs soft dl" href="${o.url}?download=1" download title="دانلود تصویر ${fa(i + 1)}">${icon("download", "sm")}</a></div>`)}</div>`;
  }
  if (g.status === "completed" && g.kind === "video") {
    const url = g.outputs?.[0]?.url || `/api/media/generations/${g.id}/files/0`;
    return html`<video src="${url}" controls playsinline preload="metadata" ${large ? raw("autoplay") : ""}></video>`;
  }
  if (["failed", "cancelled", "expired"].includes(g.status)) {
    return html`<div class="gen-state"><span class="feed-icon danger">${icon("circle-alert")}</span>
      <b>${g.status === "failed" ? "ساخت ناموفق بود" : STATUS[g.status][0]}</b><span class="small muted">${g.error?.message || "OpenRouter توضیحی نداد."}</span></div>`;
  }
  const [t, d] = stateCopy(g);
  return html`<div class="gen-state"><span class="gen-orb">${icon(g.kind === "image" ? "image" : "clapperboard")}</span><b>${t}</b><span class="small muted">${d}</span></div>`;
}
export function resultCard(g) {
  const done = g.status === "completed";
  const dl = done ? (g.kind === "video" ? (g.outputs?.[0]?.url || `/api/media/generations/${g.id}/files/0`) : g.outputs?.length === 1 ? g.outputs[0].url : null) : null;
  return html`<section class="card result" data-gen="${g.id}" data-status="${g.status}">
    <div class="result-head">${provAvatar(g.model_id, "sm")}<div class="grow"><strong>${g.model_name || g.model_id}</strong><small>${g.model_id}</small></div>
      ${statusBadge(g.status)}<span class="small muted num" data-elapsed="${g.id}">${elapsed(g)}</span></div>
    <div class="media-frame" style="--ratio:${ratioCss(g)}">${mediaView(g)}</div>
    <div class="result-meta"><span>${specs(g)}</span><span>${g.cost != null ? `${usd(g.cost)} هزینه` : "هزینه هنوز معلوم نیست"}</span>
      ${g.created_by_name ? html`<span>${g.created_by_name}</span>` : ""}</div>
    <div class="result-actions">
      ${dl ? html`<a class="btn sm soft" href="${dl}?download=1" download>${icon("download", "sm")} دانلود</a>` : ""}
      ${!TERMINAL.has(g.status) && g.kind === "video" && g.job_id ? html`<button class="btn sm ghost" data-refresh="${g.id}">${icon("refresh-cw", "sm")} بررسی وضعیت</button>` : ""}
      ${canCreate() && TERMINAL.has(g.status) ? html`<button class="btn sm ghost" data-retry="${g.id}">${icon("rotate-ccw", "sm")} دوباره با همین تنظیمات</button>` : ""}
      <button class="btn sm ghost ${g.favorite ? "fav-on" : ""}" data-fav="${g.id}" title="علاقه‌مندی">${icon("heart", "sm")}</button>
      <button class="btn sm ghost" data-json="${g.id}" title="جزئیات فنی">${icon("code", "sm")}</button>
    </div>
    <pre class="raw-json hidden" data-json-of="${g.id}">${JSON.stringify({ request: g.request, usage: g.usage, error: g.error, job_id: g.job_id }, null, 2)}</pre>
  </section>`;
}

/** Shared click handling for cards and the library (favorite, refresh, json, zoom, delete). */
export function bindCardActions(root, { onRetry, onChanged } = {}) {
  root.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-fav],[data-refresh],[data-json],[data-zoom],[data-retry],[data-del]");
    if (!t || !root.contains(t)) return;
    if (t.dataset.fav) {
      const fav = !t.classList.contains("fav-on");
      await api(`/api/media/generations/${t.dataset.fav}`, { method: "PATCH", body: { favorite: fav } });
      t.classList.toggle("fav-on", fav);
      onChanged && onChanged();
    } else if (t.dataset.refresh) {
      t.disabled = true;
      await api(`/api/media/generations/${t.dataset.refresh}/refresh`, { method: "POST" }).finally(() => { t.disabled = false; });
    } else if (t.dataset.json) {
      root.querySelector(`[data-json-of="${t.dataset.json}"]`)?.classList.toggle("hidden");
    } else if (t.dataset.zoom) {
      sheet({ title: "تصویر", size: "xwide", focus: false, body: html`<img src="${t.dataset.zoom}" alt="" style="width:100%;border-radius:18px">`,
        foot: html`<a class="btn primary" href="${t.dataset.zoom}?download=1" download>${icon("download")} دانلود</a><button class="btn ghost" data-close>بستن</button>` });
    } else if (t.dataset.retry) {
      onRetry && onRetry(Number(t.dataset.retry));
    } else if (t.dataset.del) {
      if (!(await confirmBox("این مورد و فایل‌هایش برای همه حذف شود؟", { okText: "حذف", danger: true }))) return;
      await api(`/api/media/generations/${t.dataset.del}`, { method: "DELETE" });
      toast("حذف شد");
      onChanged && onChanged("deleted", Number(t.dataset.del));
    }
  });
}

/** Detail of one generation from the library. */
export async function openGeneration(id, { onChanged, onClose } = {}) {
  const g = await api(`/api/media/generations/${id}`);
  const s = sheet({
    title: g.kind === "image" ? "تصویر" : "ویدیو", size: "xwide", focus: false, onClose,
    body: html`<div class="stack s12">
      <div class="media-frame" style="--ratio:${ratioCss(g)}">${mediaView(g, { large: true })}</div>
      <div class="result-head">${provAvatar(g.model_id, "sm")}<div class="grow"><strong>${g.model_name}</strong><small>${g.model_id}</small></div>${statusBadge(g.status)}</div>
      <div class="inset small" style="direction:auto;white-space:pre-wrap;line-height:1.9">${g.prompt}</div>
      <div class="result-meta"><span>${specs(g)}</span><span>${g.cost != null ? `${usd(g.cost)} هزینه` : ""}</span>
        <span>${g.created_by_name || ""}</span><span>${new Intl.DateTimeFormat("fa-IR-u-ca-persian", { dateStyle: "medium", timeStyle: "short" }).format(new Date(g.created_at))}</span></div>
    </div>`,
    foot: html`${g.status === "completed" && g.outputs?.length === 1 ? html`<a class="btn primary" href="${g.outputs[0].url}?download=1" download>${icon("download")} دانلود</a>` : ""}
      <button class="btn ghost ${g.favorite ? "fav-on" : ""}" data-fav="${g.id}">${icon("heart", "sm")} علاقه‌مندی</button>
      ${canCreate() ? html`<a class="btn ghost" href="#/media?retry=${g.id}" data-close>${icon("rotate-ccw", "sm")} دوباره بساز</a>` : ""}
      <span class="spacer"></span>${canCreate() ? html`<button class="btn danger" data-del="${g.id}">${icon("trash-2", "sm")} حذف</button>` : ""}`,
  });
  bindCardActions(s.root, { onChanged: (what) => { if (what === "deleted") s.close(); onChanged && onChanged(); } });
  return s;
}

// one live channel for every media page
export const onMedia = (fn) => on("live:media", fn);
export { esc };
