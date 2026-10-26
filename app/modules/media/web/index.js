// Media studio entry: what the shell needs to show this module (nav, pages, what the home page shows).
import { fa, isOwner } from "/static/js/kit.js";
import { usd } from "./media.js";

export default {
  id: "media",
  css: ["/m/media/media.css"],
  // settings (spending cap) live in Settings → استودیو محتوا
  nav: () => [
    { href: "", label: "ساخت", ico: "wand-sparkles" },
    { href: "library", label: "کتابخانه", ico: "library" },
  ],
  action: (role) => (role === "creator" ? { href: "", label: "ساخت جدید", ico: "sparkles" } : null),
  pages: {
    "": () => import("./pages/studio.js"),
    library: () => import("./pages/library.js"),
  },
  settings: () => import("./pages/settings.js"),
  quick: (role) => (role === "creator" ? [{ href: "#/media", label: "ساخت محتوا", ico: "wand-sparkles" }] : []),

  /** The unified home page: what needs attention (the studio has no business numbers to show there). */
  glance(d) {
    if (!d.configured) {
      return { alerts: isOwner() ? [{ tone: "info", ico: "key-round", text: "استودیو محتوا راه‌اندازی نشده", sub: "کلید OpenRouter", href: "#/settings/connections" }] : [] };
    }
    const alerts = [];
    if (d.active) alerts.push({ tone: "info", ico: "loader-circle", text: `${fa(d.active)} تصویر/ویدیو در حال ساخت`, href: "#/media/library" });
    return { alerts, stats: [{ label: "هزینه استودیو این ماه", value: usd(d.month_spend) || "$0", unit: "OpenRouter", href: "#/media/library" }] };
  },
};
