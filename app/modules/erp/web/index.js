// ERP module entry: what the shell needs to show this module (nav, pages, what the home page shows).
import { compact, fa } from "/static/js/kit.js";
import { erp, refreshMe } from "./erp.js";

// the module's pages, shown as tabs under the page title (settings live in Settings → فروشگاه و حسابداری)
const ADMIN_NAV = [
  { href: "", label: "داشبورد", ico: "layout-dashboard" },
  { href: "sell", label: "ثبت فروش و خرید", ico: "shopping-bag" },
  { href: "products", label: "انبار", ico: "package" },
  { href: "sales", label: "فروش‌ها", ico: "receipt" },
  { href: "purchases", label: "خریدها", ico: "truck" },
  { href: "expenses", label: "هزینه‌ها", ico: "banknote" },
  { href: "money", label: "حساب‌ها و شرکا", ico: "wallet" },
  { href: "reports", label: "گزارش‌ها", ico: "chart-column" },
  { href: "statements", label: "صورت‌های مالی", ico: "scale" },
  { href: "site", label: "همگام‌سازی سایت", ico: "globe" },
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
  css: ["/m/erp/erp.css"],
  nav: (role) => (role === "admin" ? ADMIN_NAV : SELLER_NAV),
  action: () => ({ href: "sell", label: "ثبت فروش", ico: "plus" }),
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
    statements: () => import("./pages/statements.js"),
    site: () => import("./pages/site.js"),
  },
  settings: () => import("./pages/settings.js"),
  // boot data (accounts, partners, channels, ...) is loaded once, the first time the module opens
  enter: async () => { if (!erp.me) await refreshMe(); },
  quick: (role) => [{ href: "#/erp/sell", label: "ثبت فروش", ico: "shopping-bag" },
    ...(role === "admin" ? [{ href: "#/erp/sell?mode=buy", label: "خرید کالا", ico: "truck" },
      { href: "#/erp/expenses/new", label: "ثبت هزینه", ico: "banknote" }] : [])],

  /** The unified home page: a headline, key numbers and what needs attention (see core/web/js/pages/home.js). */
  glance(d, role) {
    if (role !== "admin") {
      return {
        stats: [
          { label: "فروش ۳۰ روز اخیر", value: compact(d.month_total), unit: "تومان", href: "#/erp/sales" },
          { label: "پول نزد شما", value: compact(d.held), unit: "تومان" },
          { label: "پورسانت ۳۰ روز", value: compact(d.commission), unit: "تومان" },
        ],
        alerts: [],
      };
    }
    const alerts = [], site = d.site || {};
    if (d.out_count) alerts.push({ tone: "bad", ico: "ban", text: `${fa(d.out_count)} محصول ناموجود`, href: "#/erp/products?f=out" });
    if (d.low_count) alerts.push({ tone: "warn", ico: "triangle-alert", text: `${fa(d.low_count)} محصول رو به اتمام`, sub: "از «خرید کالا» دوباره پرش کنید", href: "#/erp/sell?mode=buy" });
    if (site.problems) alerts.push({ tone: "bad", ico: "cloud-off", text: `${fa(site.problems)} محصول با سایت هماهنگ نمی‌شود`, href: "#/erp/site" });
    if (site.nocount) alerts.push({ tone: "info", ico: "hash", text: `${fa(site.nocount)} محصول سایت شمارش نشده`, sub: "موجودی‌شان را یک بار در انبار اصلاح کنید", href: "#/erp/site" });
    if (d.period.unpaid) alerts.push({ tone: "info", ico: "clock", text: `${compact(d.period.unpaid)} تومان نسیه ۳۰ روز اخیر`, href: "#/erp/sales?unpaid=1" });
    return {
      headline: d.today.orders ? `امروز ${fa(d.today.orders)} فروش به مبلغ ${compact(d.today.revenue)} تومان` : "امروز هنوز فروشی ثبت نشده",
      stats: [
        { label: `فروش ${d.period_label}`, value: compact(d.period.revenue), unit: "تومان", foot: `${fa(d.period.orders)} سفارش`, href: "#/erp" },
        { label: "فروش امروز", value: compact(d.today.revenue), unit: d.today.revenue ? "تومان" : "", foot: `${fa(d.today.orders)} سفارش`, href: "#/erp/sales" },
        { label: "سود خالص ۳۰ روز", value: compact(d.period.net), unit: "تومان", tone: d.period.net < 0 ? "bad" : "", href: "#/erp/reports" },
        { label: "ارزش انبار", value: compact(d.stock_value), unit: "به قیمت خرید", href: "#/erp/products" },
      ],
      alerts,
    };
  },
};
