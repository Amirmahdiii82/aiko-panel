// Chart.js wrappers that follow the clay theme (colors from CSS tokens, Persian numbers, RTL tooltips).
import { compact, cssVar, num, on } from "./core.js";

const charts = new Set();
on("theme", () => setTimeout(() => charts.forEach((c) => c.__refresh && c.__refresh()), 50));

function base() {
  const ink = cssVar("--muted") || "#6E687F";
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 500 },
    locale: "fa-IR",
    plugins: {
      legend: { display: false, rtl: true, labels: { font: { family: "Vazirmatn" }, color: ink, usePointStyle: true, boxWidth: 8 } },
      tooltip: {
        rtl: true, textDirection: "rtl", backgroundColor: cssVar("--clay") || "#fff", titleColor: cssVar("--ink"), bodyColor: cssVar("--ink-2"),
        borderColor: cssVar("--line-2"), borderWidth: 1, padding: 12, cornerRadius: 14, boxPadding: 6,
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

function gradient(canvas, color) {
  const ctx = canvas.getContext("2d");
  const g = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 240);
  g.addColorStop(0, color);
  g.addColorStop(1, color + "55");
  return g;
}

/** Bars, e.g. daily revenue. */
export function barChart(canvas, labels, values, label = "فروش") {
  return make(canvas, () => ({
    type: "bar",
    data: { labels, datasets: [{ label, data: values, backgroundColor: gradient(canvas, cssVar("--chart-1")), borderRadius: 10, borderSkipped: false, maxBarThickness: 26 }] },
    options: base(),
  }));
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
          { label: "فروش", data: revenue, backgroundColor: gradient(canvas, cssVar("--chart-1")), borderRadius: 10, borderSkipped: false, maxBarThickness: 34, order: 2 },
          { label: "هزینه‌های جاری", data: expenses, backgroundColor: gradient(canvas, cssVar("--chart-2")), borderRadius: 10, borderSkipped: false, maxBarThickness: 34, order: 3 },
          { label: "سود خالص", data: net, type: "line", borderColor: cssVar("--chart-4"), backgroundColor: cssVar("--chart-4"), tension: 0.35, pointRadius: 4, pointHoverRadius: 6, borderWidth: 3, order: 1 },
        ],
      },
      options: o,
    };
  });
}
