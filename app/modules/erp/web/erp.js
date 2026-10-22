// ERP state and ERP-only helpers (accounts, channels, stock and site badges).
// `erp.me` is the ERP boot data (accounts, partners, channels, settings, ...) loaded when the module opens.
import { api, choiceChips, confirmBox, delegate, fa, html, icon, receiptLink, selectOptions, toast, upload } from "/static/js/kit.js";

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
/** Stock sync state of a linked product (see site/stock.py: the panel keeps stock, the site shows it). */
export const WOO_STATE = {
  ok: { cls: "ok", ico: "globe", label: "هماهنگ", tip: "موجودی اینجا و سایت یکی است" },
  pending: { cls: "info", ico: "loader-circle", label: "در حال ارسال", tip: "چند ثانیه دیگر سایت همین عدد را نشان می‌دهد" },
  differ: { cls: "warn", ico: "scale", label: "عدد متفاوت", tip: "همگام‌سازی هنوز شروع نشده (صفحه اتصال سایت)" },
  nocount: { cls: "", ico: "hash", label: "سایت تعداد ندارد", tip: "در سایت مدیریت موجودی خاموش است؛ در صفحه اتصال سایت یک بار بشمارید" },
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

/** The receipt of a sale or purchase: see it, add or replace it (photo or PDF), remove it, open it in Google Drive. */
export function receiptBox(receipt, driveLink) {
  return html`<div class="receipt-box">
    ${receipt ? receiptLink(receipt) : html`<span class="thumb">${icon("paperclip", "sm")}</span>`}
    <div class="grow"><b class="small">${receipt ? "رسید پیوست است" : "رسیدی پیوست نشده"}</b>
      <div class="tiny muted">${driveLink ? html`<a href="${driveLink}" target="_blank" rel="noopener">${icon("folder", "sm")} در گوگل درایو</a>` : receipt ? "عکس یا PDF" : "عکس فاکتور، کارت‌خوان یا PDF"}</div></div>
    <label class="btn xs soft">${receipt ? "تعویض" : html`${icon("plus", "sm")} افزودن`}<input type="file" accept="image/*,application/pdf" hidden data-receipt-file></label>
    ${receipt ? html`<button class="btn xs ghost icon" data-receipt-remove aria-label="حذف رسید" title="حذف رسید">${icon("trash-2", "sm")}</button>` : ""}
  </div>`;
}
export function bindReceiptBox(root, kind, id, done) {
  const save = async (path) => {
    const r = await api(`/api/erp/${kind}/${id}/receipt`, { method: "PUT", body: { receipt: path } });
    toast(path ? "رسید ذخیره شد" : "رسید حذف شد");
    done?.(r);
  };
  delegate(root, "change", "[data-receipt-file]", async (e, input) => {
    const file = input.files[0];
    if (!file) return;
    input.closest(".receipt-box").classList.add("busy");
    try { await save((await upload(file)).path); } finally { input.value = ""; }
  });
  delegate(root, "click", "[data-receipt-remove]", async () => {
    if (await confirmBox("رسید حذف شود؟", { danger: true, okText: "حذف" })) save(null);
  });
}
