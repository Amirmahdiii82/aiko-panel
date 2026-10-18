// Shared UI kit for every module: money inputs (with amount in words), Jalali date field, chips, uploads,
// badges, KPI tiles, feed items. Module-specific widgets live in the module (e.g. /m/erp/erp.js).
import { $$, ago, compact, delegate, esc, fa, html, icon, jdate, moduleName, num, numWords, parseNum, popover, raw, state, toast, upload } from "./core.js";
import { MONTHS, WEEKDAYS, addDays, isoToJ, jToIso, monthLength, weekdayIndex } from "./jalali.js";

// ---------------------------------------------------------------- money input
export function moneyField({ name, label, value = "", hint = "", big = false, required = false, placeholder = "۰", suffix = "تومان", autofocus = false }) {
  const v = value === "" || value === null || value === undefined ? "" : num(value);
  return html`<div class="field">
    ${label ? html`<label>${label}${required ? " *" : ""}</label>` : ""}
    <div class="input-wrap">
      <input class="input money has-suffix ${big ? "big" : ""}" name="${name}" inputmode="numeric" autocomplete="off"
        value="${v}" placeholder="${placeholder}" data-money ${autofocus ? raw("autofocus") : ""}>
      <span class="suffix">${suffix}</span>
    </div>
    <div class="hint words" data-words-for="${name}">${value ? numWords(value) + " " + suffix : hint}</div>
  </div>`;
}
export function bindMoney(root) {
  delegate(root, "input", "input[data-money]", (e, el) => {
    const n = parseNum(el.value);
    const formatted = el.value.trim() === "" ? "" : num(n);
    if (el.value !== formatted) {
      el.value = formatted;
      el.setSelectionRange(el.value.length, el.value.length);
    }
    const w = root.querySelector(`[data-words-for="${el.name}"]`);
    if (w) {
      const suffix = el.parentElement.querySelector(".suffix")?.textContent || "";
      w.textContent = n ? `${numWords(n)} ${suffix}` : "";
    }
  });
}

// ---------------------------------------------------------------- Jalali date field
export function dateField({ name, label, value }) {
  return html`<div class="field">
    ${label ? html`<label>${label}</label>` : ""}
    <button type="button" class="input date-btn" data-date="${name}">
      <span data-date-label>${jdate(value, { weekday: true })}</span>${icon("calendar", "sm")}
    </button>
    <input type="hidden" name="${name}" value="${value || ""}">
  </div>`;
}
export function bindDates(root, onChange) {
  delegate(root, "click", "[data-date]", (e, btn) => {
    const input = root.querySelector(`input[name="${btn.dataset.date}"]`);
    datePicker(btn, input.value || state.me.today, (iso) => {
      input.value = iso;
      btn.querySelector("[data-date-label]").textContent = jdate(iso, { weekday: true });
      onChange && onChange(btn.dataset.date, iso);
    });
  });
}
export function datePicker(anchor, iso, onPick) {
  let [vy, vm] = isoToJ(iso);
  const sel = iso;
  const today = state.me.today;
  const render = () => {
    const first = jToIso(vy, vm, 1);
    const offset = weekdayIndex(first);
    const days = monthLength(vy, vm);
    let cells = WEEKDAYS.map((w) => `<span class="wd">${w}</span>`).join("");
    for (let i = 0; i < offset; i++) cells += "<span></span>";
    for (let d = 1; d <= days; d++) {
      const di = jToIso(vy, vm, d);
      const cls = [di === sel ? "sel" : "", di === today ? "today" : "", (offset + d - 1) % 7 === 6 ? "fri" : ""].join(" ");
      cells += `<button type="button" class="${cls}" data-day="${di}">${fa(d)}</button>`;
    }
    return `<div class="dp">
      <div class="dp-head">
        <button type="button" class="btn icon xs ghost" data-nav="-1" aria-label="ماه قبل">${icon("chevron-right", "sm")}</button>
        <div class="dp-title">${MONTHS[vm - 1]} ${fa(vy)}</div>
        <button type="button" class="btn icon xs ghost" data-nav="1" aria-label="ماه بعد">${icon("chevron-left", "sm")}</button>
      </div>
      <div class="dp-grid">${cells}</div>
      <div class="row mt8"><button type="button" class="btn xs soft" data-day="${today}">امروز</button>
        <button type="button" class="btn xs ghost" data-yesterday>دیروز</button></div>
    </div>`;
  };
  popover(anchor, render(), (pop, close) => {
    pop.addEventListener("click", (e) => {
      const nav = e.target.closest("[data-nav]");
      if (nav) {
        vm += Number(nav.dataset.nav);
        if (vm < 1) { vm = 12; vy--; }
        if (vm > 12) { vm = 1; vy++; }
        pop.innerHTML = render();
        return;
      }
      const day = e.target.closest("[data-day]");
      if (day) { onPick(day.dataset.day); close(); return; }
      if (e.target.closest("[data-yesterday]")) { onPick(addDays(today, -1)); close(); }
    });
  });
}

// ---------------------------------------------------------------- chip choices (radio-like)
export function choiceChips(name, options, selected, { big = false, cls = "" } = {}) {
  return html`<div class="chips ${cls}" data-choice="${name}">
    ${options.map((o) => html`<button type="button" class="chip ${big ? "big" : ""} ${String(o.value) === String(selected) ? "on" : ""}"
      data-value="${o.value}">${o.icon ? icon(o.icon, "sm") : ""}${o.label}</button>`)}
    <input type="hidden" name="${name}" value="${selected ?? ""}">
  </div>`;
}
export function bindChoices(root, onChange) {
  delegate(root, "click", "[data-choice] .chip", (e, chip) => {
    const group = chip.closest("[data-choice]");
    group.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === chip));
    group.querySelector("input[type=hidden]").value = chip.dataset.value;
    onChange && onChange(group.dataset.choice, chip.dataset.value);
  });
}

// ---------------------------------------------------------------- receipt upload
export function uploadField({ name, label = "عکس رسید / فاکتور", value = "" }) {
  return html`<div class="field">
    <label>${label}</label>
    <label class="upload-box" data-upload="${name}">
      <span data-preview>${value ? previewHtml(value) : html`<span class="thumb">${icon("camera")}</span>`}</span>
      <span class="grow"><b data-upload-text>${value ? "رسید پیوست شد" : "عکس بگیرید یا فایل انتخاب کنید"}</b><br>
        <span class="small muted">عکس کارت‌خوان، فاکتور یا PDF</span></span>
      <input type="file" accept="image/*,application/pdf" capture="environment" hidden>
    </label>
    <input type="hidden" name="${name}" value="${value || ""}">
  </div>`;
}
function previewHtml(path) {
  if (path.toLowerCase().endsWith(".pdf")) return html`<span class="thumb">${icon("file-text")}</span>`;
  return html`<img src="/uploads/${path}" alt="">`;
}
export function bindUploads(root) {
  delegate(root, "change", "[data-upload] input[type=file]", async (e, input) => {
    const box = input.closest("[data-upload]");
    const file = input.files[0];
    if (!file) return;
    box.querySelector("[data-upload-text]").textContent = "در حال بارگذاری…";
    try {
      const file2 = file.type.startsWith("image/") && file.size > 1.5e6 ? await shrinkImage(file) : file;
      const res = await upload(file2);
      root.querySelector(`input[name="${box.dataset.upload}"]`).value = res.path;
      box.querySelector("[data-preview]").innerHTML = String(previewHtml(res.path));
      box.querySelector("[data-upload-text]").textContent = "رسید پیوست شد ✓";
    } catch (err) {
      box.querySelector("[data-upload-text]").textContent = "بارگذاری نشد؛ دوباره امتحان کنید";
    }
  });
}
/** Phone photos are huge; resize to ~1600px JPEG before upload. */
function shrinkImage(file) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * scale);
      c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      c.toBlob((b) => resolve(b ? new File([b], "receipt.jpg", { type: "image/jpeg" }) : file), "image/jpeg", 0.82);
    };
    img.onerror = () => resolve(file);
    img.src = URL.createObjectURL(file);
  });
}
export function receiptLink(path) {
  if (!path) return "";
  if (path.toLowerCase().endsWith(".pdf")) return html`<a class="btn xs soft" href="/uploads/${path}" target="_blank">${icon("file-text", "sm")} رسید</a>`;
  return html`<a href="/uploads/${path}" target="_blank" title="نمایش رسید"><img class="receipt-thumb" src="/uploads/${path}" alt="رسید"></a>`;
}

// ---------------------------------------------------------------- form data
export function formData(root) {
  const out = {};
  root.querySelectorAll("input[name], select[name], textarea[name]").forEach((el) => {
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.dataset.money !== undefined || el.dataset.num !== undefined) out[el.name] = el.value.trim() === "" ? null : parseNum(el.value);
    else out[el.name] = el.value;
  });
  return out;
}

// ---------------------------------------------------------------- display bits
export function thumb(p, size = "") {
  const img = p && p.image;
  return html`<span class="thumb ${size}">${img ? html`<img src="${img}" alt="" loading="lazy" referrerpolicy="no-referrer">` : icon("package", "sm")}</span>`;
}
export function emptyState(ico, title, text = "", action = "") {
  return html`<div class="empty"><div class="blob">${icon(ico)}</div><h3>${title}</h3>${text ? html`<p class="small">${text}</p>` : ""}${action}</div>`;
}
export function kpi({ label, value, unit = "", foot = "", color = "", ico = "", title = "" }) {
  return html`<div class="kpi ${color}" title="${title}">
    ${ico ? html`<span class="k-icon">${icon(ico)}</span>` : ""}
    <div class="k-label">${label}</div>
    <div class="k-value num">${value}${unit ? html`<span class="k-unit">${unit}</span>` : ""}</div>
    ${foot ? html`<div class="k-foot">${foot}</div>` : ""}
  </div>`;
}
export function moneyKpi(opts) {
  return kpi({ ...opts, value: compact(opts.amount), unit: "تومان", title: `${num(opts.amount)} تومان` });
}
export function delta(cur, prev) {
  if (!prev) return cur ? html`<span class="delta up">جدید</span>` : "";
  const d = (cur - prev) / Math.abs(prev);
  const cls = Math.abs(d) < 0.005 ? "flat" : d > 0 ? "up" : "down";
  const sign = d > 0 ? "+" : d < 0 ? "−" : "";
  return html`<span class="delta ${cls}">${sign}${new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 }).format(Math.abs(d) * 100)}٪</span>`;
}
export function barList(items, { label, value, fmt = (v) => compact(v), sub, colors = true } = {}) {
  const max = Math.max(1, ...items.map((i) => Math.abs(value(i))));
  return html`<div class="bars">${items.map((it, idx) => html`<div class="bar-row">
    <div class="bar-top"><span class="ellipsis">${label(it)}${sub ? html` <span class="muted small">${sub(it)}</span>` : ""}</span><b class="num nowrap">${fmt(value(it))}</b></div>
    <div class="bar-track"><div class="bar-fill ${colors ? "c" + ((idx % 5) + 1) : ""}" style="width:${Math.max(2, (Math.abs(value(it)) / max) * 100)}%"></div></div>
  </div>`)}</div>`;
}
const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter("fa", { granularity: "grapheme" }) : null;
/** First visible character (a whole emoji or accented letter, never half of one). */
function initial(name) {
  const s = String(name || "").trim() || "?";
  if (segmenter) return segmenter.segment(s)[Symbol.iterator]().next().value.segment.toUpperCase();
  return Array.from(s)[0].toUpperCase();
}
export function avatar(name, cls = "") {
  return html`<span class="avatar ${cls}">${initial(name)}</span>`;
}
export function copyText(text) {
  navigator.clipboard?.writeText(text).then(() => toast("کپی شد"), () => toast("کپی نشد", "error"));
}
export function selectOptions(options, selected, placeholder = "") {
  return html`${placeholder ? html`<option value="">${placeholder}</option>` : ""}${options.map((o) =>
    html`<option value="${o.value}" ${String(o.value) === String(selected ?? "") ? raw("selected") : ""}>${o.label}</option>`)}`;
}
export function feedItem(a, { showModule = false } = {}) {
  return html`<div class="feed-item ${a.link ? "clickable" : ""}" data-link="${a.link || ""}">
    <span class="feed-icon ${a.level}">${icon(KIND_ICON[a.kind] || LEVEL_ICON[a.level] || "info")}</span>
    <div class="feed-body"><div class="feed-title">${a.title}${showModule && a.module ? html` <span class="role-pill">${moduleName(a.module)}</span>` : ""}</div>${a.body ? html`<div class="feed-text">${a.body}</div>` : ""}</div>
    <span class="feed-time" title="${a.created_at}">${ago(a.created_at)}</span>
  </div>`;
}
export const KIND_ICON = {
  sale: "shopping-bag", sale_void: "undo-2", stock_out: "ban", low_stock: "triangle-alert", purchase: "truck",
  expense: "banknote", adjust: "package", transfer: "arrow-left-right", capital: "piggy-bank", sync_error: "cloud-off",
  sync_warning: "triangle-alert", import: "file-spreadsheet", woo: "globe", woo_link: "link", product: "package-plus",
  split: "split", user: "user-plus", woo_import: "cloud-upload",
  crawl_done: "chart-line", crawl_failed: "cloud-off", video_done: "clapperboard", video_failed: "circle-alert",
  backup: "database", integrations: "plug", full_sync: "refresh-cw", merge: "merge", purchase_void: "undo-2",
  partners: "users",
};
// fallback by severity for kinds without their own icon (a kind added later must never break the feed)
export const LEVEL_ICON = { success: "circle-check", warning: "triangle-alert", danger: "circle-alert", info: "info" };
export { esc };
