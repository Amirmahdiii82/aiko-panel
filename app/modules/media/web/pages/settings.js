// Studio settings (owners only): monthly spending cap. The OpenRouter key and the outbound proxy are shared
// connections in Settings → Connections (this page is also shown there as the "Studio" tab).
import { $, api, html, icon, raw, toast } from "/static/js/kit.js";
import { M, loadConfig, usd } from "../media.js";

export async function render(view, params, { setTitle }) {
  setTitle("تنظیمات استودیو", "سقف هزینه و وضعیت اتصال OpenRouter");

  const draw = async () => {
    const [s, cfg] = await Promise.all([api("/api/media/settings"), loadConfig()]);
    view.innerHTML = String(html`<div class="grid side">
      <section class="card">
        <div class="card-head"><h2>${icon("key-round")} اتصال OpenRouter</h2>
          <p>کلید OpenRouter و پروکسی خروجی برای همه برنامه یک جا تنظیم می‌شوند.</p></div>
        <div class="list">
          <div class="list-item"><div class="grow">کلید API</div>${s.key_set ? html`<span class="badge ok">${icon("check")}ذخیره شده <span class="ltr">${s.key_hint}</span></span>` : html`<span class="badge warn">تنظیم نشده</span>`}</div>
          <div class="list-item"><div class="grow">پروکسی خروجی</div>${s.proxy_url ? html`<span class="badge ok">${icon("check")}فعال</span>` : html`<span class="badge warn">ندارد — از ایران OpenRouter در دسترس نیست</span>`}</div>
        </div>
        <div class="row mt12"><a class="btn soft" href="#/settings/connections">${icon("plug", "sm")} تنظیم کلید و پروکسی</a>
          <button class="btn ghost" type="button" id="test">${icon("zap", "sm")} آزمایش اتصال</button></div>
        <div class="divider"></div>
        <form class="stack s12" id="f">
          <div class="field"><label>سقف هزینه ماهانه (دلار، ۰ = بدون سقف)</label><input class="input ltr" name="monthly_limit_usd" inputmode="decimal" value="${s.monthly_limit_usd || 0}"></div>
          <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره</button></div>
        </form>
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("dollar-sign")} هزینه</h2></div>
        <div class="money-big num ltr" style="text-align:right">${usd(cfg.month_spend) || "$0"}</div>
        <p class="small muted">هزینه گزارش‌شده OpenRouter برای ساخته‌های این ماه${cfg.monthly_limit_usd ? ` · سقف: ${usd(cfg.monthly_limit_usd)}` : ""}</p>
        <div class="divider"></div>
        <ul class="small" style="line-height:2.1;padding-inline-start:20px">
          <li>قبل از هر ساخت، قیمت اعلام‌شده هر مدل نشان داده و تأیید گرفته می‌شود.</li>
          <li>اگر سقف ماهانه پر شود، ساخت جدید تا ماه بعد (یا تغییر سقف) متوقف می‌شود.</li>
          <li>چه کسی بتواند بسازد را در «تیم و دسترسی‌ها» تعیین کنید (نقش «سازنده»).</li>
        </ul>
      </section>
    </div>`);
    $("#f", view).onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target;
      const body = { monthly_limit_usd: f.monthly_limit_usd.value.replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)) || 0 };
      await api("/api/media/settings", { method: "PUT", body });
      toast("ذخیره شد");
      M.loaded.clear();
      draw();
    };
    $("#test", view).onclick = async (e) => {
      e.target.disabled = true;
      try { const r = await api("/api/media/settings/test", { method: "POST" }); toast(`اتصال برقرار است — ${r.video_models} مدل ویدیو`); }
      finally { e.target.disabled = false; }
    };
  };
  await draw();
}
export { raw };
