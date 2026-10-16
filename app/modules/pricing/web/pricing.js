// Pricing module state and shared pieces: formatting, position badges, price strip, dot plot, charts,
// the product detail sheet and the crawl status that every page shows.
import { $, $$, api, emit, emptyState, esc, html, icon, moduleRole, on, raw, sheet, storage, toast } from "/static/js/kit.js";

export const P = {
  meta: null,
  siteNames: {},
  filters: storage("pricing-filters") || { q: "", position: "", brand: "", site: "", sort: "gap", opportunity: "" },
};
export const canEdit = () => moduleRole("pricing") === "editor";

// ---------------------------------------------------------------- formatting (prices are Toman)
const nf = new Intl.NumberFormat("fa-IR");
export const nf1 = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
export const n = (v) => (v == null ? "—" : nf.format(v));
export const pc = (v, sign = true) => (v == null ? "—" : `${sign && v > 0 ? "+" : ""}${nf1.format(v)}٪`);
export const short = (v) => {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e9) return `${nf1.format(v / 1e9)} میلیارد`;
  if (Math.abs(v) >= 1e6) return `${nf1.format(v / 1e6)} میلیون`;
  if (Math.abs(v) >= 1e3) return `${nf1.format(v / 1e3)} هزار`;
  return nf.format(v);
};
const TZ = "Asia/Tehran";
export const faDate = (iso) => (iso ? new Intl.DateTimeFormat("fa-IR-u-ca-persian", { dateStyle: "medium", timeStyle: "short", timeZone: TZ }).format(new Date(iso)) : "—");
export const shortDate = (iso) => new Intl.DateTimeFormat("fa-IR-u-ca-persian", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: TZ }).format(new Date(iso));
export const ago = (iso) => {
  if (!iso) return "هرگز";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "همین الان";
  if (s < 3600) return `${n(Math.round(s / 60))} دقیقه پیش`;
  if (s < 86400) return `${n(Math.round(s / 3600))} ساعت پیش`;
  return `${n(Math.round(s / 86400))} روز پیش`;
};

// ---------------------------------------------------------------- positions & badges
export const POS = {
  cheapest: { label: "ارزان‌ترین", cls: "ok", color: "var(--pos-good)", mark: "✓" },
  close: { label: "رقابتی (تا ۳٪)", cls: "info", color: "var(--pos-info)", mark: "≈" },
  above: { label: "گران‌تر (۳ تا ۱۰٪)", cls: "warn", color: "var(--pos-warn)", mark: "▲" },
  far_above: { label: "خیلی گران‌تر (+۱۰٪)", cls: "bad", color: "var(--pos-bad)", mark: "▲▲" },
  unique: { label: "بدون رقیب", cls: "primary", color: "var(--pos-violet)", mark: "★" },
  no_price: { label: "بدون قیمت / ناموجود", cls: "", color: "var(--pos-none)", mark: "–" },
};
export const posBadge = (p) => (p && POS[p] ? html`<span class="badge ${POS[p].cls}" title="${POS[p].label}">${POS[p].mark} ${POS[p].label}</span>` : "");
export const gapBadge = (g) => {
  if (g == null) return html`<span class="muted">—</span>`;
  const cls = g <= 0 ? "ok" : g <= 3 ? "info" : g <= 10 ? "warn" : "bad";
  return html`<span class="badge ${cls} num">${g <= 0 ? "▼" : "▲"} ${pc(g)}</span>`;
};
export const indexBadge = (i) => {
  if (i == null) return "—";
  const cls = i <= 98 ? "ok" : i <= 103 ? "info" : i <= 110 ? "warn" : "bad";
  return html`<span class="badge ${cls} num">${nf1.format(i)}</span>`;
};
export const siteName = (k) => P.siteNames[k] || k;
export const img = (src, cls = "thumb") => src
  ? html`<img class="${cls}" src="${src}" alt="" loading="lazy" referrerpolicy="no-referrer" data-hide-broken>`
  : html`<span class="${cls}">${icon("package", "sm")}</span>`;
export const pEmpty = (t) => html`<div class="p-empty">${t}</div>`;
/** Links scraped from other sites are only followed if they are plain http(s). */
export const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

// ---------------------------------------------------------------- meta, crawl state, review badge
export async function refreshMeta() {
  P.meta = await api("/api/pricing/meta");
  P.siteNames = Object.fromEntries(P.meta.sites.map((s) => [s.key, s.name]));
  syncAction();
  return P.meta;
}
export function progressText(p) {
  if (!p || !p.sites) return "";
  if (p.stage === "catalog") return "خواندن محصولات سایت شما";
  if (p.stage === "new_products") return "بررسی بازار محصولات جدید";
  const vals = Object.values(p.sites);
  const done = vals.reduce((a, s) => a + s.done, 0), total = vals.reduce((a, s) => a + s.total, 0);
  return total ? `${n(Math.round((done / total) * 100))}٪ از ${n(vals.length)} سایت` : "";
}
export function progressPct(p) {
  const vals = Object.values(p?.sites || {});
  const done = vals.reduce((a, s) => a + s.done, 0), total = vals.reduce((a, s) => a + s.total, 0);
  return total ? Math.round((done / total) * 100) : p?.stage === "catalog" ? 3 : 0;
}
/** The shell's top-bar button for this module mirrors the crawl state. */
export function syncAction() {
  const btn = $("#top-action-btn");
  if (!btn || !P.meta || !location.hash.startsWith("#/pricing")) return;
  btn.classList.toggle("disabled", P.meta.running);
  btn.innerHTML = P.meta.running ? String(html`<span class="spin"></span> در حال اجرا`) : String(html`${icon("refresh-cw")} بروزرسانی قیمت‌ها`);
}
export async function startCrawl(body = {}) {
  if (!canEdit()) return toast("دسترسی شما فقط مشاهده است", "error");
  if (P.meta?.running) return toast("یک بروزرسانی در حال اجراست", "info");
  await api("/api/pricing/crawl", { method: "POST", body });
  toast(body.product_ids ? "در حال خواندن قیمت‌های همین محصول…" : "بروزرسانی شروع شد؛ چند دقیقه طول می‌کشد");
  if (P.meta) P.meta.running = true;
  syncAction();
  emit("pricing:state");
}
export function setReviewCount(count) {
  $$('a[data-nav="review"]').forEach((a) => {
    let c = a.querySelector(".count");
    if (!count) { c?.remove(); return; }
    if (!c) { c = document.createElement("span"); c.className = "count"; a.appendChild(c); }
    c.textContent = n(count);
  });
}
export async function refreshReviewCount() {
  try { const r = await api("/api/pricing/review?limit=1", { quiet: true }); setReviewCount(r.total); } catch (e) { /* ignore */ }
}

// live crawl progress / completion (once per page load)
let wired = false;
export function wireLive() {
  if (wired) return;
  wired = true;
  on("live:pricing", async (ev) => {
    if (!P.meta) return;
    if (ev.type === "progress") {
      P.meta.running = ev.running;
      P.meta.progress = ev.progress;
      syncAction();
      emit("pricing:progress", ev.progress);
    } else if (ev.type === "crawl") {
      await refreshMeta();
      emit("pricing:state", ev);
      if (ev.state === "done" || ev.state === "failed") refreshReviewCount();
    }
  });
  window.addEventListener("hashchange", () => setTimeout(syncAction, 50));
}

// ---------------------------------------------------------------- tooltips
let tipEl = null;
export function showTip(e, content) {
  if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "p-tip"; document.body.appendChild(tipEl); }
  tipEl.innerHTML = content;
  tipEl.hidden = false;
  const r = tipEl.getBoundingClientRect();
  let x = e.clientX - r.width / 2, y = e.clientY - r.height - 14;
  x = Math.max(8, Math.min(x, innerWidth - r.width - 8));
  if (y < 8) y = e.clientY + 18;
  tipEl.style.left = `${x}px`;
  tipEl.style.top = `${y}px`;
}
export const hideTip = () => { if (tipEl) tipEl.hidden = true; };
/** Elements with data-tip (HTML whose text parts were escaped when built) show it on hover. */
export function bindTips(root) {
  $$("[data-tip]", root).forEach((el) => {
    el.addEventListener("mousemove", (e) => { e.stopPropagation(); showTip(e, el.dataset.tip); });
    el.addEventListener("mouseleave", hideTip);
  });
}

// ---------------------------------------------------------------- tiny visualisations
/** Every competitor's price (dots) and yours (diamond) on one strip; cheaper is to the right. */
export function ladder(r) {
  const pts = r.sites.map((s) => s.price);
  if (!pts.length || !r.my_price) return html`<span class="muted small">—</span>`;
  const all = [...pts, r.my_price];
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi === lo) { lo *= 0.95; hi *= 1.05; }
  const W = 150, pad = 8, x = (v) => W - pad - ((v - lo) / (hi - lo)) * (W - pad * 2);
  const tipFor = (label, v) => esc(`${esc(label)}: ${n(v)} تومان`);
  return raw(`<svg class="ladder" viewBox="0 0 ${W} 26" aria-label="بازه قیمت">
    <line class="track" x1="${pad}" x2="${W - pad}" y1="13" y2="13"/>
    ${r.sites.map((s) => `<circle class="comp" cx="${x(s.price)}" cy="13" r="5" data-tip="${tipFor(siteName(s.site), s.price)}"/>`).join("")}
    <rect class="me" x="${x(r.my_price) - 6}" y="7" width="12" height="12" rx="3" transform="rotate(45 ${x(r.my_price)} 13)" data-tip="${tipFor("شما", r.my_price)}"/>
  </svg>`);
}

/** All listings per site on one price axis, with your price (or a suggested price) and an optional profit floor. */
export function dotPlot(offers, my, { label = "شما", floor = null } = {}) {
  const shown = offers.filter((o) => o.status !== "rejected" && o.price);
  if (!shown.length) return pEmpty("آگهی قیمت‌داری برای نمایش نیست.");
  const vals = shown.map((o) => o.price).concat(my ? [my] : [], floor ? [floor] : []);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || hi * 0.1;
  lo -= span * 0.06; hi += span * 0.06;
  const pos = (v) => ((v - lo) / (hi - lo)) * 100;
  const bySite = {};
  shown.forEach((o) => (bySite[o.site] ||= []).push(o));
  const rows = Object.entries(bySite).sort((a, b) => Math.min(...a[1].map((o) => o.price)) - Math.min(...b[1].map((o) => o.price)));
  const ticks = [lo + (hi - lo) * 0.06, (lo + hi) / 2, hi - (hi - lo) * 0.06];
  const h = (rows.length - 1) * 36;
  return raw(`<div class="plot" style="padding-top:${my ? 24 : 0}px;padding-bottom:${floor ? 22 : 0}px">
    ${rows.map(([site, list], i) => `<div class="plot-row"><div class="plot-site">${esc(siteName(site))}</div><div class="plot-track">
      ${i === 0 && my ? `<div class="plot-me" style="right:${pos(my)}%;top:-24px;bottom:-${h}px"></div><div class="plot-me-label" style="right:${pos(my)}%">${esc(label)} ${n(my)}</div>` : ""}
      ${i === 0 && floor ? `<div class="plot-me plot-floor" style="right:${pos(floor)}%;top:-24px;bottom:-${h}px" title="حداقل قیمت برای رسیدن به سود هدف"></div><div class="plot-me-label plot-floor-label" style="right:${pos(floor)}%;top:auto;bottom:-${h + 22}px">کف سود ${n(floor)}</div>` : ""}
      ${list.map((o) => `<span class="plot-dot ${o.status === "pending" ? "pending" : ""} ${!o.in_stock || !o.fresh ? "oos" : ""}" style="right:${pos(o.price)}%"
        data-tip="${esc(`<b>${n(o.price)} تومان</b><br>${esc(siteName(o.site))}${o.seller ? " · " + esc(o.seller) : ""}<br>${esc(o.title)}${o.status === "pending" ? "<br>منتظر تأیید" : ""}${!o.in_stock ? "<br>ناموجود" : ""}`)}"></span>`).join("")}
    </div></div>`).join("")}
    <div class="plot-axis"><div></div><div class="plot-axis-in">${ticks.map((t) => `<span style="right:${pos(t)}%">${short(Math.round(t))}</span>`).join("")}</div></div>
  </div>`);
}

// ---------------------------------------------------------------- charts
function cssVar(el, name) { return getComputedStyle(el).getPropertyValue(name).trim(); }
export function chartBase(el) {
  const scope = el.closest(".pricing, .p-sheet") || document.documentElement;
  Chart.defaults.font.family = "Vazirmatn, system-ui, sans-serif";
  Chart.defaults.color = cssVar(document.documentElement, "--muted");
  return { ink2: cssVar(document.documentElement, "--ink-2"), ink: cssVar(document.documentElement, "--ink"), grid: cssVar(scope, "--grid"),
    accent: cssVar(scope, "--accent"), market: cssVar(scope, "--market"), market2: cssVar(scope, "--market-2"), surface: cssVar(scope, "--surface") };
}
export function hexA(hex, a) {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
}
export function lineOptions(c, tickFmt, labelFn) {
  return {
    responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { rtl: true, textDirection: "rtl", labels: { usePointStyle: true, pointStyle: "line", boxWidth: 18, color: c.ink2 } },
      tooltip: { rtl: true, textDirection: "rtl", backgroundColor: c.ink, titleColor: c.surface, bodyColor: c.surface, padding: 10, cornerRadius: 8,
        callbacks: { label: (ctx) => labelFn(ctx) ?? `${ctx.dataset.label}: ${tickFmt(ctx.parsed.y)}` }, filter: (i) => labelFn(i) !== null || i.datasetIndex !== 1 },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 6 }, border: { color: c.grid } },
      y: { grid: { color: c.grid }, border: { display: false }, ticks: { callback: tickFmt, maxTicksLimit: 5 } },
    },
  };
}

// ---------------------------------------------------------------- product detail (side sheet)
export function insightBox(a) {
  const site = a.cheapest_site ? siteName(a.cheapest_site) : "";
  if (a.position === "far_above")
    return html`<div class="callout bad">${icon("trending-down")}<div>قیمت شما <b>${pc(a.gap_min_pct, false)} بیشتر</b> از ارزان‌ترین رقیب (${site}، ${n(a.min)} تومان) است.
      برای هم‌قیمت شدن باید حدود <b>${n(a.my_price - a.min)} تومان</b> کم کنید؛ یا اگر خدمات/اصالت بهتری دارید، آن را در صفحه محصول برجسته کنید.</div></div>`;
  if (a.opportunity === "raise")
    return html`<div class="callout ok">${icon("piggy-bank")}<div>شما ارزان‌ترین هستید و نزدیک‌ترین رقیب (${site}) <b>${n(a.min)}</b> تومان می‌فروشد.
      می‌توانید تا حدود <b>${n(a.suggested_price)}</b> تومان بفروشید و همچنان ارزان‌ترین باشید (<b>+${n(a.impact)}</b> در هر فروش).</div></div>`;
  if (a.position === "cheapest") return html`<div class="callout ok">${icon("circle-check")}<div>شما ارزان‌ترین فروشنده این محصول هستید.</div></div>`;
  if (a.position === "close") return html`<div class="callout">${icon("info")}<div>قیمت شما تنها ${pc(a.gap_min_pct, false)} با ارزان‌ترین رقیب (${site}) فاصله دارد؛ رقابتی است.</div></div>`;
  if (a.position === "above") return html`<div class="callout warn">${icon("trending-up")}<div>قیمت شما ${pc(a.gap_min_pct, false)} از ارزان‌ترین رقیب (${site}) بیشتر است.</div></div>`;
  if (a.position === "unique") return html`<div class="callout">${icon("star")}<div>${a.opportunity === "competitors_oos" ? raw("رقبا این محصول را دارند ولی <b>ناموجود</b> است؛ فرصت فروش بیشتر.") : "در رقبا آگهی تأییدشده و موجودی برای این محصول پیدا نشد."}
      ${a.n_pending ? ` ${n(a.n_pending)} تطبیق منتظر تأیید شماست.` : ""}</div></div>`;
  return html`<div class="callout">${icon("info")}<div>این محصول در سایت شما قیمت ندارد یا ناموجود است.</div></div>`;
}

const STATUS_BADGE = {
  confirmed: html`<span class="badge ok">تأیید شده</span>`,
  auto: html`<span class="badge info" title="تطبیق خودکار با اطمینان بالا">خودکار</span>`,
  pending: html`<span class="badge warn">منتظر تأیید</span>`,
  rejected: html`<span class="badge">رد شده</span>`,
};
export const isWarnReason = (r) => /متفاوت|نیامده|نیست/.test(r);
export function scoreBar(o) {
  const v = Math.round((o.score || 0) * 100);
  return html`<span class="score" title="${(o.reasons || []).join(" · ")}">تطابق <i><b style="width:${v}%"></b></i> ${n(v)}٪</span>`;
}
function sellersTable(sellers, mine = true) {
  return sellers && sellers.length > 1 ? html`<details class="sellers"><summary>${n(sellers.length)} فروشنده / تنوع در این آگهی</summary>
    <table>${sellers.map((s) => html`<tr><td>${s.seller || ""}${mine && s.is_me ? " (شما)" : ""}</td><td>${s.variant || ""}</td><td class="n">${n(s.price)}</td></tr>`)}</table></details>` : "";
}
function offerRow(o, my) {
  const notes = [];
  if (!o.fresh) notes.push(html`<span class="badge">قدیمی: ${ago(o.last_seen)}</span>`);
  else if (!o.in_stock) notes.push(html`<span class="badge">ناموجود</span>`);
  else if (o.status === "auto" && !o.counted) notes.push(html`<span class="badge warn" title="قیمت خیلی دور از قیمت شماست؛ تا تأیید نکنید شمرده نمی‌شود">قیمت مشکوک</span>`);
  const disc = o.regular_price && o.price && o.regular_price > o.price ? Math.round((1 - o.price / o.regular_price) * 100) : 0;
  return html`<div class="offer ${o.status === "rejected" ? "rejected" : ""}">
    <div style="min-width:0">
      <div class="offer-title"><a href="${safeUrl(o.url)}" target="_blank" rel="noopener">${o.title} ↗</a></div>
      <div class="offer-meta">
        ${o.seller ? html`<span>فروشنده: ${o.seller}</span>` : ""}
        ${o.extra?.shops > 1 ? html`<span>${n(o.extra.shops)} فروشگاه در ترب</span>` : ""}
        ${scoreBar(o)}
        ${(o.reasons || []).filter(isWarnReason).map((r) => html`<span class="badge warn">${r}</span>`)}
        ${STATUS_BADGE[o.status] || ""}${notes}
      </div>
    </div>
    <div class="offer-price"><b class="num">${n(o.price)}</b>${disc ? html` <span class="badge bad">${n(disc)}٪ تخفیف</span>` : ""}
      ${my && o.price ? html`<div class="small muted">${o.price < my ? "ارزان‌تر از شما" : o.price > my ? "گران‌تر از شما" : "هم‌قیمت"}</div>` : ""}</div>
    ${canEdit() ? html`<div class="row nowrap" style="gap:6px">
      <button class="btn sm icon ok-btn ${o.status === "confirmed" ? "on" : ""}" data-oid="${o.id}" data-st="confirmed" title="همین محصول است">${icon("check", "sm")}</button>
      <button class="btn sm icon no-btn ${o.status === "rejected" ? "on" : ""}" data-oid="${o.id}" data-st="rejected" title="محصول دیگری است">${icon("x", "sm")}</button>
    </div>` : html`<span></span>`}
  </div>${sellersTable(o.extra?.sellers)}`;
}
function siteGroup(site, offers, my) {
  const counted = offers.filter((o) => o.counted);
  const min = counted.length ? Math.min(...counted.map((o) => o.price)) : null;
  return html`<div class="site-group">
    <div class="site-head"><b>${siteName(site)}</b>
      <span class="small muted">${min ? html`ارزان‌ترین: <b class="num">${n(min)}</b> ${my ? gapBadge(Math.round(((my - min) / min) * 1000) / 10) : ""}` : "آگهی معتبر موجود نیست"} · ${n(offers.length)} آگهی</span></div>
    ${offers.map((o) => offerRow(o, my))}
  </div>`;
}

let detailChart = null;
export async function openProduct(id, { onChange } = {}) {
  const s = sheet({ title: "جزئیات محصول", side: true, size: "wide p-sheet", focus: false, body: html`<div class="skeleton" style="height:420px"></div>`,
    onClose: () => { detailChart?.destroy(); detailChart = null; hideTip(); } });
  const draw = async () => {
    const d = await api(`/api/pricing/products/${id}`);
    P.siteNames = { ...P.siteNames, ...d.site_names };
    const p = d.product, a = d.analysis;
    const bySite = {};
    d.offers.forEach((o) => (bySite[o.site] ||= []).push(o));
    const order = Object.keys(bySite).sort((x, y) => {
      const mx = Math.min(...bySite[x].filter((o) => o.counted).map((o) => o.price), Infinity);
      const my = Math.min(...bySite[y].filter((o) => o.counted).map((o) => o.price), Infinity);
      return mx - my;
    });
    s.root.querySelector(".sheet-head h2").textContent = p.name;
    s.root.querySelector(".sheet-body").innerHTML = String(html`<div class="stack">
      <div class="row">${img(p.image, "thumb lg")}<div class="grow" style="min-width:0">
        <div class="offer-meta">${p.brand ? html`<span class="badge">${p.brand}</span>` : ""}${posBadge(a.position)}
          ${p.permalink ? html`<a href="${safeUrl(p.permalink)}" target="_blank" rel="noopener">مشاهده در سایت شما ↗</a>` : ""}
          ${p.sku ? html`<span class="ltr">SKU: ${p.sku}</span>` : ""}</div></div></div>
      ${insightBox(a)}
      <div class="kv">
        <div><div class="k">قیمت شما</div><div class="v num">${n(a.my_price)}</div>${a.my_regular && a.my_regular > a.my_price ? html`<div class="small muted"><s>${n(a.my_regular)}</s></div>` : ""}</div>
        <div><div class="k">ارزان‌ترین رقیب</div><div class="v num">${n(a.min)}</div><div class="small muted">${a.cheapest_site ? siteName(a.cheapest_site) : ""}</div></div>
        <div><div class="k">میانه بازار</div><div class="v num">${n(a.median)}</div><div class="small muted">${a.index ? `شاخص ${nf1.format(a.index)}` : ""}</div></div>
        <div><div class="k">رتبه شما</div><div class="v">${a.rank ? `${n(a.rank)} از ${n(a.n_sites + 1)}` : "—"}</div><div class="small muted">۱ = ارزان‌ترین</div></div>
      </div>
      <section class="card"><div class="card-head"><h3>همه فروشنده‌ها روی یک خط</h3><p>هر نقطه یک آگهی است؛ راست = ارزان‌تر. نقطه توخالی = منتظر تأیید، کم‌رنگ = ناموجود</p></div>
        ${dotPlot(d.offers, a.my_price)}</section>
      <section class="card"><div class="card-head"><h3>روند قیمت</h3><p>قیمت شما در برابر ارزان‌ترین رقیب و میانه بازار</p></div>
        <div class="chart-box sm"><canvas id="histChart"></canvas></div>
        ${d.history.points.length < 2 ? html`<p class="small muted mt8">از بروزرسانی دوم به بعد روند نمایش داده می‌شود.</p>` : ""}</section>
      <div><div class="card-head"><h3>آگهی‌های رقبا</h3><p>تطبیق‌های مطمئن خودکار شمرده می‌شوند؛ بقیه را تأیید یا رد کنید تا دقیق‌تر شود</p></div>
        ${order.length ? order.map((k) => siteGroup(k, bySite[k], a.my_price)) : emptyState("search", "هنوز آگهی مشابهی در رقبا پیدا نشده")}</div>
      ${canEdit() ? html`<section class="card"><div class="card-head"><h3>${icon("sliders-horizontal", "sm")} دقیق‌ترش کنید</h3></div>
        <div class="stack s12">
          <div class="field"><label>لینک محصول در سایت رقیب را بچسبانید تا دستی وصل شود</label>
            <div class="row nowrap"><input class="input ltr" id="manualUrl" style="flex:1" placeholder="https://www.digikala.com/product/dkp-…">
              <button class="btn soft" id="manualBtn">افزودن</button></div></div>
          <div class="field"><label>عبارت جستجوی اختصاصی در رقبا (خالی = از نام محصول ساخته می‌شود)</label>
            <div class="row nowrap"><input class="input" id="customQ" style="flex:1" value="${p.search_query || ""}" placeholder="مثلاً: ریمل میبلین لش سنسیشنال">
              <button class="btn soft" id="customQBtn">ذخیره</button><button class="btn soft" id="recrawlBtn" title="فقط همین محصول را الان بخوان">${icon("refresh-cw", "sm")} بخوان</button></div></div>
          <label class="check"><span class="switch"><input type="checkbox" id="trackChk" ${p.tracked ? raw("checked") : ""}><span></span></span>این محصول پایش شود</label>
        </div></section>` : ""}
    </div>`);
    const root = s.root;
    root.querySelectorAll("[data-oid]").forEach((b) => (b.onclick = async () => {
      await api(`/api/pricing/offers/${b.dataset.oid}/status`, { method: "POST", body: { status: b.dataset.st } });
      refreshReviewCount();
      onChange && onChange();
      draw();
    }));
    root.querySelector("#manualBtn")?.addEventListener("click", async (e) => {
      const url = root.querySelector("#manualUrl").value.trim();
      if (!url) return;
      e.target.disabled = true;
      try {
        const r = await api(`/api/pricing/products/${id}/manual`, { method: "POST", body: { url } });
        toast(`اضافه شد: ${r.title}`);
        draw();
      } catch (err) { e.target.disabled = false; }
    });
    root.querySelector("#customQBtn")?.addEventListener("click", async () => {
      await api(`/api/pricing/products/${id}`, { method: "PATCH", body: { search_query: root.querySelector("#customQ").value } });
      toast("ذخیره شد؛ در بروزرسانی بعدی استفاده می‌شود");
    });
    root.querySelector("#recrawlBtn")?.addEventListener("click", () => startCrawl({ product_ids: [id] }));
    root.querySelector("#trackChk")?.addEventListener("change", async (e) => {
      await api(`/api/pricing/products/${id}`, { method: "PATCH", body: { tracked: e.target.checked } });
      toast(e.target.checked ? "پایش فعال شد" : "این محصول دیگر پایش نمی‌شود");
    });
    bindTips(root);
    drawHistory(root.querySelector("#histChart"), d.history.points);
  };
  try { await draw(); } catch (e) { s.close(); }
  return s;
}

function drawHistory(el, points) {
  detailChart?.destroy();
  detailChart = null;
  if (!el || !points.length || !window.Chart) return;
  const c = chartBase(el);
  const ds = (label, key, color, width) => ({
    label, data: points.map((p) => p[key]), borderColor: color, backgroundColor: color, borderWidth: width, stepped: true, spanGaps: true,
    pointRadius: points.length > 15 ? 0 : 3.5, pointBorderColor: c.surface, pointBorderWidth: 2,
  });
  detailChart = new Chart(el, {
    type: "line",
    data: { labels: points.map((p) => shortDate(p.ts)),
      datasets: [ds("قیمت شما", "my", c.accent, 2.5), ds("ارزان‌ترین رقیب", "min", c.market, 2), ds("میانه بازار", "median", c.market2, 2)] },
    options: lineOptions(c, (v) => short(v), (ctx) => {
      const p = points[ctx.dataIndex];
      if (ctx.datasetIndex === 1 && p.min) {
        const site = Object.entries(p.sites).find(([, v]) => v === p.min)?.[0];
        return `ارزان‌ترین رقیب: ${n(p.min)}${site ? ` (${siteName(site)})` : ""}`;
      }
      return `${ctx.dataset.label}: ${n(ctx.parsed.y)}`;
    }),
  });
}
