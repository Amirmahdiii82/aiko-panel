// Chart.js wrappers that follow the design tokens (colours from CSS, Persian numbers, RTL tooltips). Monochrome:
// ink for what is being looked at (this period, the latest bar), greys for context.
import { compact, cssVar, num, on } from "./core.js";

const charts = new Set();
on("theme", () => setTimeout(() => charts.forEach((c) => c.__refresh && c.__refresh()), 50));

function base() {
  const ink = cssVar("--muted") || "#76767C";
  return {
    // numbers people read and compare: they appear in place instead of growing in on every visit
    responsive: true, maintainAspectRatio: false, animation: false,
    locale: "fa-IR",
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false, rtl: true, labels: { font: { family: "Vazirmatn" }, color: ink, usePointStyle: true, boxWidth: 8 } },
      tooltip: {
        rtl: true, textDirection: "rtl", backgroundColor: cssVar("--accent") || "#111", titleColor: cssVar("--on-accent"), bodyColor: cssVar("--on-accent"),
        borderWidth: 0, padding: 12, cornerRadius: 12, boxPadding: 6, usePointStyle: true,
        titleFont: { family: "Vazirmatn", weight: "700" }, bodyFont: { family: "Vazirmatn" },
        callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${num(ctx.parsed.y)} تومان` },
      },
    },
    scales: {
      x: { grid: { display: false }, border: { display: false }, ticks: { color: ink, font: { family: "Vazirmatn", size: 11 }, maxRotation: 0, autoSkipPadding: 12 } },
      y: { grid: { color: cssVar("--chart-grid") }, border: { display: false }, position: "right",
        ticks: { color: ink, font: { family: "Vazirmatn", size: 11 }, callback: (v) => compact(v), maxTicksLimit: 5 } },
    },
  };
}

function make(canvas, build) {
  if (!window.Chart) return null;
  const chart = new window.Chart(canvas, build());
  chart.__refresh = () => {
    const cfg = build();
    chart.options = cfg.options;
    chart.data.datasets.forEach((ds, i) => Object.assign(ds, cfg.data.datasets[i]));
    chart.update("none");
  };
  charts.add(chart);
  const obs = new MutationObserver(() => {
    if (!document.body.contains(canvas)) { chart.destroy(); charts.delete(chart); obs.disconnect(); }
  });
  obs.observe(document.body, { childList: true, subtree: true });
  return chart;
}

/** Bars, e.g. daily revenue: the latest bar in ink, the rest in grey. */
export function barChart(canvas, labels, values, label = "فروش") {
  return make(canvas, () => {
    const [ink, grey] = [cssVar("--chart-1"), cssVar("--chart-3")];
    const colors = values.map((_, i) => (i === values.length - 1 ? ink : grey));
    return {
      type: "bar",
      data: { labels, datasets: [{ label, data: values, backgroundColor: colors, hoverBackgroundColor: ink, borderRadius: 8, borderSkipped: false, maxBarThickness: 22 }] },
      options: base(),
    };
  });
}

/** This period as a solid ink line over a soft fill, the previous period as a dashed grey line under it. */
export function trendChart(canvas, labels, current, previous, { label = "این دوره", prevLabel = "دوره قبل" } = {}) {
  return make(canvas, () => {
    const ink = cssVar("--chart-1");
    const ctx = canvas.getContext("2d");
    const fill = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 260);
    fill.addColorStop(0, cssVar("--chart-grid"));
    fill.addColorStop(1, "transparent");
    const sets = [{ label, data: current, borderColor: ink, backgroundColor: fill, fill: true, tension: 0.35, borderWidth: 2.2,
      pointRadius: 0, pointHoverRadius: 5, pointBackgroundColor: ink, pointHoverBorderWidth: 3, pointHoverBorderColor: cssVar("--surface") }];
    if (previous) {
      sets.push({ label: prevLabel, data: previous, borderColor: cssVar("--chart-2"), borderDash: [5, 5], borderWidth: 1.6, tension: 0.35,
        pointRadius: 0, pointHoverRadius: 4, pointBackgroundColor: cssVar("--chart-2"), fill: false });
    }
    return { type: "line", data: { labels, datasets: sets }, options: base() };
  });
}

/** Monthly revenue bars + net profit line. */
export function comboChart(canvas, labels, revenue, net, expenses) {
  return make(canvas, () => {
    const o = base();
    o.plugins.legend.display = true;
    o.plugins.legend.position = "bottom";
    return {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "فروش", data: revenue, backgroundColor: cssVar("--chart-1"), borderRadius: 8, borderSkipped: false, maxBarThickness: 30, order: 2 },
          { label: "هزینه‌های جاری", data: expenses, backgroundColor: cssVar("--chart-3"), borderRadius: 8, borderSkipped: false, maxBarThickness: 30, order: 3 },
          { label: "سود خالص", data: net, type: "line", borderColor: cssVar("--chart-4"), backgroundColor: cssVar("--chart-4"), tension: 0.35, pointRadius: 3, pointHoverRadius: 5, borderWidth: 2.5, order: 1 },
        ],
      },
      options: o,
    };
  });
}
