// The signed-in user's own account: who they are, what they can open, password.
import { $, api, html, icon, state, toast, toggleTheme } from "../kit.js";

export async function render(view, params, { setTitle }) {
  const me = state.me;
  setTitle("حساب من", `@${me.user.username}`);
  view.innerHTML = String(html`<div class="grid g2">
    <section class="card">
      <div class="card-head"><h2>${icon("shield-check")} دسترسی‌های شما</h2></div>
      <div class="list">
        ${me.user.is_admin ? html`<div class="list-item"><span class="badge primary">${icon("shield")}مدیر کل</span>
          <div class="grow small muted">به همه بخش‌ها، تیم و تنظیمات دسترسی دارید.</div></div>` : ""}
        ${me.modules.map((m) => html`<div class="list-item">${icon(m.icon)}<div class="grow"><div class="title">${m.name}</div>
          <div class="sub">${m.description}</div></div><span class="role-pill">${m.roles[m.role] || m.role}</span></div>`)}
      </div>
    </section>
    <section class="card">
      <div class="card-head"><h2>${icon("lock")} تغییر رمز عبور</h2><p>بعد از تغییر، بقیه دستگاه‌هایی که با حساب شما وارد شده‌اند خارج می‌شوند.</p></div>
      <form class="stack s12" id="pw">
        <div class="field"><label>رمز فعلی</label><input class="input ltr" type="password" name="current" autocomplete="current-password" required></div>
        <div class="field"><label>رمز جدید (حداقل ۶ حرف)</label><input class="input ltr" type="password" name="new" autocomplete="new-password" minlength="6" required></div>
        <button class="btn primary" type="submit">${icon("check")} تغییر رمز</button>
      </form>
      <div class="divider"></div>
      <div class="row"><span class="grow small">ظاهر برنامه</span><button class="btn sm soft" id="theme">${icon("moon", "sm")} روشن / تیره</button></div>
    </section>
  </div>`);
  $("#pw", view).onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/me/password", { method: "POST", body: { current: e.target.current.value, new: e.target.new.value } });
    toast("رمز عوض شد");
    e.target.reset();
  };
  $("#theme", view).onclick = (e) => toggleTheme(e.currentTarget);
}
