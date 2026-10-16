// Shared helpers for the shell and every module: API calls, HTML templating, formatting,
// overlays (sheet, toast, confirm), icons, and who is signed in.
import { ICONS } from "./icons.js";
import { MONTHS, isoToJ } from "./jalali.js";

// ---------------------------------------------------------------- state & events
export const state = { me: null, live: false };
const listeners = new Map();
export function on(evt, fn) {
  if (!listeners.has(evt)) listeners.set(evt, new Set());
  listeners.get(evt).add(fn);
  return () => listeners.get(evt).delete(fn);
}
export function emit(evt, data) {
  (listeners.get(evt) || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } });
}

// ---------------------------------------------------------------- API
export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
export async function api(path, { method = "GET", body, form, quiet } = {}) {
  const opts = { method, headers: { "x-aiko": "1" }, credentials: "same-origin" };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.headers["content-type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    const err = new ApiError("ارتباط با سرور برقرار نشد. اینترنت را چک کنید.", 0);
    if (!quiet) toast(err.message, "error");
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (res.status === 401 && !path.endsWith("/login")) {
    emit("logout");
    throw new ApiError("ابتدا وارد شوید", 401);
  }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("، ");
    const err = new ApiError(msg || `خطا (${res.status})`, res.status);
    if (!quiet) toast(err.message, "error");
    throw err;
  }
  return data;
}
export async function upload(file) {
  const form = new FormData();
  form.append("file", file);
  return api("/api/uploads", { method: "POST", form });
}

// ---------------------------------------------------------------- templating
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(s);
function val(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(val).join("");
  if (v === null || v === undefined || v === false) return "";
  return esc(v);
}
/** html`<b>${x}</b>` escapes interpolations; returns a Raw so templates can nest. */
export function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) out += val(values[i]) + strings[i + 1];
  return new Raw(out);
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
/** Delegated event: on root, for elements matching selector. */
export function delegate(root, type, selector, fn) {
  const handler = (e) => {
    const el = e.target.closest(selector);
    if (el && root.contains(el)) fn(e, el);
  };
  root.addEventListener(type, handler);
  return () => root.removeEventListener(type, handler);
}
export function icon(name, cls = "") {
  return raw(`<svg class="i ${cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`);
}

// ---------------------------------------------------------------- formatting
const nf = new Intl.NumberFormat("fa-IR");
const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
export const fa = (v) => String(v ?? "").replace(/\d/g, (d) => FA_DIGITS[d]);
export const num = (n) => nf.format(Math.round(Number(n) || 0));
export const money = (n) => num(n);
export const toman = (n) => `${num(n)} تومان`;
export function compact(n) {
  n = Math.round(Number(n) || 0);
  const a = Math.abs(n);
  const f = (x, d) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: d }).format(x);
  if (a >= 1e9) return `${f(n / 1e9, 2)} میلیارد`;
  if (a >= 1e6) return `${f(n / 1e6, a >= 1e8 ? 0 : a >= 1e7 ? 1 : 2)} میلیون`;
  if (a >= 1e3) return `${f(n / 1e3, 0)} هزار`;
  return f(n, 0);
}
export const pct = (x, d = 0) => `${new Intl.NumberFormat("fa-IR", { maximumFractionDigits: d }).format((x || 0) * 100)}٪`;
export function parseNum(s) {
  if (typeof s === "number") return s;
  const latin = String(s ?? "").replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
  const neg = /^\s*[-−]/.test(latin);
  const digits = latin.replace(/[^\d.]/g, "");
  const v = parseFloat(digits) || 0;
  return neg ? -v : v;
}
export function jdate(iso, { year = true, weekday = false } = {}) {
  if (!iso) return "";
  const [y, m, d] = isoToJ(iso);
  const wd = weekday ? new Intl.DateTimeFormat("fa-IR", { weekday: "long" }).format(new Date(iso.slice(0, 10) + "T12:00:00")) + " " : "";
  return `${wd}${fa(d)} ${MONTHS[m - 1]}${year ? " " + fa(y) : ""}`;
}
export function jdateNum(iso) {
  if (!iso) return "";
  const [y, m, d] = isoToJ(iso);
  return fa(`${y}/${String(m).padStart(2, "0")}/${String(d).padStart(2, "0")}`);
}
export function ago(ts) {
  if (!ts) return "";
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 50) return "همین الان";
  if (diff < 3600) return `${fa(Math.round(diff / 60))} دقیقه پیش`;
  if (diff < 86400) return `${fa(Math.round(diff / 3600))} ساعت پیش`;
  if (diff < 86400 * 7) return `${fa(Math.round(diff / 86400))} روز پیش`;
  return jdate(ts.slice(0, 10));
}
export function timeOf(ts) {
  if (!ts) return "";
  return fa(ts.slice(11, 16));
}

// Persian number to words (for amounts: «پانصد و چهل هزار تومان»)
const ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"];
const TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"];
const TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"];
const HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"];
const SCALES = ["", "هزار", "میلیون", "میلیارد", "هزار میلیارد"];
function words3(n) {
  const parts = [];
  const h = Math.floor(n / 100), r = n % 100;
  if (h) parts.push(HUNDREDS[h]);
  if (r >= 10 && r < 20) parts.push(TEENS[r - 10]);
  else {
    if (Math.floor(r / 10)) parts.push(TENS[Math.floor(r / 10)]);
    if (r % 10) parts.push(ONES[r % 10]);
  }
  return parts.join(" و ");
}
export function numWords(n) {
  n = Math.round(Math.abs(Number(n) || 0));
  if (!n) return "";
  const parts = [];
  let i = 0;
  while (n > 0 && i < SCALES.length) {
    const chunk = n % 1000;
    if (chunk) parts.unshift(words3(chunk) + (SCALES[i] ? " " + SCALES[i] : ""));
    n = Math.floor(n / 1000);
    i++;
  }
  return parts.join(" و ");
}

// ---------------------------------------------------------------- overlays
export function toast(message, type = "success", { action, timeout = 4200 } = {}) {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const ico = type === "error" ? "circle-alert" : type === "info" ? "info" : "circle-check";
  el.innerHTML = `<span class="t-ico">${icon(ico)}</span><span class="t-msg">${esc(message)}</span>`;
  if (action) {
    const b = document.createElement("button");
    b.className = "btn sm soft";
    b.textContent = action.label;
    b.onclick = () => { action.fn(); el.remove(); };
    el.appendChild(b);
  }
  box.appendChild(el);
  setTimeout(() => el.remove(), timeout);
}

const openSheets = [];
/** Open a dialog. body may be html`` or a string. Returns { root, close }. */
export function sheet({ title = "", body = "", foot = "", size = "", side = false, onClose, focus = true } = {}) {
  const scrim = document.createElement("div");
  scrim.className = "scrim" + (side ? " side-mode" : "");
  scrim.innerHTML = `
    <div class="sheet ${size} ${side ? "side" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="sheet-head"><h2>${esc(title)}</h2>
        <button class="btn icon sm ghost" data-close aria-label="بستن">${icon("x")}</button></div>
      <div class="sheet-body">${body}</div>
      ${foot ? `<div class="sheet-foot">${foot}</div>` : ""}
    </div>`;
  document.body.appendChild(scrim);
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => scrim.classList.add("show"));
  const root = scrim.querySelector(".sheet");
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    scrim.classList.remove("show");
    const i = openSheets.indexOf(api_);
    if (i >= 0) openSheets.splice(i, 1);
    if (!openSheets.length) document.body.style.overflow = "";
    setTimeout(() => scrim.remove(), 200);
    onClose && onClose();
  };
  const api_ = { root, close, scrim };
  openSheets.push(api_);
  scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) close(); });
  root.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  if (focus) setTimeout(() => {
    const first = root.querySelector("[autofocus], .sheet-body input:not([type=hidden]):not([type=checkbox]), .sheet-body select");
    if (first && window.matchMedia("(min-width: 901px)").matches) first.focus();
  }, 120);
  return api_;
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && openSheets.length && !document.querySelector(".pop")) openSheets[openSheets.length - 1].close();
});
export function closeAllSheets() { [...openSheets].forEach((s) => s.close()); }

export function confirmBox(message, { okText = "بله", danger = false, title = "مطمئنید؟", input = null } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const s = sheet({
      title,
      body: html`<p style="line-height:1.9">${message}</p>${input ? html`<div class="field mt16"><label>${input}</label><input class="input" id="cb-input"></div>` : ""}`,
      foot: html`<button class="btn ${danger ? "danger" : "primary"}" id="cb-ok">${okText}</button><button class="btn ghost" data-close>انصراف</button>`,
      onClose: () => { if (!done) resolve(false); },
    });
    s.root.querySelector("#cb-ok").onclick = () => {
      done = true;
      const v = input ? s.root.querySelector("#cb-input").value : true;
      s.close();
      resolve(input ? { value: v } : true);
    };
  });
}

/** A popover anchored to an element (used by the date picker). */
export function popover(anchor, content, onMount) {
  document.querySelectorAll(".pop").forEach((p) => p.remove());
  const pop = document.createElement("div");
  pop.className = "pop";
  pop.innerHTML = content;
  document.body.appendChild(pop);
  const r = anchor.getBoundingClientRect();
  const w = pop.offsetWidth, h = pop.offsetHeight;
  let left = r.right - w;
  if (left < 8) left = 8;
  if (left + w > window.innerWidth - 8) left = window.innerWidth - w - 8;
  let top = r.bottom + 8;
  if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
  pop.style.left = `${left + window.scrollX}px`;
  pop.style.top = `${top + window.scrollY}px`;
  pop.style.position = "absolute";
  const close = () => { pop.remove(); document.removeEventListener("mousedown", outside, true); document.removeEventListener("keydown", esc_, true); };
  const outside = (e) => { if (!pop.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) close(); };
  const esc_ = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  setTimeout(() => { document.addEventListener("mousedown", outside, true); document.addEventListener("keydown", esc_, true); });
  onMount && onMount(pop, close);
  return close;
}

export function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
export function storage(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem("aiko-" + key) || "null");
    localStorage.setItem("aiko-" + key, JSON.stringify(value));
  } catch (e) { return null; }
}
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ---------------------------------------------------------------- who is signed in
/** Owner of the business: every module plus team and system settings. */
export const isOwner = () => !!(state.me && state.me.user.is_admin);
/** The user's role in a module ("admin", "seller", "editor", ...) or undefined without access. */
export const moduleRole = (id) => state.me && state.me.user.modules[id];
export const hasModule = (id) => moduleRole(id) !== undefined;
/** Display name of a module id ("core" = system events). */
export function moduleName(id) {
  if (!id || id === "core") return "سیستم";
  return (state.me?.modules || []).find((m) => m.id === id)?.name || id;
}
