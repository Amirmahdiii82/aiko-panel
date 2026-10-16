// ERP module entry: what the shell needs to show this module (nav, pages, home card).
import { compact, fa, html, icon, toman } from "/static/js/kit.js";
import { erp, refreshMe } from "./erp.js";

const ADMIN_NAV = [
  { href: "", label: "داشبورد فروشگاه", ico: "layout-dashboard" },
  { href: "sell", label: "فروش سریع", ico: "shopping-bag" },
  { href: "products", label: "محصولات و انبار", ico: "package" },
  { href: "sales", label: "فروش‌ها", ico: "receipt" },
  { section: "مالی" },
  { href: "purchases", label: "خرید کالا", ico: "truck" },
  { href: "expenses", label: "هزینه‌ها", ico: "banknote" },
  { href: "money", label: "حساب‌ها و شرکا", ico: "wallet" },
  { href: "reports", label: "گزارش‌ها", ico: "chart-column" },
  { section: "فروشگاه" },
  { href: "site", label: "اتصال سایت", ico: "globe" },
  { href: "settings", label: "تنظیمات فروشگاه", ico: "settings" },
];
const SELLER_NAV = [
  { href: "", label: "خانه", ico: "house" },
  { href: "sell", label: "ثبت فروش", ico: "shopping-bag" },
  { href: "products", label: "موجودی محصولات", ico: "package" },
  { href: "sales", label: "فروش‌های من", ico: "receipt" },
];
const SELLER_PAGES = ["", "sell", "products", "sales"];

export default {
  id: "erp",
  nav: (role) => (role === "admin" ? ADMIN_NAV : SELLER_NAV),
  mobile: (role) => role === "admin"
    ? [{ href: "", label: "فروشگاه", ico: "layout-dashboard" }, { href: "products", label: "انبار", ico: "package" },
      { href: "sell", label: "فروش", ico: "plus", fab: true }, { href: "expenses", label: "هزینه", ico: "banknote" }]
    : [{ href: "", label: "خانه", ico: "house" }, { href: "products", label: "موجودی", ico: "package" },
      { href: "sell", label: "فروش", ico: "plus", fab: true }, { href: "sales", label: "فروش‌ها", ico: "receipt" }],
  action: () => ({ href: "sell", label: "فروش سریع", ico: "plus" }),
  allowed: (role, page) => role === "admin" || SELLER_PAGES.includes(page),
  pages: {
    "": () => import("./pages/dashboard.js"),
    sell: () => import("./pages/sell.js"),
    products: () => import("./pages/products.js"),
    sales: () => import("./pages/sales.js"),
    purchases: () => import("./pages/purchases.js"),
    expenses: () => import("./pages/expenses.js"),
    money: () => import("./pages/money.js"),
    reports: () => import("./pages/reports.js"),
    site: () => import("./pages/site.js"),
    settings: () => import("./pages/settings.js"),
  },
  // boot data (accounts, partners, channels, ...) is loaded once, the first time the module opens
  enter: async () => { if (!erp.me) await refreshMe(); },
  quick: (role) => [{ href: "#/erp/sell", label: "فروش سریع", sub: "ثبت فروش از هر کانال", ico: "shopping-bag", color: "#F4907E" },
    ...(role === "admin" ? [{ href: "#/erp/expenses/new", label: "ثبت هزینه", sub: "با عکس رسید", ico: "banknote", color: "#C87FAF" }] : [])],

  /** Card on the unified home page. */
  home(d, role) {
    if (role !== "admin") {
      return html`<div class="grid g3">
        <div class="mini-stat"><span>فروش ۳۰ روز اخیر</span><b class="num">${compact(d.month_total)}</b><small>تومان</small></div>
        <div class="mini-stat"><span>پول نزد شما</span><b class="num">${compact(d.held)}</b><small>تومان</small></div>
        <div class="mini-stat"><span>پورسانت</span><b class="num">${compact(d.commission)}</b><small>تومان</small></div>
      </div>`;
    }
    const alerts = [];
    if (d.out_count) alerts.push(html`<a class="badge bad" href="#/erp/products?f=out">${icon("ban")}${fa(d.out_count)} ناموجود</a>`);
    if (d.low_count) alerts.push(html`<a class="badge warn" href="#/erp/products?f=low">${icon("triangle-alert")}${fa(d.low_count)} رو به اتمام</a>`);
    if (d.sync_errors) alerts.push(html`<a class="badge bad" href="#/erp/site">${icon("cloud-off")}${fa(d.sync_errors)} خطای سایت</a>`);
    if (d.month.unpaid) alerts.push(html`<a class="badge coral" href="#/erp/sales?unpaid=1">${icon("clock")}${compact(d.month.unpaid)} نسیه</a>`);
    return html`<div class="grid g4">
        <div class="mini-stat"><span>فروش امروز</span><b class="num">${compact(d.today.revenue)}</b><small>${fa(d.today.orders)} سفارش</small></div>
        <div class="mini-stat"><span>فروش ${d.month_label}</span><b class="num">${compact(d.month.revenue)}</b><small>تومان</small></div>
        <div class="mini-stat"><span>سود خالص ماه</span><b class="num ${d.month.net < 0 ? "bad-ink" : ""}">${compact(d.month.net)}</b><small>تومان</small></div>
        <div class="mini-stat"><span>ارزش انبار</span><b class="num">${compact(d.stock_value)}</b><small title="${toman(d.stock_value)}">به قیمت خرید</small></div>
      </div>
      ${alerts.length ? html`<div class="chips mt12">${alerts}</div>` : html`<p class="small muted mt12">${icon("circle-check", "sm")} موردی برای رسیدگی نیست.</p>`}`;
  },
};
