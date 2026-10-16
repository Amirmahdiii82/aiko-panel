// Media studio entry: what the shell needs to show this module (nav, pages, home card).
import { fa, html, icon, isOwner } from "/static/js/kit.js";
import { usd } from "./media.js";

export default {
  id: "media",
  css: ["/m/media/media.css"],
  nav: () => [
    { href: "", label: "استودیو", ico: "wand-sparkles" },
    { href: "library", label: "کتابخانه", ico: "library" },
    ...(isOwner() ? [{ section: "مدیریت" }, { href: "settings", label: "تنظیمات استودیو", ico: "key-round" }] : []),
  ],
  mobile: () => [
    { href: "", label: "استودیو", ico: "wand-sparkles" },
    { href: "library", label: "کتابخانه", ico: "library" },
  ],
  action: (role) => (role === "creator" ? { href: "", label: "ساخت جدید", ico: "sparkles" } : null),
  allowed: (role, page) => page !== "settings" || isOwner(),
  pages: {
    "": () => import("./pages/studio.js"),
    library: () => import("./pages/library.js"),
    settings: () => import("./pages/settings.js"),
  },
  quick: (role) => (role === "creator" ? [{ href: "#/media", label: "ساخت تصویر یا ویدیو", sub: "تبلیغ با هوش مصنوعی", ico: "wand-sparkles", color: "#D297BE" }] : []),

  /** Card on the unified home page. */
  home(d) {
    if (!d.configured) {
      return html`<p class="small muted">${isOwner() ? html`کلید OpenRouter تنظیم نشده. <a href="#/media/settings">تنظیم</a>` : "استودیو هنوز راه‌اندازی نشده."}</p>`;
    }
    return html`<div class="grid g3">
        <div class="mini-stat"><span>هزینه این ماه</span><b class="num ltr" style="text-align:right">${usd(d.month_spend) || "$0"}</b><small>OpenRouter</small></div>
        <div class="mini-stat"><span>در حال ساخت</span><b class="num">${fa(d.active)}</b><small>کار</small></div>
        <div class="mini-stat"><span>ساخته‌های اخیر</span><b class="num">${fa(d.recent.length)}</b><small>در کتابخانه</small></div>
      </div>
      ${d.recent.length ? html`<div class="thumb-strip mt12">${d.recent.map((g) => html`<a href="#/media/library/${g.id}" title="${g.prompt}">
        ${g.thumb ? html`<img src="${g.thumb}" alt="" loading="lazy">` : icon(g.kind === "video" ? "video" : "image")}</a>`)}</div>` : ""}`;
  },
};
