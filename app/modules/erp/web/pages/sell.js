// Quick sale: tap products, adjust quantity/price, pick channel and where the money went, done.
// Stock drops immediately and (when linked) the site is updated within seconds.
import { $, api, delegate, fa, html, icon, num, numWords, on, parseNum, sheet, toast, toman } from "/static/js/kit.js";
import { bindChoices, bindDates, bindMoney, choiceChips, dateField, emptyState, formData, moneyField, thumb } from "/static/js/kit.js";
import { accountChoice, CHANNEL_ICON, erp, isAdmin, stockBadge } from "../erp.js";

const norm = (s) => String(s || "").replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ").toLowerCase();

export async function render(view, params, { setTitle }) {
  setTitle(isAdmin() ? "فروش سریع" : "ثبت فروش", "محصول را لمس کنید تا به سبد اضافه شود");
  let products = await api("/api/erp/products");
  const cart = new Map();           // product_id -> { qty, unit_price }
  let q = "", cat = "", lastSale = null;
  const admin = isAdmin();
  const channelOpts = (admin
    ? ["in_person", "instagram", "agent", "website", "other"]
    : ["agent", "in_person", "instagram", "other"]).map((c) => ({ value: c, label: erp.me.channels[c], icon: CHANNEL_ICON[c] }));
  const meta = {
    channel: admin ? "in_person" : "agent", date: erp.me.today, paid: true,
    account_id: admin ? (erp.me.settings.channel_accounts || {}).in_person : erp.me.user.account_id,
    seller_id: erp.me.user.id, discount: 0, shipping: 0, customer_name: "", customer_phone: "", note: "",
  };

  view.innerHTML = String(html`<div class="grid side-r">
    <section class="stack s12" style="min-width:0">
      <div class="card tight">
        <div class="input-wrap">${icon("search")}<input enterkeyhint="search" class="input" id="q" placeholder="جستجوی نام، برند یا کد محصول…" autocomplete="off"></div>
        <div class="chips scroll mt12" id="cats"></div>
      </div>
      <div class="tiles" id="tiles"></div>
    </section>
    <aside class="card cart" id="cart"></aside>
  </div>
  <button class="btn brand lg hidden cart-bar" id="cart-bar"></button>`);

  const tilesEl = $("#tiles", view), cartEl = $("#cart", view), catsEl = $("#cats", view), bar = $("#cart-bar", view);

  function drawCats() {
    const cats = [...new Set(products.map((p) => p.category).filter(Boolean))];
    catsEl.innerHTML = String(html`<button class="chip ${!cat ? "on" : ""}" data-cat="">همه</button>
      ${cats.map((c) => html`<button class="chip ${cat === c ? "on" : ""}" data-cat="${c}">${c}</button>`)}`);
  }
  function filtered() {
    const terms = norm(q).split(/\s+/).filter(Boolean);
    return products
      .filter((p) => !cat || p.category === cat)
      .filter((p) => !terms.length || terms.every((t) => norm(`${p.name} ${p.brand || ""} ${p.sku || ""}`).includes(t)))
      .sort((a, b) => (b.stock > 0) - (a.stock > 0) || (b.sold_30 || 0) - (a.sold_30 || 0) || a.name.localeCompare(b.name, "fa"));
  }
  function drawTiles() {
    const list = filtered();
    tilesEl.innerHTML = list.length ? String(html`${list.map((p) => {
      const inCart = cart.get(p.id)?.qty || 0;
      return html`<button class="tile ${p.stock <= 0 ? "out" : ""}" data-add="${p.id}" title="${p.name}">
        ${inCart ? html`<span class="in-cart">${fa(inCart)}</span>` : ""}
        <span class="t-img">${p.image ? html`<img src="${p.image}" alt="" loading="lazy" referrerpolicy="no-referrer">` : icon("package", "lg")}</span>
        <span class="t-name">${p.name}</span>
        <span class="t-foot"><span class="t-price">${num(p.price)}</span>${stockBadge({ ...p, stock: p.stock - inCart })}</span>
      </button>`;
    })}`) : String(emptyState("search", "محصولی پیدا نشد", q ? "عبارت دیگری را امتحان کنید." : "هنوز محصولی ثبت نشده."));
  }
  function totals() {
    let subtotal = 0, count = 0;
    cart.forEach((l) => { subtotal += l.qty * l.unit_price; count += l.qty; });
    const total = Math.max(0, subtotal - (meta.discount || 0) + (meta.shipping || 0));
    return { subtotal, count, total };
  }
  function drawCart() {
    const t = totals();
    const lines = [...cart.entries()].map(([id, l]) => ({ ...l, p: products.find((x) => x.id === id) })).filter((l) => l.p);
    cartEl.innerHTML = String(html`
      <div class="row between"><h2>${icon("shopping-cart")} سبد فروش</h2>
        ${cart.size ? html`<button class="btn xs ghost" data-clear>${icon("trash-2", "sm")} خالی کردن</button>` : ""}</div>
      <div class="cart-lines">
        ${lines.length ? lines.map((l) => html`<div class="cart-line">
          ${thumb(l.p, "sm")}
          <div class="grow"><div class="cl-name">${l.p.name}</div>
            <button class="price-edit" data-price="${l.p.id}" title="تغییر قیمت">${num(l.unit_price)} تومان</button>
            ${l.p.stock - l.qty < 0 ? html`<div class="tiny bad-ink">موجودی کافی نیست (${fa(l.p.stock)} عدد)</div>` : ""}
          </div>
          <div class="stepper"><button data-inc="${l.p.id}" aria-label="یکی بیشتر">${icon("plus", "sm")}</button>
            <input value="${fa(l.qty)}" data-qty="${l.p.id}" inputmode="numeric" aria-label="تعداد">
            <button data-dec="${l.p.id}" aria-label="یکی کمتر">${icon(l.qty > 1 ? "minus" : "trash-2", "sm")}</button></div>
        </div>`) : html`<div class="empty" style="padding:18px"><div class="blob">${icon("shopping-bag")}</div><p class="small">محصول را از فهرست انتخاب کنید</p></div>`}
      </div>
      <div class="stack s12" id="meta">
        <div class="field"><label>کانال فروش</label>${choiceChips("channel", channelOpts, meta.channel)}</div>
        ${admin ? html`<div class="field"><label>پول به کدام حساب رفت؟</label>${accountChoice("account_id", meta.account_id)}</div>` : ""}
        <label class="check"><span class="switch"><input type="checkbox" name="paid" ${meta.paid ? "checked" : ""}><span></span></span>
          پول را گرفتم ${meta.paid ? "" : html`<span class="badge warn">نسیه / بعداً</span>`}</label>
        <div class="form-grid">
          <div class="field"><label>نام مشتری</label><input class="input" name="customer_name" value="${meta.customer_name}" placeholder="اختیاری"></div>
          <div class="field"><label>تلفن</label><input class="input ltr" name="customer_phone" value="${meta.customer_phone}" inputmode="tel" placeholder="اختیاری"></div>
        </div>
        <details ${meta.discount || meta.shipping || meta.note || (admin && meta.date !== erp.me.today) ? "open" : ""}>
          <summary class="small muted" style="cursor:pointer;padding:4px 0">تخفیف، هزینه ارسال، تاریخ و یادداشت</summary>
          <div class="stack s12 mt12">
            <div class="form-grid">
              ${moneyField({ name: "discount", label: "تخفیف کل", value: meta.discount || "" })}
              ${moneyField({ name: "shipping", label: "هزینه ارسال (از مشتری)", value: meta.shipping || "" })}
            </div>
            ${admin ? html`<div class="form-grid">${dateField({ name: "date", label: "تاریخ فروش", value: meta.date })}
              <div class="field"><label>فروشنده</label><select class="select" name="seller_id">
                ${erp.me.users.filter((u) => u.active).map((u) => html`<option value="${u.id}" ${u.id === meta.seller_id ? "selected" : ""}>${u.name}</option>`)}
              </select></div></div>` : ""}
            <div class="field"><label>یادداشت</label><input class="input" name="note" value="${meta.note}" placeholder="مثلاً: ارسال با پیک"></div>
          </div>
        </details>
      </div>
      <div class="totals">
        <div class="t-row"><span class="muted">${fa(t.count)} عدد</span><span class="num">${num(t.subtotal)}</span></div>
        ${meta.discount ? html`<div class="t-row"><span class="muted">تخفیف</span><span class="num bad-ink">−${num(meta.discount)}</span></div>` : ""}
        ${meta.shipping ? html`<div class="t-row"><span class="muted">ارسال</span><span class="num">+${num(meta.shipping)}</span></div>` : ""}
        <div class="t-row t-grand"><span>مبلغ نهایی</span><span class="num">${num(t.total)} <small class="muted">تومان</small></span></div>
        ${t.total ? html`<div class="tiny muted">${numWords(t.total)} تومان</div>` : ""}
      </div>
      <button class="btn brand lg block" data-submit ${cart.size ? "" : "disabled"}>${icon("check")} ثبت فروش</button>`);
    updateBar();
    bar.innerHTML = String(html`${icon("shopping-cart")} ${fa(t.count)} عدد، ${num(t.total)} تومان — ادامه`);
  }
  // floating "cart" button on phones: only while the cart itself is off screen
  let cartVisible = false;
  function updateBar() { bar.classList.toggle("hidden", !cart.size || window.innerWidth > 1180 || cartVisible); }
  const io = new IntersectionObserver((entries) => { cartVisible = entries[0].isIntersecting; updateBar(); });
  io.observe(cartEl);
  function captureMeta() {
    const f = formData($("#meta", cartEl));
    Object.assign(meta, {
      channel: f.channel || meta.channel, paid: f.paid, customer_name: f.customer_name || "", customer_phone: f.customer_phone || "",
      note: f.note || "", discount: f.discount || 0, shipping: f.shipping || 0,
    });
    if (admin) Object.assign(meta, { account_id: Number(f.account_id) || null, date: f.date || meta.date, seller_id: Number(f.seller_id) || meta.seller_id });
  }
  function add(id, by = 1) {
    const p = products.find((x) => x.id === id);
    if (!p) return;
    captureMeta();
    const line = cart.get(id) || { qty: 0, unit_price: p.price };
    line.qty += by;
    if (line.qty <= 0) cart.delete(id);
    else cart.set(id, line);
    if (by > 0 && p.stock - line.qty < 0) toast(`از «${p.name}» فقط ${fa(Math.max(0, p.stock))} عدد در انبار ثبت شده`, "info");
    drawTiles();
    drawCart();
    if (by > 0) tilesEl.querySelector(`[data-add="${id}"] .in-cart`)?.classList.add("bump");
  }

  drawCats(); drawTiles(); drawCart();
  bindMoney(cartEl);
  bindDates(cartEl);
  bindChoices(cartEl, (name, value) => {
    if (name === "channel" && admin) {
      const def = (erp.me.settings.channel_accounts || {})[value];
      captureMeta();
      meta.channel = value;
      if (def) meta.account_id = def;
      drawCart();
    }
  });

  $("#q", view).addEventListener("input", (e) => { q = e.target.value; drawTiles(); });
  delegate(catsEl, "click", "[data-cat]", (e, el) => { cat = el.dataset.cat; drawCats(); drawTiles(); });
  delegate(tilesEl, "click", "[data-add]", (e, el) => add(Number(el.dataset.add)));
  delegate(cartEl, "click", "[data-inc]", (e, el) => add(Number(el.dataset.inc), 1));
  delegate(cartEl, "click", "[data-dec]", (e, el) => add(Number(el.dataset.dec), -1));
  delegate(cartEl, "click", "[data-clear]", () => { cart.clear(); drawTiles(); drawCart(); });
  delegate(cartEl, "change", "[data-qty]", (e, el) => {
    const id = Number(el.dataset.qty);
    const v = Math.round(parseNum(el.value));
    captureMeta();
    if (v <= 0) cart.delete(id); else cart.get(id).qty = v;
    drawTiles(); drawCart();
  });
  delegate(cartEl, "change", "input[name=paid]", () => { captureMeta(); drawCart(); });
  delegate(cartEl, "change", "input[data-money]", () => { captureMeta(); drawCart(); });
  delegate(cartEl, "click", "[data-price]", (e, el) => editPrice(Number(el.dataset.price)));
  delegate(cartEl, "click", "[data-submit]", submit);
  bar.addEventListener("click", () => cartEl.scrollIntoView({ behavior: "smooth", block: "start" }));
  const keyHandler = (e) => {
    if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
      e.preventDefault(); $("#q", view)?.focus();
    }
  };
  document.addEventListener("keydown", keyHandler);

  function editPrice(id) {
    const line = cart.get(id);
    const p = products.find((x) => x.id === id);
    const s = sheet({
      title: `قیمت «${p.name}»`,
      body: html`<div class="stack s12">${moneyField({ name: "price", label: "قیمت هر عدد", value: line.unit_price, big: true, autofocus: true })}
        <p class="small muted">قیمت ثبت‌شده محصول: ${toman(p.price)}</p></div>`,
      foot: html`<button class="btn primary" id="ok">ثبت</button><button class="btn ghost" data-close>انصراف</button>`,
    });
    bindMoney(s.root);
    const ok = () => { line.unit_price = Math.round(parseNum(s.root.querySelector("[name=price]").value)); s.close(); captureMeta(); drawCart(); };
    s.root.querySelector("#ok").onclick = ok;
    s.root.querySelector("[name=price]").addEventListener("keydown", (e) => { if (e.key === "Enter") ok(); });
  }

  async function submit() {
    captureMeta();
    if (!cart.size) return;
    const btn = cartEl.querySelector("[data-submit]");
    btn.disabled = true;
    btn.innerHTML = String(html`${icon("loader-circle")} در حال ثبت…`);
    const body = {
      ...meta,
      items: [...cart.entries()].map(([product_id, l]) => ({ product_id, qty: l.qty, unit_price: l.unit_price })),
    };
    try {
      const res = await api("/api/erp/sales", { method: "POST", body });
      lastSale = res.id;
      const detail = await api(`/api/erp/sales/${res.id}`);
      cart.clear();
      Object.assign(meta, { discount: 0, shipping: 0, customer_name: "", customer_phone: "", note: "" });
      products = await api("/api/erp/products");
      drawTiles(); drawCart();
      showSuccess(detail);
    } catch (e) {
      btn.disabled = false;
      btn.innerHTML = String(html`${icon("check")} ثبت فروش`);
    }
  }

  function showSuccess({ sale, items }) {
    const autoPush = erp.me.site.auto_push && erp.me.site.configured;
    let offLive = () => {};
    const s = sheet({
      onClose: () => offLive(),
      title: "فروش ثبت شد",
      body: html`<div class="success-burst">${icon("check")}</div>
        <p style="text-align:center" class="bold">${sale.code}، ${toman(sale.total)}</p>
        <div class="list mt16">${items.map((it) => {
          const p = products.find((x) => x.id === it.product_id);
          const left = p ? p.stock : null;
          return html`<div class="list-item">${thumb(p || {}, "sm")}
            <div class="grow"><div class="title small">${fa(it.qty)}× ${it.name}</div>
              <div class="sub">${left === null ? "" : left <= 0 ? html`<b class="bad-ink">تمام شد</b>` : html`مانده در انبار: ${fa(left)}`}</div></div>
            <span data-site="${it.product_id}">${p && p.woo_id
              ? (autoPush ? html`<span class="badge info">${icon("loader-circle")}سایت…</span>` : html`<span class="badge warn">سایت دستی</span>`)
              : html`<span class="badge">به سایت وصل نیست</span>`}</span>
          </div>`;
        })}</div>
        ${items.some((it) => { const p = products.find((x) => x.id === it.product_id); return p && p.stock <= 0 && !p.woo_id; })
          ? html`<div class="callout warn mt16">${icon("triangle-alert")}<div>محصولی تمام شد که به سایت وصل نیست. اگر در سایت هست، آنجا ناموجودش کنید یا از صفحه «اتصال سایت» وصلش کنید.</div></div>` : ""}`,
      foot: html`<button class="btn primary" data-close>${icon("plus")} فروش بعدی</button>
        <button class="btn ghost" id="undo">${icon("undo-2")} برگرداندن این فروش</button>`,
    });
    offLive = on("live:erp", (ev) => {
      if (ev.type === "product" && ev.woo_state) {
        const el = s.root.querySelector(`[data-site="${ev.id}"]`);
        if (el) el.innerHTML = String(ev.woo_state === "ok" ? html`<span class="badge ok">${icon("check")}سایت به‌روز شد</span>`
          : ev.woo_state === "error" ? html`<span class="badge bad">${icon("cloud-off")}خطای سایت</span>` : el.innerHTML);
      }
    });
    s.root.querySelector("#undo").onclick = async () => {
      await api(`/api/erp/sales/${sale.id}/void`, { method: "POST", body: { reason: "برگردانده شد بلافاصله بعد از ثبت" } });
      s.close();
      products = await api("/api/erp/products");
      drawTiles();
      toast("فروش برگردانده شد و موجودی برگشت");
    };
  }

  const offLive = on("live:erp", async (ev) => {
    if (ev.type === "product" && ev.stock !== undefined) {
      const p = products.find((x) => x.id === ev.id);
      if (p) { p.stock = ev.stock; drawTiles(); }
    }
    if (ev.type === "refresh" && ev.scope === "products") { products = await api("/api/erp/products", { quiet: true }); drawTiles(); }
  });
  const onResize = () => updateBar();
  window.addEventListener("resize", onResize);
  return () => { offLive(); io.disconnect(); document.removeEventListener("keydown", keyHandler); window.removeEventListener("resize", onResize); };
}
