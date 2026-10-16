// Team & permissions (owners only): one login per person, and which modules each person can open with which role.
import { $, ago, api, avatar, confirmBox, delegate, emptyState, fa, formData, html, icon, raw, sheet, state, toast } from "../kit.js";

export async function render(view, params, { setTitle }) {
  setTitle("تیم و دسترسی‌ها", "هر نفر یک ورود؛ دسترسی هر بخش جدا");
  const load = async () => {
    const data = await api("/api/team");
    draw(data);
  };
  const draw = ({ users, modules }) => {
    const roleLabel = (mid, role) => modules.find((m) => m.id === mid)?.roles[role] || role;
    view.innerHTML = String(html`<div class="grid side">
      <section class="card">
        <div class="card-head"><h2>${icon("users")} اعضای تیم</h2><span class="spacer"></span>
          <button class="btn sm primary" id="add">${icon("user-plus", "sm")} عضو جدید</button></div>
        ${users.length ? html`<div class="list">${users.map((u) => html`<div class="list-item clickable" data-user="${u.id}">
          ${avatar(u.name)}<div class="grow"><div class="title">${u.name} <span class="muted small ltr">@${u.username}</span>
            ${u.is_admin ? html`<span class="badge primary">${icon("shield")}مدیر کل</span>` : ""}
            ${u.active ? "" : html`<span class="badge">غیرفعال</span>`}</div>
            <div class="sub">${u.is_admin ? "همه بخش‌ها" : Object.keys(u.access).length
              ? Object.entries(u.access).map(([m, r]) => `${modules.find((x) => x.id === m)?.name || m}: ${roleLabel(m, r)}`).join(" · ")
              : "بدون دسترسی"}</div>
            <div class="tiny muted">${u.last_seen_at ? `آخرین فعالیت ${ago(u.last_seen_at)}` : u.last_login_at ? `آخرین ورود ${ago(u.last_login_at)}` : "هنوز وارد نشده"}</div>
          </div>${icon("chevron-left", "sm")}</div>`)}</div>` : emptyState("users", "کسی نیست")}
      </section>
      <section class="card">
        <h3>${icon("info", "sm")} دسترسی‌ها چطور کار می‌کنند؟</h3>
        <ul class="small mt8" style="line-height:2.1;padding-inline-start:20px">
          <li><b>مدیر کل</b> (شرکا): همه بخش‌ها، این صفحه، تنظیمات و پشتیبان‌ها.</li>
          ${modules.map((m) => html`<li><b>${m.name}</b>: ${Object.values(m.roles).join(" / ")}</li>`)}
          <li>کسی که به بخشی دسترسی ندارد آن را در منو هم نمی‌بیند و سرور هم درخواستش را رد می‌کند.</li>
          <li>با غیرفعال کردن یا عوض کردن رمز، آن فرد از همه دستگاه‌ها خارج می‌شود.</li>
        </ul>
      </section>
    </div>`);
    $("#add", view).onclick = () => userForm(null, modules, load);
    delegate(view, "click", "[data-user]", (e, row) => userForm(users.find((u) => u.id === Number(row.dataset.user)), modules, load));
  };
  await load();
}

function userForm(u, modules, done) {
  const self = u && u.id === state.me.user.id;
  const grants = u?.grants || {};
  const s = sheet({
    title: u ? `ویرایش ${u.name}` : "عضو جدید",
    body: html`<div class="stack s12" id="uf">
      <div class="form-grid">
        <div class="field"><label>نام</label><input class="input" name="name" value="${u?.name || ""}" placeholder="مثلاً سارا" required></div>
        <div class="field"><label>نام کاربری (انگلیسی)</label><input class="input ltr" name="username" value="${u?.username || ""}" ${u ? raw("disabled") : ""} autocomplete="off"></div>
      </div>
      <div class="field"><label>${u ? "رمز جدید (خالی = بدون تغییر)" : "رمز عبور (حداقل ۶ حرف)"}</label>
        <input class="input ltr" name="password" type="text" autocomplete="new-password"></div>
      <label class="check"><span class="switch"><input type="checkbox" name="is_admin" ${u?.is_admin ? raw("checked") : ""} ${self ? raw("disabled") : ""}><span></span></span>
        مدیر کل (شریک) — همه بخش‌ها و تنظیمات</label>
      <div class="inset" id="perm-box">
        <div class="label" style="margin-bottom:10px">دسترسی به هر بخش</div>
        <div class="perm-grid">${modules.map((m) => html`
          <div><div class="bold small">${icon(m.icon, "sm")} ${m.name}</div></div>
          <select class="select sm" name="grant_${m.id}" style="width:auto;min-width:170px">
            <option value="">بدون دسترسی</option>
            ${Object.entries(m.roles).map(([r, label]) => html`<option value="${r}" ${grants[m.id] === r ? raw("selected") : ""}>${label}</option>`)}
          </select>`)}</div>
        <div class="field mt12 ${grants.erp === "seller" ? "" : "hidden"}" id="commission-field">
          <label>پورسانت از هر فروش (٪)</label><input class="input sm" name="commission_pct" data-num inputmode="decimal" placeholder="۰"></div>
      </div>
      ${u ? html`<label class="check"><span class="switch"><input type="checkbox" name="active" ${u.active ? raw("checked") : ""} ${self ? raw("disabled") : ""}><span></span></span>فعال (می‌تواند وارد شود)</label>` : ""}
    </div>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ذخیره</button>
      ${u && !self ? html`<button class="btn ghost" id="kick">${icon("log-out", "sm")} خروج از همه دستگاه‌ها</button>` : ""}
      <span class="spacer"></span><button class="btn ghost" data-close>انصراف</button>`,
  });
  const box = s.root.querySelector("#uf");
  const syncAdmin = () => {
    const admin = box.querySelector("[name=is_admin]").checked;
    s.root.querySelector("#perm-box").style.opacity = admin ? ".45" : "";
    s.root.querySelectorAll("#perm-box select").forEach((el) => { el.disabled = admin; });
  };
  box.querySelector("[name=is_admin]").addEventListener("change", syncAdmin);
  box.querySelector("[name=grant_erp]")?.addEventListener("change", (e) => {
    s.root.querySelector("#commission-field").classList.toggle("hidden", e.target.value !== "seller");
  });
  syncAdmin();
  s.root.querySelector("#kick")?.addEventListener("click", async () => {
    if (!(await confirmBox(`${u.name} از همه دستگاه‌ها خارج شود؟`, { okText: "خارج کن" }))) return;
    await api(`/api/team/${u.id}/sessions`, { method: "DELETE" });
    toast("خارج شد");
  });
  s.root.querySelector("#save").onclick = async () => {
    const f = formData(box);
    const body = { name: f.name, is_admin: f.is_admin, grants: {} };
    for (const m of modules) if (f[`grant_${m.id}`]) body.grants[m.id] = f[`grant_${m.id}`];
    if (f.password) body.password = f.password;
    if (u) body.active = f.active;
    else body.username = f.username;
    if (body.grants.erp === "seller" && f.commission_pct !== null) body.profile = { erp: { commission_pct: f.commission_pct } };
    if (u) await api(`/api/team/${u.id}`, { method: "PUT", body });
    else await api("/api/team", { method: "POST", body });
    toast(u ? "ذخیره شد" : `${f.name} اضافه شد`);
    s.close();
    done && done();
  };
}
export { fa };
