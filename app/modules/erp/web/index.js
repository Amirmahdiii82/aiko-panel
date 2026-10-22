// ERP module entry: what the shell needs to show this module (nav, pages, what the home page shows).
import { compact, fa } from "/static/js/kit.js";
import { erp, refreshMe } from "./erp.js";

const ADMIN_NAV = [
  { href: "", label: "داشبورد فروشگاه", ico: "layout-dashboard" },
  { href: "sell", label: "ثبت فروش و خرید", ico: "shopping-bag" },
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
  css: ["/m/erp/erp.css"],
  nav: (role) => (role === "admin" ? ADMIN_NAV : SELLER_NAV),
  mobile: (role) => role === "admin"
    ? [{ href: "", label: "فروشگاه", ico: "layout-dashboard" }, { href: "products", label: "انبار", ico: "package" },
      { href: "sell", label: "فروش", ico: "plus", fab: true }, { href: "expenses", label: "هزینه", ico: "banknote" }]
    : [{ href: "", label: "خانه", ico: "house" }, { href: "products", label: "موجودی", ico: "package" },
      { href: "sell", label: "فروش", ico: "plus", fab: true }, { href: "sales", label: "فروش‌ها", ico: "receipt" }],
  action: () => ({ href: "sell", label: "ثبت سریع", ico: "plus" }),
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
  quick: (role) => [{ href: "#/erp/sell", label: "ثبت فروش", ico: "shopping-bag", tone: "coral" },
    ...(role === "admin" ? [{ href: "#/erp/sell?mode=buy", label: "خرید کالا", ico: "truck", tone: "indigo" },
      { href: "#/erp/expenses/new", label: "ثبت هزینه", ico: "banknote", tone: "orchid" }] : [])],

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
    if (site.configured && !site.started) alerts.push({ tone: "warn", ico: "globe", text: "همگام‌سازی موجودی با سایت هنوز شروع نشده", sub: "یک انتخاب لازم است", href: "#/erp/site" });
    if (site.problems) alerts.push({ tone: "bad", ico: "cloud-off", text: `${fa(site.problems)} محصول با سایت هماهنگ نمی‌شود`, href: "#/erp/site" });
    if (site.nocount) alerts.push({ tone: "info", ico: "hash", text: `${fa(site.nocount)} محصول سایت شمارش نشده`, sub: "تعدادشان را یک بار وارد کنید", href: "#/erp/site" });
    if (d.month.unpaid) alerts.push({ tone: "info", ico: "clock", text: `${compact(d.month.unpaid)} تومان نسیه این ماه`, href: "#/erp/sales?unpaid=1" });
    return {
      headline: d.today.orders ? `امروز ${fa(d.today.orders)} فروش به مبلغ ${compact(d.today.revenue)} تومان` : "امروز هنوز فروشی ثبت نشده",
      stats: [
        { label: "فروش امروز", value: compact(d.today.revenue), unit: `${fa(d.today.orders)} سفارش`, href: "#/erp/sales" },
        { label: `فروش ${d.month_label}`, value: compact(d.month.revenue), unit: "تومان", href: "#/erp/reports" },
        { label: "سود خالص ماه", value: compact(d.month.net), unit: "تومان", tone: d.month.net < 0 ? "bad" : "", href: "#/erp/reports" },
        { label: "ارزش انبار", value: compact(d.stock_value), unit: "به قیمت خرید", href: "#/erp/products" },
      ],
      alerts,
    };
  },
};
