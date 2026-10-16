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
  if (p.stock <= 0) return html`<span class="badge bad">${icon("ban")}ناموجود${p.stock < 0 ? ` (${fa(p.stock)})` : ""}</span>`;
  if (p.stock <= p.low_stock) return html`<span class="badge warn">${fa(p.stock)} عدد</span>`;
  return html`<span class="badge ok">${fa(p.stock)} عدد</span>`;
}
export function wooBadge(p) {
  if (!p.woo_id) return html`<span class="badge" title="به محصول سایت وصل نیست">${icon("unlink")}وصل نیست</span>`;
  if (p.woo_state === "pending") return html`<span class="badge info" title="در صف ارسال به سایت">${icon("loader-circle")}در صف</span>`;
  if (p.woo_state === "error") return html`<span class="badge bad" title="${p.woo_error || ""}">${icon("cloud-off")}خطا</span>`;
  if (p.woo_state === "ok") return html`<span class="badge ok" title="موجودی سایت هماهنگ است">${icon("globe")}هماهنگ</span>`;
  return html`<span class="badge primary" title="وصل است ولی هنوز موجودی ارسال نشده">${icon("link")}وصل</span>`;
}
