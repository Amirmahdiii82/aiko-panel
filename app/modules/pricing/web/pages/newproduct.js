// Pricing a product you do not sell yet: search every competitor, then suggest a selling price from
// the market and your purchase cost / target margin.
import { $, api, confirmBox, delegate, emptyState, html, icon, parseNum, raw, toast } from "/static/js/kit.js";
import { P, ago, bindTips, canEdit, dotPlot, isWarnReason, n, pEmpty, pc, safeUrl, scoreBar, siteName } from "../pricing.js";

export async function render(view, params, { setTitle }) {
  let timer = null;
  let strategy = null;
  const stop = () => clearTimeout(timer);

  const list = async () => {
    setTitle("قیمت‌گذاری جدید", "محصولی که هنوز نمی‌فروشید را بنویسید؛ در همه رقبا جستجو می‌کنیم و قیمت فروش پیشنهاد می‌دهیم");
    const data = await api("/api/pricing/newproducts");
    view.innerHTML = String(html`<div class="stack pricing">
      ${canEdit() ? html`<form class="card" id="npForm">
        <div class="form-grid" style="grid-template-columns:2fr 1fr 1fr 110px auto;align-items:end" id="npGrid">
          <div class="field"><label>نام محصول *</label><input class="input" name="name" required placeholder="مثلاً: رژگونه استیکی شیگلم Buttery Bliss Blush Stick"></div>
          <div class="field"><label>برند</label><input class="input" name="brand" placeholder="مثلاً: SHEGLAM"></div>
          <div class="field"><label>قیمت خرید شما (تومان)</label><input class="input money" name="cost" inputmode="numeric" placeholder="اختیاری"></div>
          <div class="field"><label>حداقل سود ٪</label><input class="input" name="margin" inputmode="numeric" value="۲۵"></div>
          <button class="btn primary" type="submit" id="npSubmit">${icon("search", "sm")} بررسی بازار</button>
        </div>
        <p class="small muted mt12">نکته: نام انگلیسی مدل را هم بنویسید (مثل «Buttery Bliss») تا دقیق‌تر پیدا شود. جستجو در همه رقبا حدود نیم تا دو دقیقه طول می‌کشد.</p>
      </form>` : ""}
      <section class="card"><div class="card-head"><h2>بررسی‌های ذخیره‌شده</h2><p>با هر بروزرسانی زمان‌بندی‌شده، قیمت بازار این محصولات هم دوباره خوانده می‌شود</p></div>
        <div class="table-wrap">${data.items.length ? html`<table class="t"><thead><tr><th>محصول</th><th class="n">سایت‌ها</th><th class="n">ارزان‌ترین</th><th class="n">میانه بازار</th><th class="n">قیمت پیشنهادی</th><th>آخرین بررسی</th></tr></thead><tbody>
          ${data.items.map((r) => {
            const sm = r.summary, rec = sm.strategies.find((x) => x.key === sm.recommended);
            return html`<tr class="clickable" data-np="${r.id}"><td><b>${r.name}</b>${r.brand ? html`<div class="small muted">${r.brand}</div>` : ""}</td>
              <td class="n">${r.status === "running" ? html`<span class="badge info"><span class="spin"></span> در حال جستجو</span>` : n(sm.n_sites)}</td>
              <td class="n">${n(sm.min)}${sm.cheapest_site ? html`<div class="small muted">${siteName(sm.cheapest_site)}</div>` : ""}</td>
              <td class="n">${n(sm.median)}</td>
              <td class="n">${rec ? html`<b>${n(rec.price)}</b>${rec.margin != null ? html`<div class="small muted">سود ${pc(rec.margin, false)}</div>` : ""}` : sm.n_sites && r.cost ? html`<span class="badge bad">سود هدف ممکن نیست</span>` : "—"}</td>
              <td class="small muted nowrap">${ago(r.updated_at)}</td></tr>`;
          })}</tbody></table>` : emptyState("tag", "هنوز محصولی بررسی نشده", canEdit() ? "نام محصول را در فرم بالا بنویسید و «بررسی بازار» را بزنید." : "")}</div></section>
    </div>`);
    $("#npForm", view)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      $("#npSubmit", view).disabled = true;
      try {
        const r = await api("/api/pricing/newproducts", { method: "POST", body: {
          name: f.name.value, brand: f.brand.value, cost: parseNum(f.cost.value) || null, target_margin: parseNum(f.margin.value) || 25 } });
        location.hash = `#/pricing/new/${r.id}`;
      } catch (err) { $("#npSubmit", view).disabled = false; }
    });
    if (data.items.some((r) => r.status === "running")) timer = setTimeout(() => !params[0] && list(), 3000);
  };

  const detail = async (id) => {
    let d;
    try { d = await api(`/api/pricing/newproducts/${id}`); } catch (e) { view.innerHTML = String(emptyState("search", e.message)); return; }
    P.siteNames = { ...P.siteNames, ...d.site_names };
    setTitle(d.name, `${d.brand ? `${d.brand} · ` : ""}${d.status === "running" ? "در حال جستجو در رقبا…" : `آخرین بررسی ${ago(d.updated_at)}`}`);
    const sm = d.summary, running = d.status === "running";
    const excluded = new Set(d.excluded_sites);
    const isIn = (l) => { const k = `${l.site}:${l.external_id}`; return k in d.choices ? d.choices[k] && !!l.price : l.score >= d.auto && l.in_stock && !!l.price && !excluded.has(l.site); };
    const chosen = sm.strategies.find((x) => x.key === strategy) || sm.strategies.find((x) => x.key === sm.recommended) || sm.strategies[1] || sm.strategies[0];
    const bySite = {};
    d.results.forEach((l) => (bySite[l.site] ||= []).push(l));
    const siteBadge = (st) => ({
      running: html`<span class="badge info">در حال جستجو…</span>`,
      ok: st.found ? html`<span class="badge ok">${n(st.found)} آگهی</span>` : html`<span class="badge">پیدا نشد</span>`,
      blocked: html`<span class="badge bad">⛔ مسدود</span>`, failed: html`<span class="badge bad">✕ خطا</span>`,
    }[st.status] || "");
    let advice = "";
    if (!running && !sm.n_sites)
      advice = html`<div class="callout">${icon("search")}<div>آگهی مطمئنی پیدا نشد. اگر در فهرست پایین آگهی درستی هست تیکش را بزنید، یا «عبارت جستجو» را دقیق‌تر کنید (مثلاً نام انگلیسی مدل) و دوباره بررسی کنید.</div></div>`;
    else if (d.cost && sm.n_sites && !sm.recommended)
      advice = html`<div class="callout bad">${icon("triangle-alert")}<div>با قیمت خرید <b>${n(d.cost)}</b> و سود هدف ${pc(d.target_margin, false)}، باید حداقل <b>${n(sm.floor)}</b> بفروشید؛
        ولی میانه بازار <b>${n(sm.median)}</b> است. یا قیمت خرید بهتری بگیرید، یا با سود کمتر وارد شوید، یا روی ارزش افزوده (اصالت، ارسال سریع، هدیه) تکیه کنید.</div></div>`;
    else if (sm.recommended) {
      const r = sm.strategies.find((x) => x.key === sm.recommended);
      advice = html`<div class="callout ok">${icon("lightbulb")}<div>پیشنهاد: <b>${n(r.price)} تومان</b> (${r.label}).
        ${r.rank === 1 ? "ارزان‌ترین فروشنده می‌شوید" : `رتبه ${n(r.rank)} از ${n(r.of)} در بازار`}${r.margin != null ? ` با سود ${pc(r.margin, false)} (${n(r.profit)} تومان در هر فروش)` : "؛ برای دیدن سود، قیمت خرید را وارد کنید"}.</div></div>`;
    }
    const edit = canEdit();
    view.innerHTML = String(html`<div class="stack pricing" data-np-detail="${id}">
      <div class="row"><a class="btn sm ghost" href="#/pricing/new">${icon("arrow-right", "sm")} همه محصولات جدید</a><span class="spacer"></span>
        ${edit ? html`<button class="btn sm soft" id="npRefresh" ${running ? raw("disabled") : ""}>${icon("refresh-cw", "sm")} بررسی دوباره</button>
        <button class="btn sm danger" id="npDelete">${icon("trash-2", "sm")} حذف</button>` : ""}</div>
      ${edit ? html`<section class="card tight"><div class="form-grid" style="grid-template-columns:1fr 110px 2fr auto;align-items:end" id="npEdit">
        <div class="field"><label>قیمت خرید (تومان)</label><input class="input money" id="npCost" inputmode="numeric" value="${d.cost ?? ""}" placeholder="برای محاسبه سود"></div>
        <div class="field"><label>حداقل سود ٪</label><input class="input" id="npMargin" inputmode="numeric" value="${d.target_margin ?? 25}"></div>
        <div class="field"><label>عبارت جستجو (اختیاری)</label><input class="input" id="npQuery" value="${d.search_query || ""}" placeholder="خالی = خودکار از نام محصول"></div>
        <button class="btn soft" id="npSave">ذخیره</button></div>
        <div class="offer-meta mt12">${Object.entries(d.site_status || {}).map(([k, st]) => html`<span title="${st.error || ""}">${siteName(k)}: ${siteBadge(st)}</span>`)}</div></section>` : ""}
      ${advice}
      ${sm.strategies.length ? html`<div class="grid g3">${sm.strategies.map((x) => html`<button class="kpi ${x.key === sm.recommended ? "hero" : ""} ${x.key === chosen?.key ? "on" : ""}" data-strategy="${x.key}">
        <span class="k-label">${x.key === sm.recommended ? icon("star", "sm") : ""}${x.label}</span>
        <span class="k-value num">${n(x.price)}</span>
        <span class="k-foot">${x.rank === 1 ? "ارزان‌ترین بازار" : `رتبه ${n(x.rank)} از ${n(x.of)}`} · ${x.hint}</span>
        ${x.margin != null ? html`<span class="badge ${x.ok ? "ok" : "bad"}" style="align-self:flex-start;margin-top:8px">${x.ok ? "✓" : "✕"} سود ${pc(x.margin, false)} · ${n(x.profit)} تومان</span>` : ""}
      </button>`)}</div>` : ""}
      ${sm.n_sites ? html`<div class="kv">
        <div><div class="k">سایت‌هایی که دارند</div><div class="v">${n(sm.n_sites)}</div></div>
        <div><div class="k">ارزان‌ترین</div><div class="v num">${n(sm.min)}</div><div class="small muted">${siteName(sm.cheapest_site)}</div></div>
        <div><div class="k">میانه بازار</div><div class="v num">${n(sm.median)}</div></div>
        <div><div class="k">گران‌ترین</div><div class="v num">${n(sm.max)}</div></div></div>` : ""}
      ${d.results.length ? html`<section class="card"><div class="card-head"><h2>همه آگهی‌ها روی یک خط</h2><p>نقطه پر = در محاسبه، توخالی = حساب نشده؛ خط رنگی = قیمت انتخاب‌شده${sm.floor ? "، خط قرمز = کف قیمت برای سود هدف" : ""}</p></div>
        ${dotPlot(d.results.map((l) => ({ ...l, status: isIn(l) ? "auto" : "pending", fresh: true })), chosen?.price, { label: "پیشنهاد", floor: sm.floor })}</section>` : ""}
      <div><div class="card-head"><h2>آگهی‌های پیدا شده</h2><p>تیک = در محاسبه قیمت پیشنهادی. آگهی‌های مطمئن خودکار تیک خورده‌اند؛ بقیه را خودتان بررسی کنید.</p></div>
        ${Object.keys(bySite).length ? Object.entries(bySite).map(([site, items]) => html`<div class="site-group">
          <div class="site-head"><b>${siteName(site)}</b>${excluded.has(site) ? html`<span class="badge">خارج از محاسبات</span>` : ""}<span class="small muted">${n(items.length)} آگهی</span></div>
          ${items.map((l) => npRow(l, isIn(l), edit))}</div>`) : running ? pEmpty("در حال جستجو…") : emptyState("search", "در هیچ رقیبی آگهی مشابهی پیدا نشد")}
      </div>
    </div>`);
    bindTips(view);
    if (running) timer = setTimeout(() => { if (location.hash.startsWith(`#/pricing/new/${id}`)) detail(id); }, 2500);
  };

  // actions (delegated once; the view is redrawn often)
  delegate(view, "click", "[data-np]", (e, r) => { location.hash = `#/pricing/new/${r.dataset.np}`; });
  delegate(view, "click", "[data-strategy]", (e, b) => { strategy = b.dataset.strategy; detail(currentId()); });
  delegate(view, "change", "[data-np-key]", async (e, c) => {
    await api(`/api/pricing/newproducts/${currentId()}`, { method: "PATCH", body: { choices: { [c.dataset.npKey]: c.checked } } });
    detail(currentId());
  });
  delegate(view, "click", "#npSave", async () => {
    const id = currentId();
    const q = $("#npQuery", view).value.trim();
    const before = await api(`/api/pricing/newproducts/${id}`);
    await api(`/api/pricing/newproducts/${id}`, { method: "PATCH", body: { cost: parseNum($("#npCost", view).value) || null,
      target_margin: parseNum($("#npMargin", view).value) || 25, search_query: q } });
    if (q !== (before.search_query || "")) { await api(`/api/pricing/newproducts/${id}/refresh`, { method: "POST" }); toast("با عبارت جدید دوباره جستجو می‌شود"); }
    detail(id);
  });
  delegate(view, "click", "#npRefresh", async () => { await api(`/api/pricing/newproducts/${currentId()}/refresh`, { method: "POST" }); detail(currentId()); });
  delegate(view, "click", "#npDelete", async () => {
    if (!(await confirmBox("این بررسی حذف شود؟", { okText: "حذف", danger: true }))) return;
    await api(`/api/pricing/newproducts/${currentId()}`, { method: "DELETE" });
    location.hash = "#/pricing/new";
  });
  const currentId = () => Number(view.querySelector("[data-np-detail]")?.dataset.npDetail);

  const show = async (p) => { stop(); strategy = null; if (p[0]) await detail(Number(p[0])); else await list(); };
  await show(params);
  return { cleanup: stop, onParams: (p) => show(p) };
}

function npRow(l, on, edit) {
  const disc = l.regular_price && l.price && l.regular_price > l.price ? Math.round((1 - l.price / l.regular_price) * 100) : 0;
  const sellers = l.extra?.sellers;
  return html`<div class="offer np">
    <input type="checkbox" class="cbx" data-np-key="${`${l.site}:${l.external_id}`}" ${on ? raw("checked") : ""} ${edit ? "" : raw("disabled")} aria-label="در محاسبه">
    <div style="min-width:0">
      <div class="offer-title"><a href="${safeUrl(l.url)}" target="_blank" rel="noopener">${l.title} ↗</a></div>
      <div class="offer-meta">${l.seller ? html`<span>فروشنده: ${l.seller}</span>` : ""}
        ${l.extra?.shops > 1 ? html`<span>${n(l.extra.shops)} فروشگاه در ترب</span>` : ""}
        ${scoreBar(l)}
        ${(l.reasons || []).filter(isWarnReason).map((r) => html`<span class="badge warn">${r}</span>`)}
        ${!l.in_stock ? html`<span class="badge">ناموجود</span>` : ""}</div>
    </div>
    <div class="offer-price"><b class="num">${n(l.price)}</b>${disc ? html` <span class="badge bad">${n(disc)}٪ تخفیف</span>` : ""}</div>
  </div>
  ${sellers && sellers.length > 1 ? html`<details class="sellers"><summary>${n(sellers.length)} فروشنده / تنوع</summary>
    <table>${sellers.map((x) => html`<tr><td>${x.seller || ""}</td><td>${x.variant || ""}</td><td class="n">${n(x.price)}</td></tr>`)}</table></details>` : ""}`;
}
