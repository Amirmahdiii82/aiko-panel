// Competitor-price settings (shown in Settings → قیمت رقبا): when prices are read automatically. Which competitors are
// read and counted stays on the «رقبا» page, next to how each one did in the last run.
import { api, delegate, fa, html, icon, toast } from "/static/js/kit.js";
import { canEdit, faDate, refreshMeta } from "../pricing.js";

export async function render(view, params, { setTitle }) {
  setTitle("تنظیمات قیمت رقبا");
  let meta = await refreshMeta();
  let times = [...meta.schedule];
  const edit = canEdit();
  const draw = () => {
    view.innerHTML = String(html`<div class="grid side">
      <section class="card">
        <div class="card-head"><h2>${icon("clock")} بروزرسانی خودکار</h2>
          <p>هر روز در این ساعت‌ها (به وقت تهران) قیمت همه رقبا خوانده می‌شود. هر بار حدود ۵ تا ۱۰ دقیقه طول می‌کشد.</p></div>
        <div class="chips" id="times">${times.length ? times.map((t) => html`<span class="chip on">${fa(t)}
            ${edit ? html`<button type="button" class="btn icon xs ghost" style="color:inherit" data-del="${t}" aria-label="حذف ${t}">${icon("x", "sm")}</button>` : ""}</span>`)
          : html`<span class="small muted">خاموش — قیمت‌ها فقط با دکمه «بروزرسانی» تازه می‌شوند.</span>`}</div>
        ${edit ? html`<form class="row mt16" id="add"><input class="input sm ltr" name="t" placeholder="09:00" style="width:110px" inputmode="numeric" maxlength="5">
          <button class="btn sm soft" type="submit">${icon("plus", "sm")} افزودن ساعت</button>
          <span class="spacer"></span><button class="btn sm primary" type="button" id="save">${icon("check", "sm")} ذخیره</button></form>` : ""}
        <p class="small muted mt12">${meta.next_run ? `اجرای بعدی: ${faDate(meta.next_run)}` : "اجرای خودکاری برنامه‌ریزی نشده."}</p>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("store")} رقبا</h2></div>
        <p class="small" style="line-height:2">اینکه قیمت کدام سایت‌ها خوانده شود و کدام‌ها در شاخص و پیشنهادها حساب شوند، و نتیجه آخرین اجرای هر سایت، در صفحه «رقبا» است.</p>
        <a class="btn sm soft mt12" href="#/pricing/sites">${icon("store", "sm")} صفحه رقبا</a>
      </section>
    </div>`);
  };
  draw();
  delegate(view, "click", "[data-del]", (e, b) => { times = times.filter((t) => t !== b.dataset.del); draw(); });
  delegate(view, "submit", "#add", (e, form) => {
    e.preventDefault();
    const t = form.t.value.trim();
    if (t && !times.includes(t)) times = [...times, t];
    draw();
  });
  delegate(view, "click", "#save", async () => {
    const r = await api("/api/pricing/schedule", { method: "PUT", body: { times } });     // a wrong time comes back as an error
    times = r.schedule;
    meta = await refreshMeta();
    toast(times.length ? "زمان‌بندی ذخیره شد" : "بروزرسانی خودکار خاموش شد");
    draw();
  });
}
