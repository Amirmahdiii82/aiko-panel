// Overview: price index vs. the market, where products stand, risks, opportunities, competitor changes.
import { $, $$, api, delegate, emptyState, html, icon, on, raw, storage } from "/static/js/kit.js";
import {
  P, POS, ago, bindTips, canEdit, chartBase, gapBadge, hexA, img, indexBadge, lineOptions, n, nf1, openProduct, pEmpty, pc,
  progressPct, progressText, refreshMeta, setReviewCount, shortDate, short, siteName, startCrawl,
} from "../pricing.js";

export function goProducts(f) {
  P.filters = { q: "", position: "", brand: "", site: "", sort: "gap", opportunity: "", ...f };
  storage("pricing-filters", P.filters);
  location.hash = "#/pricing/products";
}

export async function render(view, params, { setTitle }) {
  setTitle("قیمت رقبا", "جایگاه قیمت محصولات سایت در برابر رقبا");
  const charts = [];
  let s;
  const draw = async () => {
    charts.forEach((c) => c.destroy());
    charts.length = 0;
    [s] = await Promise.all([api("/api/pricing/summary"), refreshMeta()]);
    setReviewCount(s.pending_reviews);
    const m = P.meta;
    const enabled = m.sites.filter((x) => x.enabled).length;
    const statusCard = html`<section class="card tight" id="crawl-card">${crawlStatus(m, s)}</section>`;

    if (!s.last_crawl && !s.products) {
      view.innerHTML = String(html`<div class="stack pricing">${statusCard}
        <section class="card">${emptyState("search", "هنوز قیمتی خوانده نشده",
          `با «بروزرسانی قیمت‌ها» محصولات ${m.own.url} و قیمت ${n(enabled)} رقیب خوانده می‌شود. اولین اجرا بسته به تعداد محصولات ممکن است طول بکشد.`,
          canEdit() ? html`<button class="btn brand" data-crawl>${icon("refresh-cw", "sm")} شروع اولین بروزرسانی</button>` : "")}</section></div>`);
      return;
    }
    const idx = s.median_index;
    const diff = idx == null ? null : Math.round((idx - 100) * 10) / 10;
    const heroText = idx == null ? "هنوز محصولی با رقبا مقایسه نشده."
      : diff > 0.5 ? raw(`قیمت‌های شما به‌طور میانه <b>${pc(diff, false)} گران‌تر</b> از میانه بازار است.`)
        : diff < -0.5 ? raw(`قیمت‌های شما به‌طور میانه <b>${pc(-diff, false)} ارزان‌تر</b> از میانه بازار است.`)
          : raw("قیمت‌های شما تقریباً <b>هم‌سطح میانه بازار</b> است.");
    const dist = s.distribution.filter((d) => d.count);
    const totalDist = dist.reduce((a, d) => a + d.count, 0) || 1;
    const count = (k) => s.distribution.find((d) => d.key === k)?.count || 0;

    view.innerHTML = String(html`<div class="stack pricing">
      ${statusCard}
      <section class="p-hero">
        <div class="p-hero-main">
          <div class="p-hero-label">شاخص قیمت شما <span class="muted small">(۱۰۰ = میانه بازار)</span></div>
          <div class="p-hero-value">${idx == null ? "—" : nf1.format(idx)}</div>
          <div class="p-hero-text">${heroText}</div>
          ${s.index_history.length > 1 ? html`<div class="p-hero-spark"><canvas id="sparkIdx"></canvas></div>` : ""}
        </div>
        <div class="grid g2">
          ${tile("compared", "محصولات مقایسه‌شده", n(s.compared), `${n(s.coverage_pct)}٪ از محصولات قیمت‌دار رقیب دارند`, "indigo", "chart-column")}
          ${tile("cheapest", "ارزان‌ترین بازار هستید", `${n(s.cheapest_share)}٪`, `${n(count("cheapest"))} محصول`, "mint", "circle-check")}
          ${tile("far_above", "بیش از ۱۰٪ گران‌ترید", n(count("far_above")), "محصول — احتمال از دست دادن فروش", "coral", "triangle-alert")}
          ${tile("raise", "فرصت افزایش قیمت", n(s.raise_count), s.raise_total ? `تا ${short(s.raise_total)} تومان سود بیشتر در هر دور فروش` : "محصولی با فاصله زیاد از رقیب نیست", "orchid", "piggy-bank")}
        </div>
      </section>
      ${s.pending_reviews ? html`<a class="callout" href="#/pricing/review" style="text-decoration:none;align-items:center">${icon("eye")}
        <div style="flex:1"><b>${n(s.pending_reviews)} تطبیق منتظر تأیید شماست.</b>
        این آگهی‌ها شبیه محصولات شما هستند ولی مطمئن نبودیم؛ تا تأیید نکنید در محاسبات شمرده نمی‌شوند.</div>
        <span class="btn sm soft">بررسی ${icon("chevron-left", "sm")}</span></a>` : ""}
      <section class="card">
        <div class="card-head"><h2>جایگاه قیمت محصولات</h2><p>نسبت به ارزان‌ترین رقیب موجود؛ روی هر بخش بزنید تا محصولاتش را ببینید</p></div>
        <div class="posbar" role="img" aria-label="توزیع جایگاه قیمت">
          ${dist.map((d) => html`<button style="flex:${d.count};background:${POS[d.key].color}" data-pos="${d.key}"
            data-tip="${`${POS[d.key].label}: ${n(d.count)} محصول (${n(Math.round((d.count / totalDist) * 100))}٪)`}"></button>`)}
        </div>
        <div class="legend">${s.distribution.map((d) => html`<button data-pos="${d.key}"><span class="dot" style="color:${POS[d.key].color}"></span>${POS[d.key].mark} ${POS[d.key].label} <b class="num">${n(d.count)}</b></button>`)}</div>
      </section>
      <section class="grid g2">
        <div class="card">
          <div class="card-head"><h2>${icon("trending-down")} در خطر: خیلی گران‌تر از رقبا</h2><span class="spacer"></span>
            <button class="btn xs ghost" data-filter='{"position":"far_above","sort":"gap"}'>همه</button><p>بیشترین فاصله با ارزان‌ترین رقیب موجود</p></div>
          <div class="list">${s.risk.length ? s.risk.map(riskRow) : pEmpty("عالی! محصولی بیش از ۱۰٪ گران‌تر از ارزان‌ترین رقیب نیست.")}</div>
        </div>
        <div class="card">
          <div class="card-head"><h2>${icon("piggy-bank")} فرصت: جا برای افزایش قیمت</h2><span class="spacer"></span>
            <button class="btn xs ghost" data-filter='{"opportunity":"raise","sort":"impact"}'>همه</button><p>ارزان‌ترین هستید و نزدیک‌ترین رقیب بیش از ۵٪ گران‌تر است</p></div>
          <div class="list">${s.raise.length ? s.raise.map(raiseRow) : pEmpty("فعلاً محصولی با فاصله زیاد از رقیب بعدی پیدا نشد.")}</div>
        </div>
      </section>
      <section class="grid side">
        <div class="card">
          <div class="card-head"><h2>شاخص قیمت در طول زمان</h2><p>میانه نسبت قیمت شما به میانه بازار در هر بروزرسانی؛ زیر ۱۰۰ یعنی ارزان‌تر</p></div>
          <div class="chart-box"><canvas id="idxChart"></canvas></div>
          ${s.index_history.length < 2 ? html`<p class="small muted mt8">بعد از چند بروزرسانی روند اینجا نمایش داده می‌شود.</p>` : ""}
        </div>
        <div class="card">
          <div class="card-head"><h2>آخرین تغییرات رقبا</h2><p>تغییر قیمت و موجودی نسبت به بروزرسانی قبلی</p></div>
          <div class="list" style="max-height:330px;overflow:auto">${s.changes.length ? s.changes.map(changeRow) : pEmpty("هنوز تغییری ثبت نشده (از بروزرسانی دوم به بعد).")}</div>
        </div>
      </section>
      <section class="grid g2">
        <div class="card"><div class="card-head"><h2>رقیب به رقیب</h2><p>در محصولات مشترک، هر رقیب چند درصد مواقع از شما ارزان‌تر است</p></div>
          <div class="table-wrap">${h2hTable(s.head_to_head)}</div></div>
        <div class="card"><div class="card-head"><h2>برندها</h2><p>شاخص قیمت شما در هر برند (۱۰۰ = میانه بازار)</p></div>
          <div class="table-wrap">${brandTable(s.brands)}</div></div>
      </section>
    </div>`);
    bindTips(view);
    drawIndexCharts(s.index_history, charts);
  };
  await draw();

  delegate(view, "click", "[data-crawl]", () => startCrawl());
  delegate(view, "click", "[data-pos]", (e, b) => goProducts({ position: b.dataset.pos }));
  delegate(view, "click", "[data-filter]", (e, b) => goProducts(JSON.parse(b.dataset.filter)));
  delegate(view, "click", "[data-pid]", (e, r) => openProduct(+r.dataset.pid));
  delegate(view, "click", "[data-brand]", (e, r) => goProducts({ brand: r.dataset.brand }));
  delegate(view, "click", "[data-site]", (e, r) => goProducts({ site: r.dataset.site }));
  delegate(view, "click", "button.kpi[data-k]", (e, t) => {
    const k = t.dataset.k;
    if (k === "raise") goProducts({ opportunity: "raise", sort: "impact" });
    else if (k === "compared") goProducts({});
    else goProducts({ position: k });
  });
  const offProgress = on("pricing:progress", () => { const c = $("#crawl-card", view); if (c && s) c.innerHTML = String(crawlStatus(P.meta, s)); });
  const offState = on("pricing:state", (ev) => {
    if (ev?.state === "done" || ev?.state === "failed") draw();
    else { const c = $("#crawl-card", view); if (c && s) c.innerHTML = String(crawlStatus(P.meta, s)); }
  });
  return () => { offProgress(); offState(); charts.forEach((c) => c.destroy()); };
}

function crawlStatus(m, s) {
  const last = s.last_crawl;
  const next = m.next_run ? new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tehran" }).format(new Date(m.next_run)) : null;
  if (m.running) {
    return html`<div class="crawl-status"><span class="spin"></span><b>در حال خواندن قیمت‌ها…</b>
      <span class="small muted">${progressText(m.progress)}</span>
      <div class="progress"><i style="width:${progressPct(m.progress)}%"></i></div></div>`;
  }
  const failed = last?.status === "failed";
  return html`<div class="crawl-status">
    <span class="badge ${failed ? "bad" : "ok"}">${icon(failed ? "cloud-off" : "circle-check")}${failed ? "آخرین اجرا ناموفق بود" : "آخرین بروزرسانی"}</span>
    <span class="small">${ago(last?.finished_at)}</span>
    <span class="small muted">${next ? `بروزرسانی خودکار بعدی: ساعت ${next}` : "بروزرسانی خودکار خاموش است"}</span>
    <span class="spacer" style="flex:1"></span>
    <a class="btn sm ghost" href="/api/pricing/export.csv">${icon("download", "sm")} خروجی اکسل</a>
    ${canEdit() ? html`<button class="btn sm soft" data-crawl>${icon("refresh-cw", "sm")} بروزرسانی الان</button>` : ""}
  </div>`;
}

function tile(k, label, value, foot, color, ico) {
  return html`<button class="kpi ${color}" data-k="${k}"><span class="k-icon">${icon(ico)}</span>
    <span class="k-label">${label}</span><span class="k-value num">${value}</span><span class="k-foot">${foot}</span></button>`;
}
function riskRow(r) {
  return html`<div class="list-item clickable" data-pid="${r.id}">${img(r.image)}
    <div class="grow"><div class="title ellipsis">${r.name}</div>
      <div class="sub ellipsis">شما ${n(r.my_price)} · ارزان‌ترین: ${n(r.min)} در ${siteName(r.cheapest_site)}</div></div>
    ${gapBadge(r.gap_min_pct)}</div>`;
}
function raiseRow(r) {
  return html`<div class="list-item clickable" data-pid="${r.id}">${img(r.image)}
    <div class="grow"><div class="title ellipsis">${r.name}</div>
      <div class="sub ellipsis">شما ${n(r.my_price)} · رقیب بعدی ${n(r.min)} (${siteName(r.cheapest_site)}) · پیشنهاد: ${n(r.suggested_price)}</div></div>
    <span class="badge ok num">+${short(r.impact)}</span></div>`;
}
function changeRow(c) {
  const what = c.kind === "out_of_stock" ? html`<span class="badge">ناموجود شد</span>`
    : c.kind === "back_in_stock" ? html`<span class="badge info">موجود شد</span>`
      : html`<span class="badge ${c.pct < 0 ? "bad" : "ok"} num" title="${c.pct < 0 ? "رقیب ارزان کرد" : "رقیب گران کرد"}">${c.pct < 0 ? "▼" : "▲"} ${pc(c.pct)}</span>`;
  return html`<div class="list-item clickable" data-pid="${c.product_id}">
    <div class="grow"><div class="title ellipsis">${c.product_name}</div>
      <div class="sub ellipsis">${siteName(c.site)}${c.seller ? ` · ${c.seller}` : ""} · ${n(c.old_price)} ← ${n(c.new_price)} · ${ago(c.ts)}</div></div>
    ${what}</div>`;
}
function h2hTable(rows) {
  const r = rows.filter((x) => x.overlap);
  if (!r.length) return pEmpty("هنوز محصول مشترکی پیدا نشده.");
  return html`<table class="t"><thead><tr><th>رقیب</th><th class="n">مشترک</th><th>ارزان‌تر از شما</th><th class="n">اختلاف میانه</th></tr></thead><tbody>
    ${r.map((x) => html`<tr class="clickable" data-site="${x.site}">
      <td><b>${x.name}</b></td><td class="n">${n(x.overlap)}</td>
      <td><div class="row nowrap"><div class="meter" style="flex:1"><span style="width:${x.cheaper_pct || 0}%"></span></div><span class="num small">${n(x.cheaper_pct)}٪</span></div></td>
      <td class="n">${x.median_diff_pct == null ? "—" : html`<span class="${x.median_diff_pct < 0 ? "bad-ink" : "ok-ink"} bold">${pc(x.median_diff_pct)}</span>`}</td></tr>`)}
    </tbody></table><p class="small muted mt8">اختلاف میانه = قیمت رقیب نسبت به شما؛ منفی یعنی رقیب ارزان‌تر است.</p>`;
}
function brandTable(rows) {
  if (!rows.length) return pEmpty("هنوز داده‌ای نیست.");
  return html`<table class="t"><thead><tr><th>برند</th><th class="n">محصول</th><th class="n">شاخص</th><th class="n">خیلی گران‌تر</th><th class="n">ارزان‌ترین</th></tr></thead><tbody>
    ${rows.map((b) => html`<tr class="clickable" data-brand="${b.brand}"><td>${b.brand}</td><td class="n">${n(b.count)}</td>
      <td class="n">${indexBadge(b.median_index)}</td><td class="n">${b.far_above ? html`<span class="bad-ink bold">${n(b.far_above)}</span>` : "۰"}</td><td class="n">${n(b.cheapest)}</td></tr>`)}
    </tbody></table>`;
}
function drawIndexCharts(hist, charts) {
  if (!hist.length || !window.Chart) return;
  const labels = hist.map((h) => shortDate(h.ts));
  const spark = document.getElementById("sparkIdx");
  if (spark && hist.length > 1) {
    const c = chartBase(spark);
    charts.push(new Chart(spark, {
      type: "line",
      data: { labels, datasets: [{ data: hist.map((h) => h.index), borderColor: c.accent, borderWidth: 2, pointRadius: 0, tension: 0.3,
        fill: { target: { value: 100 }, above: hexA(c.accent, 0.08), below: hexA(c.accent, 0.08) } }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false } } },
    }));
  }
  const el = document.getElementById("idxChart");
  if (!el) return;
  const c = chartBase(el);
  charts.push(new Chart(el, {
    type: "line",
    data: { labels, datasets: [
      { label: "شاخص قیمت شما", data: hist.map((h) => h.index), borderColor: c.accent, backgroundColor: c.accent, borderWidth: 2, pointRadius: hist.length > 20 ? 0 : 4, pointBorderColor: c.surface, pointBorderWidth: 2, tension: 0.25 },
      { label: "میانه بازار (۱۰۰)", data: hist.map(() => 100), borderColor: c.market2, borderWidth: 1, pointRadius: 0 },
    ] },
    options: lineOptions(c, (v) => nf1.format(v), (ctx) => ctx.datasetIndex === 0 ? `شاخص: ${nf1.format(ctx.parsed.y)} · ارزان‌ترین در ${n(hist[ctx.dataIndex].cheapest_share)}٪ محصولات` : null),
  }));
}
export { $$ };
