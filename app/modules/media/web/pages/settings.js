// Studio settings (owners only): OpenRouter key (never shown again), outbound proxy, monthly spending cap.
import { $, api, html, icon, isOwner, raw, toast } from "/static/js/kit.js";
import { M, loadConfig, usd } from "../media.js";

export async function render(view, params, { setTitle }) {
  setTitle("تنظیمات استودیو", "اتصال OpenRouter و سقف هزینه");
  if (!isOwner()) { location.hash = "#/media"; return; }
  const draw = async () => {
    const [s, cfg] = await Promise.all([api("/api/media/settings"), loadConfig()]);
    view.innerHTML = String(html`<div class="grid side">
      <section class="card">
        <div class="card-head"><h2>${icon("key-round")} اتصال OpenRouter</h2>
          <p>کلید فقط روی سرور ذخیره می‌شود و هیچ‌وقت به مرورگر یا پاسخ‌های برنامه نمی‌رسد.</p></div>
        <form class="stack s12" id="f">
          <div class="field"><label>کلید API ${s.key_set ? html`<span class="badge ok">${icon("check")}ذخیره شده <span class="ltr">${s.key_hint}</span></span>` : html`<span class="badge warn">تنظیم نشده</span>`}</label>
            <input class="input ltr" name="api_key" autocomplete="off" placeholder="${s.key_set ? "برای تغییر، کلید جدید را بچسبانید" : "sk-or-v1-…"}"></div>
          <div class="field"><label>پروکسی خروجی (اختیاری)</label><input class="input ltr" name="proxy_url" value="${s.proxy_url || ""}" placeholder="http://user:pass@host:port یا socks5://host:port">
            <div class="hint">سرور ایران مستقیم به OpenRouter نمی‌رسد؛ اگر لازم است، همه درخواست‌های استودیو از این پروکسی می‌روند.</div></div>
          <div class="field"><label>سقف هزینه ماهانه (دلار، ۰ = بدون سقف)</label><input class="input ltr" name="monthly_limit_usd" inputmode="decimal" value="${s.monthly_limit_usd || 0}"></div>
          <div class="row"><button class="btn primary" type="submit">${icon("check")} ذخیره</button>
            <button class="btn soft" type="button" id="test">${icon("zap", "sm")} آزمایش اتصال</button>
            ${s.key_set ? html`<button class="btn ghost" type="button" id="clear">${icon("trash-2", "sm")} حذف کلید</button>` : ""}</div>
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
      const body = { proxy_url: f.proxy_url.value.trim(), monthly_limit_usd: f.monthly_limit_usd.value.replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)) || 0 };
      if (f.api_key.value.trim()) body.api_key = f.api_key.value.trim();
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
    $("#clear", view)?.addEventListener("click", async () => {
      await api("/api/media/settings", { method: "PUT", body: { clear_key: true } });
      toast("کلید حذف شد");
      draw();
    });
  };
  await draw();
}
export { raw };
