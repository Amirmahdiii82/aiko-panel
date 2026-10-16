// Pricing module entry: what the shell needs to show this module (nav, pages, home card).
import { fa, html, icon } from "/static/js/kit.js";
import { P, ago, canEdit, gapBadge, img, nf1, refreshMeta, refreshReviewCount, startCrawl, syncAction, wireLive } from "./pricing.js";

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
  quick: (role) => (role === "editor" ? [{ href: "#/pricing/new", label: "قیمت‌گذاری محصول جدید", sub: "بررسی بازار و سود", ico: "tag", color: "#ADA4DC" }] : []),

  /** Card on the unified home page. */
  home(d) {
    if (!d.products) return html`<p class="small muted">هنوز قیمتی خوانده نشده. از «قیمت رقبا» اولین بروزرسانی را بزنید.</p>`;
    return html`<div class="grid g4">
        <div class="mini-stat"><span>شاخص قیمت</span><b class="num">${d.median_index == null ? "—" : nf1.format(d.median_index)}</b><small>۱۰۰ = میانه بازار</small></div>
        <div class="mini-stat"><span>خیلی گران‌تر</span><b class="num ${d.far_above ? "bad-ink" : ""}">${fa(d.far_above)}</b><small>محصول</small></div>
        <div class="mini-stat"><span>فرصت افزایش</span><b class="num">${fa(d.raise_count)}</b><small>محصول</small></div>
        <div class="mini-stat"><span>منتظر تأیید</span><b class="num">${fa(d.pending_reviews)}</b><small>تطبیق</small></div>
      </div>
      ${d.risk.length ? html`<div class="list mt12">${d.risk.map((r) => html`<a class="list-item clickable" href="#/pricing/products" style="text-decoration:none">${img(r.image, "thumb sm")}
        <div class="grow"><div class="title ellipsis small">${r.name}</div></div>${gapBadge(r.gap)}</a>`)}</div>` : ""}
      <p class="small muted mt12">${d.running ? html`<span class="spin"></span> در حال بروزرسانی…` : html`${icon("history", "sm")} آخرین بروزرسانی: ${ago(d.last_crawl?.finished_at)}`}</p>`;
  },
};
export { P, canEdit };
