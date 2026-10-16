// Money: account balances, partner stakes and settlement, money held by sellers, capital and transfers.
import { $, api, compact, confirmBox, delegate, fa, html, icon, jdate, num, on, sheet, toast, toman } from "/static/js/kit.js";
import { avatar, bindChoices, bindDates, bindMoney, choiceChips, dateField, emptyState, formData, moneyField, selectOptions } from "/static/js/kit.js";
import { accountOptions, erp, refreshMe } from "../erp.js";

const KIND = { shop: "فروشگاه", partner: "شخصی شریک", agent: "نزد فروشنده" };
const SRC = { sale: "فروش", purchase: "خرید کالا", expense: "هزینه", capital: "آورده/برداشت", transfer: "انتقال" };

export async function render(view, params, { setTitle }) {
  setTitle("حساب‌ها و شرکا", "پول کجاست و چه کسی به چه کسی بدهکار است");
  let d = await api("/api/erp/money");
  const draw = () => { view.innerHTML = String(page(d)); };
  draw();
  const reload = async () => { d = await api("/api/erp/money", { quiet: true }); await refreshMe(); draw(); };

  delegate(view, "click", "[data-act]", (e, el) => {
    const act = el.dataset.act;
    if (act === "settle") openSettlement(d.partners.settlement[Number(el.dataset.i)], reload);
    if (act === "capital-in") openCapital("in", reload);
    if (act === "capital-out") openCapital("out", reload);
    if (act === "transfer") openTransfer({}, reload);
    if (act === "new-account") openAccount(null, reload);
    if (act === "handover") {
      const acc = d.accounts.find((a) => a.id === Number(el.dataset.id));
      openTransfer({ from_account: acc.id, amount: acc.balance, kind: "handover", title: `تحویل پول از ${acc.name}` }, reload);
    }
  });
  delegate(view, "click", "[data-account]", (e, el) => { if (!e.target.closest("button")) openStatement(d.accounts.find((a) => a.id === Number(el.dataset.account)), reload); });
  delegate(view, "click", "[data-del-cap]", async (e, el) => {
    if (!(await confirmBox("این ردیف حذف شود؟", { danger: true, okText: "حذف" }))) return;
    await api(`/api/erp/capital/${el.dataset.delCap}`, { method: "DELETE" }); reload();
  });
  delegate(view, "click", "[data-del-tr]", async (e, el) => {
    if (!(await confirmBox("این انتقال/تسویه حذف شود؟", { danger: true, okText: "حذف" }))) return;
    await api(`/api/erp/transfers/${el.dataset.delTr}`, { method: "DELETE" }); reload();
  });
  let timer;
  const off = on("live:erp", (ev) => {
    if (ev.type === "refresh" && ["money", "sales", "expenses", "purchases"].includes(ev.scope)) { clearTimeout(timer); timer = setTimeout(reload, 800); }
  });
  return () => { off(); clearTimeout(timer); };
}

function page(d) {
  const P = d.partners;
  const maxNet = Math.max(1, ...P.partners.map((p) => Math.abs(p.net)));
  const shopAccs = d.accounts.filter((a) => a.kind !== "agent" && a.active);
  const agents = d.accounts.filter((a) => a.kind === "agent" && (a.active || a.balance));
  return html`<div class="stack">
    <section class="hero">
      <span class="blob-deco" style="width:240px;height:240px;left:-70px;top:-90px"></span>
      <div class="row between" style="align-items:flex-start">
        <div><h1>${icon("handshake")} تسویه شرکا</h1>
          <p class="muted small">هر شریک به اندازه سهمش باید در فروشگاه پول گذاشته باشد. اختلاف را با یک انتقال صاف کنید.</p></div>
      </div>
      ${P.settlement.length ? P.settlement.map((m, i) => html`<div class="row mt16" style="gap:14px">
          <div class="row nowrap">${avatar(m.from_name)}<span class="bold">${m.from_name}</span>${icon("arrow-left")}${avatar(m.to_name)}<span class="bold">${m.to_name}</span></div>
          <div class="money-big">${num(m.amount)} <span class="small muted">تومان</span></div>
          <button class="btn primary" data-act="settle" data-i="${i}">${icon("check")} ثبت این تسویه</button>
        </div>`) : html`<div class="callout ok mt16">${icon("circle-check")}<div><b>حساب شرکا صاف است.</b> هر کدام به نسبت سهمشان پول گذاشته‌اند.</div></div>`}
    </section>

    <div class="grid g2">
      ${P.partners.map((p) => html`<section class="card">
        <div class="card-head">${avatar(p.name)}<h2>${p.name}</h2><span class="badge primary">سهم ${fa(p.share)}٪</span><span class="spacer"></span>
          <span class="badge ${p.excess > 0 ? "ok" : p.excess < 0 ? "coral" : ""}">${p.excess > 0 ? `طلبکار ${compact(p.excess)}` : p.excess < 0 ? `بدهکار ${compact(-p.excess)}` : "صاف"}</span></div>
        <div class="small muted">آورده خالص در فروشگاه</div>
        <div class="money-big">${num(p.net)} <span class="small muted">تومان</span></div>
        <div class="bar-track mt8"><div class="bar-fill ${p.id === 1 ? "c1" : "c2"}" style="width:${Math.max(3, (Math.abs(p.net) / maxNet) * 100)}%"></div></div>
        <div class="list mt12 small">
          <div class="list-item"><span class="grow">آورده سرمایه</span><b class="num">${num(p.capital_in)}</b></div>
          <div class="list-item"><span class="grow">خرید و هزینه از کارت شخصی</span><b class="num">${num(p.paid_expenses)}</b></div>
          ${p.received_sales ? html`<div class="list-item"><span class="grow">پول فروش که به کارتش آمده</span><b class="num bad-ink">−${num(p.received_sales)}</b></div>` : ""}
          ${p.transfers_out ? html`<div class="list-item"><span class="grow">انتقال/تسویه پرداختی</span><b class="num">${num(p.transfers_out)}</b></div>` : ""}
          ${p.transfers_in ? html`<div class="list-item"><span class="grow">انتقال/تسویه دریافتی</span><b class="num bad-ink">−${num(p.transfers_in)}</b></div>` : ""}
          ${p.capital_out ? html`<div class="list-item"><span class="grow">برداشت</span><b class="num bad-ink">−${num(p.capital_out)}</b></div>` : ""}
          <div class="list-item"><span class="grow muted">سهم منصفانه از کل (${compact(P.total_net)})</span><b class="num">${num(Math.round(p.fair))}</b></div>
        </div>
      </section>`)}
    </div>

    <details class="card tight"><summary class="bold" style="cursor:pointer">${icon("info", "sm")} این اعداد چطور حساب می‌شوند؟</summary>
      <div class="small mt12" style="line-height:2">
        <p>• <b>آورده خالص</b> هر شریک = پولی که به فروشگاه داده (آورده سرمایه + خرید و هزینه‌هایی که از کارت شخصی‌اش پرداخته) منهای پولی از فروشگاه که دست اوست (فروش‌هایی که پولش به کارت او واریز شده، برداشت‌ها).</p>
        <p>• <b>سهم منصفانه</b> = جمع آورده همه شرکا × درصد سهم هر شریک.</p>
        <p>• اختلاف این دو می‌گوید چه کسی باید به چه کسی پول بدهد. با «ثبت این تسویه» یک انتقال از کارت بدهکار به کارت طلبکار ثبت می‌شود و حساب صفر می‌شود.</p>
        <p>• پولی که در حساب‌های «فروشگاه» (درگاه سایت، صندوق، حساب مشترک) است مال هیچ‌کدام نیست و در این حساب نمی‌آید.</p>
      </div></details>

    <section class="card">
      <div class="card-head"><h2>${icon("wallet")} حساب‌ها</h2><span class="spacer"></span>
        <div class="btn-group">
          <button class="btn sm soft" data-act="capital-in">${icon("piggy-bank", "sm")} آورده سرمایه</button>
          <button class="btn sm ghost" data-act="capital-out">${icon("hand-coins", "sm")} برداشت</button>
          <button class="btn sm ghost" data-act="transfer">${icon("arrow-left-right", "sm")} انتقال بین حساب‌ها</button>
          <button class="btn sm ghost" data-act="new-account">${icon("plus", "sm")} حساب جدید</button>
        </div>
        <p>مانده هر حساب = دریافتی‌ها − پرداختی‌ها. مانده منفی کارت شخصی یعنی آن شریک از جیب خودش برای فروشگاه خرج کرده.</p></div>
      <div class="grid g3" style="gap:14px">
        ${shopAccs.map((a) => html`<div class="kpi ${a.kind === "partner" ? "orchid" : "indigo"}" data-account="${a.id}" style="cursor:pointer;min-height:110px">
          <span class="k-icon">${icon(a.kind === "partner" ? "credit-card" : "landmark")}</span>
          <div class="k-label">${a.name}</div>
          <div class="k-value num ${a.balance < 0 ? "bad-ink" : ""}">${compact(a.balance)}<span class="k-unit">تومان</span></div>
          <div class="k-foot">${KIND[a.kind]}، ${fa(a.n)} گردش</div></div>`)}
      </div>
    </section>

    <section class="card">
      <div class="card-head"><h2>${icon("users")} پول نزد فروشنده‌ها و دوستان</h2>
        <p>وقتی دوستی از طرف شما می‌فروشد، پول تا وقتی تحویل ندهد اینجا می‌ماند (پورسانت او کم شده).</p></div>
      ${agents.length ? html`<div class="list">${agents.map((a) => html`<div class="list-item clickable" data-account="${a.id}">
          ${avatar(a.user_name || a.name)}<div class="grow"><div class="title">${a.user_name || a.name}</div><div class="sub">${fa(a.n)} گردش</div></div>
          <span class="stack s8" style="align-items:flex-end;gap:0"><b class="num ${a.balance > 0 ? "warn-ink" : ""}">${num(Math.abs(a.balance))}</b>
            <span class="tiny muted">${a.balance > 0 ? "باید تحویل بدهد" : a.balance < 0 ? "فروشگاه به او بدهکار است" : "تسویه"}</span></span>
          ${a.balance > 0 ? html`<button class="btn sm soft" data-act="handover" data-id="${a.id}">${icon("hand-coins", "sm")} تحویل گرفتم</button>` : ""}
        </div>`)}</div>`
        : emptyState("users", "هنوز فروشنده‌ای تعریف نشده", "از «تنظیمات ← کاربران» برای دوستانی که برایتان می‌فروشند حساب بسازید.")}
    </section>

    <div class="grid g2">
      <section class="card">
        <div class="card-head"><h2>${icon("piggy-bank")} آورده و برداشت</h2></div>
        ${d.capital.length ? html`<div class="table-wrap"><table class="t responsive"><tbody>${d.capital.map((c) => html`<tr>
          <td class="nowrap">${jdate(c.date, { year: false })}</td><td><span class="badge ${c.kind === "in" ? "ok" : "coral"}">${c.kind === "in" ? "آورده" : "برداشت"}</span> ${c.partner_name}</td>
          <td class="small muted m-full">${c.account_name || ""}${c.note ? html`، <bdi>${c.note}</bdi>` : ""}</td><td class="n bold">${num(c.amount)}</td>
          <td><button class="btn icon xs ghost" data-del-cap="${c.id}" aria-label="حذف">${icon("trash-2", "sm")}</button></td></tr>`)}</tbody></table></div>`
          : emptyState("piggy-bank", "ردیفی نیست")}
      </section>
      <section class="card">
        <div class="card-head"><h2>${icon("arrow-left-right")} انتقال‌ها و تسویه‌ها</h2></div>
        ${d.transfers.length ? html`<div class="table-wrap"><table class="t responsive"><tbody>${d.transfers.map((t) => html`<tr>
          <td class="nowrap">${jdate(t.date, { year: false })}</td>
          <td><span class="badge ${t.kind === "settlement" ? "primary" : t.kind === "handover" ? "ok" : ""}">${t.kind === "settlement" ? "تسویه" : t.kind === "handover" ? "تحویل" : "انتقال"}</span></td>
          <td class="small m-full">${t.from_name} ← ${t.to_name}${t.note ? html`<span class="muted">، <bdi>${t.note}</bdi></span>` : ""}</td><td class="n bold">${num(t.amount)}</td>
          <td><button class="btn icon xs ghost" data-del-tr="${t.id}" aria-label="حذف">${icon("trash-2", "sm")}</button></td></tr>`)}</tbody></table></div>`
          : emptyState("arrow-left-right", "ردیفی نیست")}
      </section>
    </div>
  </div>`;
}

export function openSettlement(move, done) {
  if (!move) return;
  openTransfer({ from_account: move.from_account, to_account: move.to_account, amount: move.amount, kind: "settlement",
    title: `تسویه: ${move.from_name} به ${move.to_name}`, note: "تسویه شرکا" }, done);
}

function openTransfer({ from_account = "", to_account = "", amount = "", kind = "transfer", title = "انتقال بین حساب‌ها", note = "" }, done) {
  const s = sheet({
    title,
    body: html`<div class="stack s12" id="tf">
      ${moneyField({ name: "amount", label: "مبلغ", value: amount, big: true })}
      <div class="form-grid">
        <div class="field"><label>از حساب</label><select class="select" name="from_account">${accountOptions(from_account, { includeEmpty: "انتخاب کنید" })}</select></div>
        <div class="field"><label>به حساب</label><select class="select" name="to_account">${accountOptions(to_account, { includeEmpty: "انتخاب کنید" })}</select></div>
        ${dateField({ name: "date", label: "تاریخ", value: erp.me.today })}
        <div class="field"><label>یادداشت</label><input class="input" name="note" value="${note}"></div>
      </div>
      <input type="hidden" name="kind" value="${kind}">
    </div>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ثبت</button><button class="btn ghost" data-close>انصراف</button>`,
  });
  bindMoney(s.root); bindDates(s.root);
  s.root.querySelector("#save").onclick = async () => {
    const f = formData(s.root.querySelector("#tf"));
    await api("/api/erp/transfers", { method: "POST", body: { ...f, from_account: Number(f.from_account), to_account: Number(f.to_account) } });
    toast("ثبت شد");
    s.close();
    done && done();
  };
}

function openCapital(kind, done) {
  const partners = erp.me.partners.filter((p) => p.active);
  const s = sheet({
    title: kind === "in" ? "آورده سرمایه" : "برداشت شریک",
    body: html`<div class="stack s12" id="cf">
      <div class="field"><label>شریک</label>${choiceChips("partner_id", partners.map((p) => ({ value: p.id, label: p.name })), erp.me.user.partner_id || partners[0]?.id)}</div>
      ${moneyField({ name: "amount", label: "مبلغ", big: true })}
      <div class="form-grid">
        <div class="field"><label>${kind === "in" ? "به کدام حساب واریز شد؟" : "از کدام حساب برداشت شد؟"}</label>
          <select class="select" name="account_id">${accountOptions(kind === "in" ? 4 : "", { includeEmpty: "—", kinds: ["shop"] })}</select></div>
        ${dateField({ name: "date", label: "تاریخ", value: erp.me.today })}
        <div class="field full"><label>یادداشت</label><input class="input" name="note"></div>
      </div>
      <div class="callout">${icon("info")}<div>${kind === "in"
        ? "آورده یعنی پولی که شریک از جیب خودش به حساب فروشگاه ریخته. خرج‌هایی که مستقیم از کارت شخصی شده‌اند را لازم نیست اینجا ثبت کنید؛ همان هزینه/خرید کافی است."
        : "برداشت یعنی شریک پولی از حساب فروشگاه برای خودش برداشته (مثلاً تقسیم سود)."}</div></div>
      <input type="hidden" name="kind" value="${kind}">
    </div>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ثبت</button><button class="btn ghost" data-close>انصراف</button>`,
  });
  bindMoney(s.root); bindDates(s.root); bindChoices(s.root);
  s.root.querySelector("#save").onclick = async () => {
    const f = formData(s.root.querySelector("#cf"));
    await api("/api/erp/capital", { method: "POST", body: { ...f, partner_id: Number(f.partner_id), account_id: Number(f.account_id) || null } });
    toast("ثبت شد");
    s.close();
    done && done();
  };
}

export function openAccount(acc, done) {
  const s = sheet({
    title: acc ? `ویرایش «${acc.name}»` : "حساب جدید",
    body: html`<div class="stack s12" id="af">
      <div class="field"><label>نام حساب</label><input class="input" name="name" value="${acc?.name || ""}" placeholder="مثلاً: کارت بانک ملت امیر"></div>
      ${acc?.kind === "agent" ? "" : html`<div class="field"><label>نوع</label>${choiceChips("kind", [{ value: "shop", label: "حساب فروشگاه" }, { value: "partner", label: "کارت شخصی شریک" }], acc?.kind || "shop")}</div>
      <div class="field"><label>صاحب کارت (برای کارت شخصی)</label><select class="select" name="partner_id">${selectOptions(erp.me.partners.map((p) => ({ value: p.id, label: p.name })), acc?.partner_id, "—")}</select></div>`}
      <div class="field"><label>توضیح</label><input class="input" name="note" value="${acc?.note || ""}"></div>
      ${acc ? html`<label class="check"><span class="switch"><input type="checkbox" name="active" ${acc.active ? "checked" : ""}><span></span></span>فعال</label>` : ""}
    </div>`,
    foot: html`<button class="btn primary" id="save">${icon("check")} ذخیره</button><button class="btn ghost" data-close>انصراف</button>`,
  });
  bindChoices(s.root);
  s.root.querySelector("#save").onclick = async () => {
    const f = formData(s.root.querySelector("#af"));
    const body = { ...f, partner_id: Number(f.partner_id) || null };
    if (acc) await api(`/api/erp/accounts/${acc.id}`, { method: "PUT", body });
    else await api("/api/erp/accounts", { method: "POST", body });
    toast("ذخیره شد");
    s.close();
    done && done();
  };
}

async function openStatement(acc, done) {
  const s = sheet({ title: acc.name, side: true, body: '<div class="skeleton" style="height:300px"></div>',
    foot: html`<button class="btn sm ghost" id="edit">${icon("pencil", "sm")} ویرایش حساب</button>` });
  s.root.querySelector("#edit").onclick = () => { s.close(); openAccount(acc, done); };
  const rows = await api(`/api/erp/accounts/${acc.id}/flows`);
  s.root.querySelector(".sheet-body").innerHTML = String(html`<div class="stack">
    <div class="inset row between"><span>مانده</span><b class="num ${acc.balance < 0 ? "bad-ink" : ""}" style="font-size:20px">${toman(acc.balance)}</b></div>
    <div class="row small"><span class="badge ok">ورودی ${compact(acc.money_in)}</span><span class="badge coral">خروجی ${compact(acc.money_out)}</span></div>
    ${rows.length ? html`<div class="table-wrap"><table class="t">
      <thead><tr><th>تاریخ</th><th>شرح</th><th class="n">مبلغ</th><th class="n">مانده</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td class="nowrap small">${jdate(r.date, { year: false })}</td>
        <td class="small"><span class="badge">${SRC[r.src]}</span> ${r.label || ""}</td>
        <td class="n bold ${r.amount < 0 ? "bad-ink" : "ok-ink"}">${r.amount < 0 ? "−" : "+"}${num(Math.abs(r.amount))}</td>
        <td class="n small">${num(r.running)}</td></tr>`)}</tbody></table></div>` : emptyState("wallet", "گردشی ندارد")}
  </div>`);
}
