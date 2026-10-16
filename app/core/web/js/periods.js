// Date range presets in Jalali months, shared by the list pages.
import { html, state } from "./core.js";
import { addDays, isoToJ, jToIso, monthLength } from "./jalali.js";

export const PERIODS = [
  { key: "today", label: "امروز" },
  { key: "7d", label: "۷ روز اخیر" },
  { key: "month", label: "این ماه" },
  { key: "last_month", label: "ماه قبل" },
  { key: "3m", label: "سه ماه اخیر" },
  { key: "year", label: "امسال" },
  { key: "all", label: "همه" },
];

export function periodRange(key) {
  const today = state.me.today;
  const [jy, jm] = isoToJ(today);
  switch (key) {
    case "today": return { start: today, end: today };
    case "7d": return { start: addDays(today, -6), end: today };
    case "month": return { start: jToIso(jy, jm, 1), end: jToIso(jy, jm, monthLength(jy, jm)) };
    case "last_month": {
      const [y, m] = jm > 1 ? [jy, jm - 1] : [jy - 1, 12];
      return { start: jToIso(y, m, 1), end: jToIso(y, m, monthLength(y, m)) };
    }
    case "3m": {
      let y = jy, m = jm - 2;
      if (m < 1) { m += 12; y -= 1; }
      return { start: jToIso(y, m, 1), end: jToIso(jy, jm, monthLength(jy, jm)) };
    }
    case "year": return { start: jToIso(jy, 1, 1), end: jToIso(jy, 12, monthLength(jy, 12)) };
    default: return { start: "", end: "" };
  }
}

export function periodChips(selected) {
  return html`<div class="chips scroll" data-periods>${PERIODS.map((p) =>
    html`<button class="chip ${p.key === selected ? "on" : ""}" data-period="${p.key}">${p.label}</button>`)}</div>`;
}
