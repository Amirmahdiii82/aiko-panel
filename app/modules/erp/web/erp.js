// ERP state and ERP-only helpers (accounts, channels, stock and site badges).
// `erp.me` is the ERP boot data (accounts, partners, channels, settings, ...) loaded when the module opens.
import { api, choiceChips, fa, html, icon, selectOptions } from "/static/js/kit.js";

export const erp = { me: null };

export async function refreshMe() {
  erp.me = await api("/api/erp/me");
  return erp.me;
}

/** ERP manager (owner or someone granted the ERP "admin" role); sellers see a reduced app. */
export const isAdmin = () => erp.me?.user?.role === "admin";
export const accountName = (id) => (erp.me.accounts.find((a) => a.id === id) || {}).name || "";
export const channelName = (c) => (erp.me.channels || {})[c] || c;
export const CHANNEL_ICON = { website: "globe", instagram: "instagram", in_person: "handshake", agent: "users", other: "tag" };

export function partnerColor(id) {
  const p = erp.me.partners.find((x) => x.id === id);
  return (p && p.color) || "#796C9D";
}
export function accountOptions(selected, { includeEmpty = "", kinds = null } = {}) {
  const accs = erp.me.accounts.filter((a) => a.active && (!kinds || kinds.includes(a.kind)));
  return selectOptions(accs.map((a) => ({ value: a.id, label: a.name })), selected, includeEmpty);
}
export function accountChoice(name, selected, { kinds = null } = {}) {
  const accs = erp.me.accounts.filter((a) => a.active && (!kinds || kinds.includes(a.kind)));
  return choiceChips(name, accs.map((a) => ({
    value: a.id, label: a.name, icon: a.kind === "partner" ? "credit-card" : a.kind === "agent" ? "user" : "landmark",
  })), selected);
}
export function stockBadge(p) {
  // the site sells it without counting: unknown here until someone counts it (site page → شمارش برای سایت)
  if (p.stock <= 0 && p.woo_state === "nocount" && p.woo_in_stock) return html`<span class="badge warn" title="در سایت موجود است ولی تعدادش شمرده نشده">${icon("hash")}شمارش نشده</span>`;
  if (p.stock <= 0) return html`<span class="badge bad">${icon("ban")}ناموجود${p.stock < 0 ? ` (${fa(p.stock)})` : ""}</span>`;
  if (p.stock <= p.low_stock) return html`<span class="badge warn">${fa(p.stock)} عدد</span>`;
  return html`<span class="badge ok">${fa(p.stock)} عدد</span>`;
}
/** Two-way stock sync state of a linked product (see stocksync.py). */
export const WOO_STATE = {
  ok: { cls: "ok", ico: "globe", label: "هماهنگ", tip: "موجودی اینجا و سایت یکی است" },
  pending: { cls: "info", ico: "loader-circle", label: "در حال ارسال", tip: "تغییر اینجا چند ثانیه دیگر در سایت هم اعمال می‌شود" },
  force: { cls: "info", ico: "loader-circle", label: "در حال ارسال", tip: "عدد اینجا روی سایت گذاشته می‌شود" },
  conflict: { cls: "warn", ico: "scale", label: "اختلاف با سایت", tip: "از قبل، عدد اینجا و سایت فرق داشت؛ یک بار انتخاب کنید کدام درست است (صفحه اتصال سایت)" },
  drift: { cls: "warn", ico: "refresh-cw", label: "تغییر در سایت", tip: "موجودی در خود سایت عوض شده؛ بعد از بررسی دوم اینجا هم اعمال می‌شود" },
  nocount: { cls: "", ico: "hash", label: "سایت تعداد ندارد", tip: "در سایت مدیریت موجودی خاموش است؛ با شمارش اینجا، سایت هم عدد می‌گیرد" },
  whole: { cls: "warn", ico: "split", label: "همه رنگ‌ها با هم", tip: "به کل محصول رنگ‌دار وصل است؛ برای همگام‌سازی به رنگ‌ها تفکیک کنید" },
  gone: { cls: "bad", ico: "circle-off", label: "در سایت نیست", tip: "این محصول در سایت پیدا نشد (حذف شده؟)" },
  error: { cls: "bad", ico: "cloud-off", label: "خطا", tip: "" },
};
export function wooBadge(p) {
  if (!p.woo_id) return html`<span class="badge" title="به محصول سایت وصل نیست">${icon("unlink")}وصل نیست</span>`;
  const st = WOO_STATE[p.woo_state];
  if (!st) return html`<span class="badge primary" title="وصل است؛ در بررسی بعدی با سایت مقایسه می‌شود">${icon("link")}وصل</span>`;
  return html`<span class="badge ${st.cls}" title="${p.woo_state === "error" ? p.woo_error || "" : st.tip}">${icon(st.ico)}${st.label}</span>`;
}
