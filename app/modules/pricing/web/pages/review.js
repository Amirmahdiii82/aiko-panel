// Review queue: listings that look like your product but were not certain enough to count automatically.
import { $, $$, api, delegate, emptyState, html, icon, toast } from "/static/js/kit.js";
import { canEdit, img, isWarnReason, n, openProduct, pc, safeUrl, scoreBar, setReviewCount, siteName } from "../pricing.js";

export async function render(view, params, { setTitle }) {
  setTitle("تأیید تطبیق‌ها", "هر تأیید/رد یک‌بار است و در بروزرسانی‌های بعد حفظ می‌شود");
  const draw = async () => {
    const data = await api("/api/pricing/review?limit=40");
    setReviewCount(data.total);
    view.innerHTML = String(html`<div class="stack pricing">
      <div class="row small muted"><span>${n(data.total)} مورد</span>${canEdit() ? html`<span>· کلید <span class="kbd">A</span> تأیید، <span class="kbd">R</span> رد برای کارت اول</span>` : ""}</div>
      <div class="stack" id="rvList">${data.items.length ? data.items.map(card) : html`<section class="card">${emptyState("check-check", "همه تطبیق‌ها بررسی شده‌اند 🎉")}</section>`}</div>
    </div>`);
  };
  const decide = async (oid, st) => {
    const el = $(`#rv-${oid}`, view);
    if (el) el.style.opacity = ".4";
    try {
      const r = await api(`/api/pricing/offers/${oid}/status`, { method: "POST", body: { status: st } });
      el?.remove();
      const left = $$("#rvList > .rv-card", view).length;
      const total = await api("/api/pricing/review?limit=1", { quiet: true }).then((x) => x.total).catch(() => 0);
      setReviewCount(total);
      if (!left) draw();
      return r;
    } catch (e) {
      if (el) el.style.opacity = "";
      toast(e.message, "error");
    }
  };
  await draw();
  delegate(view, "click", "[data-oid]", (e, b) => decide(b.dataset.oid, b.dataset.st));
  delegate(view, "click", "[data-pid]", (e, b) => openProduct(+b.dataset.pid, { onChange: draw }));
  const onKey = (e) => {
    if (!canEdit() || e.target.closest("input,textarea,select") || document.querySelector(".scrim")) return;
    const first = $("#rvList > .rv-card", view);
    if (!first) return;
    const id = first.id.slice(3);
    if (["a", "A", "ش"].includes(e.key)) decide(id, "confirmed");
    if (["r", "R", "ق"].includes(e.key)) decide(id, "rejected");
  };
  document.addEventListener("keydown", onKey);
  return () => document.removeEventListener("keydown", onKey);
}

function card(o) {
  const diff = o.my_price && o.price ? Math.round(((o.price - o.my_price) / o.my_price) * 1000) / 10 : null;
  return html`<section class="card rv-card" id="rv-${o.id}">
    <div class="review-card">
      <div class="rv-side mine">${img(o.product_image)}<div style="min-width:0"><div class="rv-label">محصول شما</div>
        <div class="rv-title">${o.product_name}</div><div class="rv-price num">${n(o.my_price)} تومان</div></div></div>
      <div class="rv-vs">در برابر</div>
      <div class="rv-side">${img(o.image)}<div style="min-width:0"><div class="rv-label">${siteName(o.site)}${o.seller ? ` · ${o.seller}` : ""}</div>
        <div class="rv-title"><a href="${safeUrl(o.url)}" target="_blank" rel="noopener">${o.title} ↗</a></div>
        <div class="rv-price num">${n(o.price)} تومان ${diff != null ? html`<span class="small ${diff < 0 ? "ok-ink" : "bad-ink"}">(${pc(diff)})</span>` : ""}</div></div></div>
    </div>
    <div class="rv-actions">
      <div class="offer-meta">${scoreBar(o)}
        ${(o.reasons || []).map((r) => html`<span class="badge ${isWarnReason(r) ? "warn" : ""}">${r}</span>`)}
        <button class="btn xs ghost" data-pid="${o.product_id}">همه رقبای این محصول</button></div>
      ${canEdit() ? html`<div class="row nowrap"><button class="btn sm ok-btn" data-oid="${o.id}" data-st="confirmed">${icon("check", "sm")} همین است</button>
        <button class="btn sm no-btn" data-oid="${o.id}" data-st="rejected">${icon("x", "sm")} محصول دیگری است</button></div>` : ""}
    </div></section>`;
}
