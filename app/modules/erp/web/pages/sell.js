// Quick entry: one counter for both directions of stock.
//   فروش       tap products → adjust qty/price → channel and where the money went → done. Stock drops at once.
//   خرید کالا  (managers) tap what you bought, or type a new product → cost of each → supplier and the account that
//              paid → done. Stock rises and the average cost is updated.
// Linked products reach the site within seconds either way (two-way sync).
// Shelves make the list useful: best sellers, what is in stock, what needs restocking, categories, brands.
// Search + Enter adds the top match (works with a barcode scanner typing the SKU).
import { $, api, confirmBox, delegate, fa, html, icon, num, numWords, on, parseNum, sheet, storage, toast, toman } from "/static/js/kit.js";
import { bindChoices, bindDates, bindMoney, bindUploads, choiceChips, dateField, emptyState, formData, moneyField, selectOptions, thumb, uploadField } from "/static/js/kit.js";
import { accountOptions, CHANNEL_ICON, erp, isAdmin, refreshMe, stockBadge } from "../erp.js";

const norm = (s) => String(s || "").replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ").toLowerCase();
const MODES = {
  sell: { label: "فروش", ico: "shopping-bag", title: "سبد فروش", hint: "محصول را لمس کنید تا به سبد اضافه شود" },
  buy: { label: "خرید کالا", ico: "truck", title: "فاکتور خرید", hint: "کالایی که خریدید را انتخاب کنید یا نام کالای جدید را بنویسید" },
};
const needsStock = (p) => p.stock <= p.low_stock;

export async function render(view, params, { setTitle, query }) {
  const admin = isAdmin();
  let mode = admin && query?.get("mode") === "buy" ? "buy" : "sell";
  let products = await api("/api/erp/products");
  const carts = { sell: new Map(), buy: new Map() };      // key -> line; key is a product id or "new-N"
  let newKey = 1;
  let q = "", brand = "";
  const shelfOf = { sell: storage("erp.sell.shelf") || "all", buy: "need" };
  const channelOpts = (admin
    ? ["in_person", "instagram", "agent", "website", "other"]
    : ["agent", "in_person", "instagram", "other"]).map((c) => ({ value: c, label: erp.me.channels[c], icon: CHANNEL_ICON[c] }));
  const channelAccount = (c) => (erp.me.settings.channel_accounts || {})[c] || null;
  const fresh = {
    sell: () => ({ channel: admin ? "in_person" : "agent", date: erp.me.today, paid: true, account_id: admin ? channelAccount("in_person") : erp.me.user.account_id,
      seller_id: erp.me.user.id, discount: 0, shipping: 0, customer_name: "", customer_phone: "", note: "", receipt: "" }),
    buy: () => ({ date: erp.me.today, supplier: "", account_id: erp.me.user.account_id || null, shipping: 0, note: "", receipt: "" }),
  };
  const meta = { sell: fresh.sell(), buy: fresh.buy() };

  setTitle(admin ? "ثبت سریع" : "ثبت فروش", MODES[mode].hint);
  view.innerHTML = String(html`<div class="pos" data-mode="${mode}">
    ${admin ? html`<div class="pos-head">
      <div class="seg pos-mode" role="tablist">${Object.entries(MODES).map(([k, m]) => html`<button role="tab" data-mode="${k}">${icon(m.ico)}${m.label}</button>`)}</div>
    </div>` : ""}
    <div class="grid side-r">
      <section class="stack s12" style="min-width:0">
        <div class="card tight pos-search">
          <div class="row nowrap">
            <div class="input-wrap" style="flex:1;min-width:0">${icon("search")}<input enterkeyhint="go" class="input" id="q" autocomplete="off"
              placeholder="نام، برند یا کد محصول… (Enter = افزودن)" aria-label="جستجوی محصول"></div>
            <select class="select brand-pick" id="brand" aria-label="برند"></select>
          </div>
          <div class="chips scroll mt12" id="shelves"></div>
        </div>
        <div class="plist" id="tiles"></div>
      </section>
      <aside class="card ticket" id="cart"></aside>
    </div>
  </div>
  <button class="btn brand lg hidden cart-bar" id="cart-bar"></button>`);

  const root = $(".pos", view), tilesEl = $("#tiles", view), cartEl = $("#cart", view), shelvesEl = $("#shelves", view), bar = $("#cart-bar", view);
  const cart = () => carts[mode];
  const m = () => meta[mode];
  const byId = (id) => products.find((x) => x.id === id);

  // ---------------------------------------------------------------- shelves and the product list
  function shelves() {
    const cats = [...new Set(products.map((p) => p.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fa"));
    const base = mode === "buy"
      ? [{ key: "need", label: "نیاز به خرید", ico: "triangle-alert", test: needsStock },
         { key: "all", label: "همه" },
         { key: "top", label: "پرفروش", ico: "flame", test: (p) => (p.sold_30 || 0) > 0 }]
      : [{ key: "all", label: "همه" },
         { key: "top", label: "پرفروش ۳۰ روز", ico: "flame", test: (p) => (p.sold_30 || 0) > 0 },
         { key: "instock", label: "موجود", ico: "circle-check", test: (p) => p.stock > 0 }];
    return [...base, ...cats.map((c) => ({ key: `cat:${c}`, label: c, test: (p) => p.category === c }))];
  }
  function drawShelves() {
    const list = shelves();
    if (!list.some((s) => s.key === shelfOf[mode])) shelfOf[mode] = list[0].key;
    shelvesEl.innerHTML = String(html`${list.map((s) => {
      const n = s.test ? products.filter(s.test).length : products.length;
      return html`<button class="chip ${shelfOf[mode] === s.key ? "on" : ""}" data-shelf="${s.key}">${s.ico ? icon(s.ico, "sm") : ""}${s.label}
        ${s.key !== "all" ? html`<span class="c-count">${fa(n)}</span>` : ""}</button>`;
    })}`);
    const brands = [...new Set(products.map((p) => p.brand).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fa"));
    const sel = $("#brand", view);
    sel.innerHTML = String(selectOptions(brands.map((b) => ({ value: b, label: b })), brand, "همه برندها"));
    sel.classList.toggle("hidden", brands.length < 2);
  }
  function filtered() {
    const shelf = shelves().find((s) => s.key === shelfOf[mode]);
    const terms = norm(q).split(/\s+/).filter(Boolean);
    const list = products
      .filter((p) => !terms.length ? (!shelf?.test || shelf.test(p)) : true)          // searching looks everywhere
      .filter((p) => !brand || p.brand === brand)
      .filter((p) => !terms.length || terms.every((t) => norm(`${p.name} ${p.brand || ""} ${p.sku || ""}`).includes(t)));
    const exact = (p) => (terms.length && norm(p.sku) === norm(q.trim()) ? 1 : 0);
    if (mode === "buy") {
      return list.sort((a, b) => exact(b) - exact(a) || (a.stock - a.low_stock) - (b.stock - b.low_stock) || (b.sold_30 || 0) - (a.sold_30 || 0) || a.name.localeCompare(b.name, "fa"));
    }
    if (shelfOf.sell === "top" && !terms.length) return list.sort((a, b) => (b.sold_30 || 0) - (a.sold_30 || 0));
    return list.sort((a, b) => exact(b) - exact(a) || (b.stock > 0) - (a.stock > 0) || (b.sold_30 || 0) - (a.sold_30 || 0) || a.name.localeCompare(b.name, "fa"));
  }
  function card(p) {
    const inCart = cart().get(p.id)?.qty || 0;
    const left = p.stock - (mode === "sell" ? inCart : 0);
    const out = mode === "sell" && left <= 0 && !(p.woo_state === "nocount" && p.woo_in_stock);
    const meta2 = [p.brand, p.sku].filter(Boolean).join(" · ");
    return html`<button class="pcard ${out ? "out" : ""} ${inCart ? "on" : ""}" data-add="${p.id}" title="${p.name}">
      ${inCart ? html`<span class="pc-qty">${fa(inCart)}</span>` : ""}
      <span class="pc-img">${p.image ? html`<img src="${p.image}" alt="" loading="lazy" referrerpolicy="no-referrer">` : icon("package")}</span>
      <span class="pc-body">
        <span class="pc-name">${p.name}</span>
        ${meta2 ? html`<span class="pc-meta">${meta2}</span>` : ""}
        <span class="pc-foot">${mode === "buy"
          ? html`<span class="pc-price">${p.avg_cost ? html`${num(p.avg_cost)} <small>خرید</small>` : html`<small>قیمت خرید ندارد</small>`}</span>
                 <span class="badge ${p.stock <= 0 ? "bad" : needsStock(p) ? "warn" : ""}">موجودی ${fa(p.stock)}</span>`
          : html`<span class="pc-price">${num(p.price)}</span>${stockBadge({ ...p, stock: left })}`}</span>
      </span>
    </button>`;
  }
  function drawTiles() {
    const list = filtered();
    const typed = q.trim();
    const addNew = mode === "buy" && typed && !list.some((p) => norm(p.name) === norm(typed));
    tilesEl.innerHTML = list.length || addNew ? String(html`
      ${addNew ? html`<button class="pcard new" data-new="1"><span class="pc-img">${icon("package-plus")}</span>
        <span class="pc-body"><span class="pc-name">کالای جدید: «${typed}»</span><span class="pc-meta">به انبار اضافه و در این خرید ثبت می‌شود</span></span></button>` : ""}
      ${list.slice(0, 240).map(card)}`)
      : String(emptyState("search", "محصولی پیدا نشد", typed ? "عبارت دیگری را امتحان کنید." : mode === "buy" ? "هیچ محصولی کم نیامده؛ «همه» را ببینید." : "هنوز محصولی ثبت نشده."));
  }

  // ---------------------------------------------------------------- the ticket (cart)
  function lines() {
    return [...cart().entries()].map(([key, l]) => ({ key, ...l, p: typeof key === "number" ? byId(key) : null }))
      .filter((l) => l.p || l.isNew);
  }
  function totals() {
    let subtotal = 0, count = 0;
    cart().forEach((l) => { subtotal += l.qty * (mode === "buy" ? l.unit_cost : l.unit_price); count += l.qty; });
    const total = mode === "buy" ? subtotal + (m().shipping || 0) : Math.max(0, subtotal - (m().discount || 0) + (m().shipping || 0));
    return { subtotal, count, total };
  }
  function lineHtml(l) {
    const price = mode === "buy" ? l.unit_cost : l.unit_price;
    const short = mode === "sell" && l.p && l.p.stock - l.qty < 0 && !(l.p.woo_state === "nocount");
    return html`<div class="tline" data-line="${l.key}">
      ${l.p ? thumb(l.p, "sm") : html`<span class="thumb sm">${icon("package-plus", "sm")}</span>`}
      <div class="tl-main">
        ${l.isNew ? html`<input class="tl-input" data-field="name" value="${l.name}" placeholder="نام کالای جدید" aria-label="نام کالای جدید">`
          : html`<div class="tl-name">${l.p.name}</div>`}
        ${short ? html`<div class="tiny bad-ink">در انبار فقط ${fa(Math.max(0, l.p.stock))} عدد ثبت شده</div>` : ""}
        ${l.isNew ? html`<div class="tl-new">
          <select class="tl-input" data-field="category" aria-label="دسته">${selectOptions((erp.me.settings.product_categories || []).map((c) => ({ value: c, label: c })), l.category, "دسته")}</select>
          <input class="tl-input money" data-field="price" data-money inputmode="numeric" value="${l.price ? num(l.price) : ""}" placeholder="قیمت فروش" aria-label="قیمت فروش">
        </div>` : ""}
      </div>
      <b class="tl-total num" data-ltotal="${l.key}">${num(l.qty * (price || 0))}</b>
      <div class="tl-ctrl">
        <label class="tl-price"><span>${mode === "buy" ? "قیمت خرید هر عدد" : "قیمت هر عدد"}</span>
          <input class="tl-input money" data-field="${mode === "buy" ? "unit_cost" : "unit_price"}" data-money inputmode="numeric" value="${price ? num(price) : ""}" placeholder="۰"></label>
        <div class="stepper"><button data-inc="${l.key}" aria-label="یکی بیشتر">${icon("plus", "sm")}</button>
          <input value="${fa(l.qty)}" data-qty="${l.key}" inputmode="numeric" aria-label="تعداد">
          <button data-dec="${l.key}" aria-label="یکی کمتر">${icon(l.qty > 1 ? "minus" : "trash-2", "sm")}</button></div>
      </div>
    </div>`;
  }
  function sellMeta(x) {
    return html`<div class="ticket-sec">
        <div class="sec-label">کانال فروش</div>
        ${choiceChips("channel", channelOpts, x.channel, { cls: "tight" })}
        <div class="row nowrap">
          ${admin ? html`<select class="select sm" name="account_id" style="flex:1;min-width:0" aria-label="پول به کدام حساب رفت">${accountOptions(x.account_id)}</select>` : ""}
          <label class="check small"><span class="switch"><input type="checkbox" name="paid" ${x.paid ? "checked" : ""}><span></span></span>${x.paid ? "پرداخت شد" : "نسیه"}</label>
        </div>
      </div>
      <details class="ticket-more" ${x.discount || x.shipping || x.note || x.customer_name || x.receipt || (admin && x.date !== erp.me.today) ? "open" : ""}>
        <summary>${icon("plus", "sm")} مشتری، تخفیف، ارسال، رسید، تاریخ و یادداشت</summary>
        <div class="stack s12 mt12">
          <div class="form-grid">
            <div class="field"><label>نام مشتری</label><input class="input sm" name="customer_name" value="${x.customer_name}" placeholder="اختیاری"></div>
            <div class="field"><label>تلفن</label><input class="input sm ltr" name="customer_phone" value="${x.customer_phone}" inputmode="tel" placeholder="اختیاری"></div>
            ${moneyField({ name: "discount", label: "تخفیف کل", value: x.discount || "" })}
            ${moneyField({ name: "shipping", label: "ارسال (از مشتری)", value: x.shipping || "" })}
            ${admin ? html`${dateField({ name: "date", label: "تاریخ", value: x.date })}
              <div class="field"><label>فروشنده</label><select class="select sm" name="seller_id">
                ${erp.me.users.filter((u) => u.active).map((u) => html`<option value="${u.id}" ${u.id === x.seller_id ? "selected" : ""}>${u.name}</option>`)}
              </select></div>` : ""}
          </div>
          <div class="field"><label>یادداشت</label><input class="input sm" name="note" value="${x.note}" placeholder="مثلاً: ارسال با پیک"></div>
          ${uploadField({ name: "receipt", label: "رسید / فیش واریز (اختیاری)", value: x.receipt })}
        </div>
      </details>`;
  }
  function buyMeta(x) {
    return html`<div class="ticket-sec">
        <div class="field"><label>از کجا خریدید؟</label><input class="input sm" name="supplier" list="sup-list" value="${x.supplier}" placeholder="تأمین‌کننده، بازار، فروشگاه…">
          <datalist id="sup-list">${erp.me.suppliers.map((s) => html`<option value="${s}">`)}</datalist></div>
        <div class="field"><label>پول از کدام حساب رفت؟</label><select class="select sm" name="account_id">${accountOptions(x.account_id, { includeEmpty: "جداگانه ثبت می‌کنم" })}</select></div>
      </div>
      <details class="ticket-more" ${x.shipping || x.note || x.receipt || x.date !== erp.me.today ? "open" : ""}>
        <summary>${icon("plus", "sm")} هزینه حمل، تاریخ، عکس فاکتور و یادداشت</summary>
        <div class="stack s12 mt12">
          ${moneyField({ name: "shipping", label: "حمل / پیک (بین کالاها تقسیم می‌شود)", value: x.shipping || "" })}
          ${dateField({ name: "date", label: "تاریخ خرید", value: x.date })}
          ${uploadField({ name: "receipt", label: "عکس فاکتور", value: x.receipt })}
          <div class="field"><label>یادداشت</label><input class="input sm" name="note" value="${x.note}"></div>
        </div>
      </details>`;
  }
  function drawCart() {
    const t = totals(), ls = lines(), x = m(), M = MODES[mode];
    cartEl.innerHTML = String(html`
      <div class="ticket-head"><h2>${icon(mode === "buy" ? "truck" : "shopping-cart")} ${M.title}</h2>
        ${t.count ? html`<span class="badge primary">${fa(t.count)} عدد</span>` : ""}<span class="spacer"></span>
        ${cart().size ? html`<button class="btn xs ghost" data-clear>${icon("trash-2", "sm")} خالی</button>` : ""}</div>
      <div class="ticket-lines">${ls.length ? ls.map(lineHtml)
        : html`<div class="ticket-empty">${icon(mode === "buy" ? "package-plus" : "shopping-bag", "lg")}<p class="small">${mode === "buy" ? "کالاهای خریده‌شده را از فهرست انتخاب کنید" : "محصول را از فهرست انتخاب کنید"}</p></div>`}</div>
      <form class="stack s12" id="meta" onsubmit="return false">${mode === "buy" ? buyMeta(x) : sellMeta(x)}</form>
      <div class="totals" id="totals">${totalsHtml(t)}</div>
      <button class="btn ${mode === "buy" ? "primary" : "brand"} lg block" data-submit ${cart().size ? "" : "disabled"}>${icon("check")} ${mode === "buy" ? "ثبت خرید و افزودن به انبار" : "ثبت فروش"}</button>`);
    updateBar(t);
  }
  function totalsHtml(t) {
    const x = m();
    return html`<div class="t-row"><span class="muted">جمع ${fa(t.count)} عدد</span><span class="num">${num(t.subtotal)}</span></div>
      ${mode === "sell" && x.discount ? html`<div class="t-row"><span class="muted">تخفیف</span><span class="num bad-ink">−${num(x.discount)}</span></div>` : ""}
      ${x.shipping ? html`<div class="t-row"><span class="muted">${mode === "buy" ? "حمل" : "ارسال"}</span><span class="num">+${num(x.shipping)}</span></div>` : ""}
      <div class="t-row t-grand"><span>${mode === "buy" ? "جمع خرید" : "مبلغ نهایی"}</span><span class="num">${num(t.total)} <small class="muted">تومان</small></span></div>
      ${t.total ? html`<div class="tiny muted">${numWords(t.total)} تومان</div>` : ""}`;
  }
  function refreshTotals() {
    const t = totals();
    $("#totals", cartEl).innerHTML = String(totalsHtml(t));
    const head = cartEl.querySelector(".ticket-head .badge");
    if (head) head.textContent = `${fa(t.count)} عدد`;
    updateBar(t);
  }
  let cartVisible = false;
  function updateBar(t = totals()) {
    bar.className = `btn ${mode === "buy" ? "primary" : "brand"} lg cart-bar ${!cart().size || window.innerWidth > 1180 || cartVisible ? "hidden" : ""}`;
    bar.innerHTML = String(html`${icon(mode === "buy" ? "truck" : "shopping-cart")} ${fa(t.count)} عدد، ${num(t.total)} تومان — ادامه`);
  }
  const io = new IntersectionObserver((entries) => { cartVisible = entries[0].isIntersecting; updateBar(); });
  io.observe(cartEl);

  function captureMeta() {
    const form = $("#meta", cartEl);
    if (!form) return;
    const f = formData(form), x = m();
    if (mode === "sell") {
      Object.assign(x, { channel: f.channel || x.channel, paid: !!f.paid, customer_name: f.customer_name || "", customer_phone: f.customer_phone || "",
        note: f.note || "", discount: f.discount || 0, shipping: f.shipping || 0, receipt: f.receipt || "" });
      if (admin) Object.assign(x, { account_id: Number(f.account_id) || null, date: f.date || x.date, seller_id: Number(f.seller_id) || x.seller_id });
    } else {
      Object.assign(x, { supplier: f.supplier || "", account_id: Number(f.account_id) || null, shipping: f.shipping || 0, date: f.date || x.date,
        note: f.note || "", receipt: f.receipt || "" });
    }
  }
  function add(key, by = 1) {
    captureMeta();
    const p = typeof key === "number" ? byId(key) : null;
    let line = cart().get(key);
    if (!line) {
      if (!p) return;
      line = mode === "buy" ? { qty: 0, unit_cost: Math.round(p.avg_cost) || 0 } : { qty: 0, unit_price: p.price };
    }
    line.qty += by;
    if (line.qty <= 0) cart().delete(key);
    else cart().set(key, line);
    if (mode === "sell" && by > 0 && p && p.stock - line.qty < 0 && p.woo_state !== "nocount") toast(`از «${p.name}» فقط ${fa(Math.max(0, p.stock))} عدد در انبار ثبت شده`, "info");
    drawTiles();
    drawCart();
    if (by > 0) tilesEl.querySelector(`[data-add="${key}"] .pc-qty`)?.classList.add("bump");
  }
  function addNew(name) {
    captureMeta();
    const key = `new-${newKey++}`;
    cart().set(key, { isNew: true, name: name.trim(), qty: 1, unit_cost: 0, price: 0, category: "" });
    q = "";
    $("#q", view).value = "";
    drawTiles(); drawCart();
    cartEl.querySelector(`[data-line="${key}"] [data-field="unit_cost"]`)?.focus();
  }
  function setMode(next) {
    captureMeta();
    mode = next;
    root.dataset.mode = mode;
    view.querySelectorAll(".pos-mode [data-mode]").forEach((b) => {
      b.classList.toggle("on", b.dataset.mode === mode);
      b.setAttribute("aria-selected", String(b.dataset.mode === mode));
    });
    setTitle(admin ? "ثبت سریع" : "ثبت فروش", MODES[mode].hint);
    history.replaceState(null, "", mode === "buy" ? "#/erp/sell?mode=buy" : "#/erp/sell");
    drawShelves(); drawTiles(); drawCart();
  }

  // ---------------------------------------------------------------- events
  const lineKey = (el) => { const k = el.closest("[data-line]")?.dataset.line ?? el.dataset.qty ?? el.dataset.inc ?? el.dataset.dec; return /^\d+$/.test(k) ? Number(k) : k; };
  delegate(view, "click", ".pos-mode [data-mode]", (e, el) => setMode(el.dataset.mode));
  $("#q", view).addEventListener("input", (e) => { q = e.target.value; drawTiles(); });
  $("#q", view).addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const first = filtered()[0];
    if (q.trim() && first) { add(first.id); e.target.select(); }
    else if (mode === "buy" && q.trim()) addNew(q);
  });
  $("#brand", view).addEventListener("change", (e) => { brand = e.target.value; drawTiles(); });
  delegate(shelvesEl, "click", "[data-shelf]", (e, el) => {
    shelfOf[mode] = el.dataset.shelf;
    if (mode === "sell") storage("erp.sell.shelf", shelfOf.sell);
    drawShelves(); drawTiles();
  });
  delegate(tilesEl, "click", "[data-add]", (e, el) => add(Number(el.dataset.add)));
  delegate(tilesEl, "click", "[data-new]", () => addNew(q));
  delegate(cartEl, "click", "[data-inc]", (e, el) => add(lineKey(el), 1));
  delegate(cartEl, "click", "[data-dec]", (e, el) => add(lineKey(el), -1));
  delegate(cartEl, "click", "[data-clear]", () => { cart().clear(); drawTiles(); drawCart(); });
  delegate(cartEl, "change", "[data-qty]", (e, el) => {
    const key = lineKey(el), v = Math.round(parseNum(el.value));
    captureMeta();
    if (v <= 0) cart().delete(key); else cart().get(key).qty = v;
    drawTiles(); drawCart();
  });
  // typing a price or a new product's details: update the numbers without redrawing (the field keeps focus)
  delegate(cartEl, "input", "[data-field]", (e, el) => {
    const key = lineKey(el), line = cart().get(key);
    if (!line) return;
    const f = el.dataset.field;
    line[f] = ["unit_price", "unit_cost", "price"].includes(f) ? Math.round(parseNum(el.value)) || 0 : el.value;
    const lt = cartEl.querySelector(`[data-ltotal="${key}"]`);
    if (lt) lt.textContent = num(line.qty * ((mode === "buy" ? line.unit_cost : line.unit_price) || 0));
    refreshTotals();
  });
  delegate(cartEl, "change", "input[name=paid]", () => { captureMeta(); drawCart(); });
  delegate(cartEl, "input", "#meta input[data-money]", () => { captureMeta(); refreshTotals(); });
  delegate(cartEl, "click", "[data-submit]", () => (mode === "buy" ? submitBuy() : submitSell()));
  bindMoney(cartEl);
  bindDates(cartEl);
  bindUploads(cartEl);
  bindChoices(cartEl, (name, value) => {
    if (name === "channel" && admin && mode === "sell") {
      captureMeta();
      meta.sell.channel = value;
      if (channelAccount(value)) meta.sell.account_id = channelAccount(value);
      drawCart();
    }
  });
  bar.addEventListener("click", () => cartEl.scrollIntoView({ behavior: "smooth", block: "start" }));
  const keyHandler = (e) => {
    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) { e.preventDefault(); $("#q", view)?.focus(); }
  };
  document.addEventListener("keydown", keyHandler);

  // ---------------------------------------------------------------- submit
  async function busy(fn) {
    const btn = cartEl.querySelector("[data-submit]");
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = String(html`<span class="spin"></span> در حال ثبت…`);
    try { await fn(); } catch (e) { btn.disabled = false; btn.innerHTML = label; }
  }
  function submitSell() {
    captureMeta();
    if (!cart().size) return;
    return busy(async () => {
      const body = { ...meta.sell, items: [...cart().entries()].map(([product_id, l]) => ({ product_id, qty: l.qty, unit_price: l.unit_price })) };
      const res = await api("/api/erp/sales", { method: "POST", body });
      const detail = await api(`/api/erp/sales/${res.id}`);
      cart().clear();
      meta.sell = { ...fresh.sell(), channel: meta.sell.channel, account_id: meta.sell.account_id, date: meta.sell.date, seller_id: meta.sell.seller_id };
      products = await api("/api/erp/products");
      drawShelves(); drawTiles(); drawCart();
      showSold(detail);
    });
  }
  function submitBuy() {
    captureMeta();
    const items = [];
    for (const [key, l] of cart()) {
      if (l.isNew && !(l.name || "").trim()) return toast("نام کالای جدید را بنویسید", "error");
      items.push(l.isNew ? { qty: l.qty, unit_cost: l.unit_cost || 0, new_product: { name: l.name.trim(), category: l.category || null, price: l.price || 0 } }
        : { product_id: key, qty: l.qty, unit_cost: l.unit_cost || 0 });
    }
    if (!items.length) return;
    return busy(async () => {
      if (items.some((i) => !i.unit_cost) && !(await confirmBox("قیمت خرید بعضی کالاها خالی است؛ سود فروششان درست حساب نمی‌شود. همین‌طور ثبت شود؟", { okText: "ثبت کن" }))) {
        throw new Error("cancelled");
      }
      const x = meta.buy;
      const res = await api("/api/erp/purchases", { method: "POST", body: { ...x, account_id: x.account_id || null, items } });
      const bought = lines();
      cart().clear();
      meta.buy = { ...fresh.buy(), account_id: x.account_id, supplier: x.supplier, date: x.date };
      products = await api("/api/erp/products");
      refreshMe();
      drawShelves(); drawTiles(); drawCart();
      showBought(res.id, bought, x);
    });
  }

  function siteBadge(p) {
    if (!p?.woo_id || !erp.me.site.configured) return html`<span class="badge">به سایت وصل نیست</span>`;
    return erp.me.site.started ? html`<span class="badge info">${icon("loader-circle")}سایت…</span>` : html`<span class="badge warn">همگام‌سازی شروع نشده</span>`;
  }
  function liveSite(s) {
    return on("live:erp", (ev) => {
      if (ev.type !== "product" || !ev.woo_state) return;
      const el = s.root.querySelector(`[data-site="${ev.id}"]`);
      if (el && ev.woo_state === "ok") el.innerHTML = String(html`<span class="badge ok">${icon("check")}سایت به‌روز شد</span>`);
      if (el && ev.woo_state === "error") el.innerHTML = String(html`<span class="badge bad">${icon("cloud-off")}خطای سایت</span>`);
    });
  }
  function showSold({ sale, items }) {
    let off = () => {};
    const s = sheet({
      onClose: () => off(),
      title: "فروش ثبت شد",
      body: html`<div class="success-burst">${icon("check")}</div>
        <p style="text-align:center" class="bold">${sale.code}، ${toman(sale.total)}</p>
        <div class="list mt16">${items.map((it) => {
          const p = byId(it.product_id);
          return html`<div class="list-item">${thumb(p || {}, "sm")}
            <div class="grow"><div class="title small">${fa(it.qty)}× ${it.name}</div>
              <div class="sub">${!p ? "" : p.stock <= 0 ? html`<b class="bad-ink">تمام شد</b>` : html`مانده در انبار: ${fa(p.stock)}`}</div></div>
            <span data-site="${it.product_id}">${siteBadge(p)}</span></div>`;
        })}</div>`,
      foot: html`<button class="btn primary" data-close>${icon("plus")} فروش بعدی</button>
        <button class="btn ghost" id="undo">${icon("undo-2")} برگرداندن این فروش</button>`,
    });
    off = liveSite(s);
    s.root.querySelector("#undo").onclick = async () => {
      await api(`/api/erp/sales/${sale.id}/void`, { method: "POST", body: { reason: "برگردانده شد بلافاصله بعد از ثبت" } });
      s.close();
      products = await api("/api/erp/products");
      drawTiles();
      toast("فروش برگردانده شد و موجودی برگشت");
    };
  }
  function showBought(id, bought, x) {
    let off = () => {};
    const total = bought.reduce((t, l) => t + l.qty * (l.unit_cost || 0), 0) + (x.shipping || 0);
    const s = sheet({
      onClose: () => off(),
      title: "خرید ثبت شد",
      body: html`<div class="success-burst">${icon("check")}</div>
        <p style="text-align:center" class="bold">${toman(total)}${x.supplier ? ` — ${x.supplier}` : ""}</p>
        <div class="list mt16">${bought.map((l) => {
          const p = l.p ? byId(l.p.id) : products.find((y) => y.name === l.name);
          return html`<div class="list-item">${thumb(p || {}, "sm")}
            <div class="grow"><div class="title small">+${fa(l.qty)} ${p?.name || l.name}</div>
              <div class="sub">${p ? html`موجودی جدید: <b>${fa(p.stock)}</b>` : ""}${l.isNew ? " — محصول جدید" : ""}</div></div>
            <span data-site="${p?.id}">${siteBadge(p)}</span></div>`;
        })}</div>`,
      foot: html`<button class="btn primary" data-close>${icon("plus")} خرید بعدی</button>
        <a class="btn ghost" href="#/erp/purchases/${id}" data-close>${icon("receipt")} مشاهده خرید</a>`,
    });
    off = liveSite(s);
  }

  // ---------------------------------------------------------------- live updates
  const offLive = on("live:erp", async (ev) => {
    if (ev.type === "product" && ev.stock !== undefined) {
      const p = byId(ev.id);
      if (p) { p.stock = ev.stock; drawTiles(); }
    }
    if (ev.type === "refresh" && ev.scope === "products") { products = await api("/api/erp/products", { quiet: true }); drawShelves(); drawTiles(); }
  });
  const onResize = () => updateBar();
  window.addEventListener("resize", onResize);

  if (admin) setMode(mode); else { drawShelves(); drawTiles(); drawCart(); }
  if (window.innerWidth > 900) $("#q", view).focus();
  return () => { offLive(); io.disconnect(); document.removeEventListener("keydown", keyHandler); window.removeEventListener("resize", onResize); };
}
