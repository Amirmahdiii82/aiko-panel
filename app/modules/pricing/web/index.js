// Pricing module entry: what the shell needs to show this module (nav, pages, what the home page shows).
import { fa } from "/static/js/kit.js";
import { P, ago, canEdit, nf1, refreshMeta, refreshReviewCount, startCrawl, syncAction, wireLive } from "./pricing.js";

export default {
  id: "pricing",
  css: ["/m/pricing/pricing.css"],
  nav: () => [
    { href: "", label: "نمای کلی", ico: "layout-dashboard" },
    { href: "products", label: "محصولات", ico: "package" },
    { href: "new", label: "قیمت‌گذاری محصول جدید", ico: "tag" },
    { href: "review", label: "تأیید تطبیق‌ها", ico: "check-check" },
    { href: "sites", label: "رقبا و اجراها", ico: "store" },
  ],
  mobile: () => [
    { href: "", label: "نمای کلی", ico: "layout-dashboard" },
    { href: "products", label: "محصولات", ico: "package" },
    { href: "new", label: "جدید", ico: "plus", fab: true },
    { href: "review", label: "تأیید", ico: "check-check" },
  ],
  action: (role) => (role === "editor" ? { label: "بروزرسانی قیمت‌ها", ico: "refresh-cw", onClick: () => startCrawl() } : null),
  pages: {
    "": () => import("./pages/overview.js"),
    products: () => import("./pages/products.js"),
    new: () => import("./pages/newproduct.js"),
    review: () => import("./pages/review.js"),
    sites: () => import("./pages/sites.js"),
  },
  enter: async () => {
    wireLive();
    await refreshMeta();
    refreshReviewCount();
    setTimeout(syncAction, 0);
  },
  quick: (role) => (role === "editor" ? [{ href: "#/pricing/new", label: "قیمت‌گذاری محصول", ico: "tag", tone: "indigo" }] : []),

  /** The unified home page: key numbers and what needs attention. */
  glance(d) {
    if (!d.products) return { alerts: [{ tone: "info", ico: "chart-line", text: "قیمت رقبا هنوز خوانده نشده", href: "#/pricing" }] };
    const alerts = [];
    if (d.running) alerts.push({ tone: "info", ico: "loader-circle", text: "بروزرسانی قیمت رقبا در حال انجام است", href: "#/pricing" });
    if (d.pending_reviews) alerts.push({ tone: "warn", ico: "check-check", text: `${fa(d.pending_reviews)} تطبیق قیمت منتظر تأیید`, href: "#/pricing/review" });
    if (d.far_above) alerts.push({ tone: "bad", ico: "trending-up", text: `${fa(d.far_above)} محصول خیلی گران‌تر از بازار`, sub: d.risk.map((r) => r.name).slice(0, 2).join("، "), href: "#/pricing/products" });
    if (d.raise_count) alerts.push({ tone: "ok", ico: "trending-down", text: `${fa(d.raise_count)} فرصت افزایش قیمت`, href: "#/pricing/products" });
    return {
      stats: [
        { label: "شاخص قیمت", value: d.median_index == null ? "—" : nf1.format(d.median_index), unit: "۱۰۰ = میانه بازار", href: "#/pricing" },
        { label: "خیلی گران‌تر", value: fa(d.far_above), unit: "محصول", href: "#/pricing/products" },
        { label: "فرصت افزایش", value: fa(d.raise_count), unit: "محصول", href: "#/pricing/products" },
        { label: "آخرین بروزرسانی", value: ago(d.last_crawl?.finished_at) || "—", unit: "", href: "#/pricing/sites" },
      ],
      alerts,
    };
  },
};
export { P, canEdit };
