// Studio: compose a video or image request, compare up to three models, confirm the cost, watch results live.
import { $, $$, api, emptyState, fa, html, icon, isOwner, raw, sheet, storage, toast } from "/static/js/kit.js";
import {
  M, TERMINAL, bindCardActions, canCreate, capabilityTags, common, commonEnum, commonRange, describePricing, elapsed,
  ensureImagePricing, loadConfig, loadModels, onMedia, pricingEntries, provAvatar, resultCard, supports, usd,
} from "../media.js";

const MAX_COMPARE = 3;
const MAX_IMAGES = 10;
const QUALITY = { auto: "خودکار", low: "کم", medium: "متوسط", high: "زیاد" };
const BACKGROUND = { auto: "خودکار", transparent: "شفاف", opaque: "مات" };
const FORMAT = { png: "PNG", jpeg: "JPEG", webp: "WebP", svg: "SVG" };
const IDEAS = [
  { label: "رژ لب روی سنگ تراورتن", ico: "sparkles", prompt: "A glossy rose lip tint standing on blush travertine, dewy highlights, coral-to-orchid sunset glow, slow elegant camera orbit, premium beauty campaign, photorealistic." },
  { label: "ماکرو ریمل", ico: "eye", prompt: "Macro view of rich mascara brushing through lashes, clean cream background, soft indigo shadows, graceful slow motion, precise premium cosmetic commercial." },
  { label: "رژگونه میان گلبرگ‌ها", ico: "heart", prompt: "A luminous blush compact surrounded by translucent pink petals, golden-hour warmth fading into blue-hour cool, soft bokeh, refined beauty editorial." },
];

const prefs = () => storage("media-composer") || {};
const savePrefs = (p) => storage("media-composer", p);

export async function render(view, params, { setTitle, query }) {
  setTitle("استودیو محتوا", "ساخت ویدیو و تصویر تبلیغاتی با هوش مصنوعی");
  await loadConfig();
  const saved = prefs();
  const st = {
    mode: saved.mode === "image" ? "image" : "video",
    compare: !!saved.compare,
    imageMode: ["first_frame", "last_frame", "reference"].includes(saved.imageMode) ? saved.imageMode : "reference",
    selection: { video: saved.selection?.video || [], image: saved.selection?.image || [] },
    batch: [],
    submitting: false,
  };
  const persist = () => savePrefs({ ...prefs(), mode: st.mode, compare: st.compare, imageMode: st.imageMode, selection: st.selection,
    ...($("#prompt", composer) ? { [st.mode]: readSettings() } : {}) });

  view.innerHTML = String(html`<div class="studio">
    <section class="card composer" id="composer"></section>
    <div class="stack" id="stage"></div>
  </div>`);
  const composer = $("#composer", view), stage = $("#stage", view);

  // ------------------------------------------------------------ composer
  const models = () => M.models[st.mode];
  const selected = () => st.selection[st.mode].map((id) => models().find((m) => m.id === id)).filter(Boolean);

  function drawComposer() {
    if (!M.config.configured) {
      composer.innerHTML = String(html`<div class="stack s12">
        <h2>${icon("wand-sparkles")} استودیو هنوز وصل نیست</h2>
        <p class="small muted" style="line-height:2">برای ساخت ویدیو و تصویر، کلید API سرویس OpenRouter لازم است. کلید فقط روی سرور نگه داشته می‌شود و هیچ‌وقت به مرورگر نمی‌رسد.</p>
        ${isOwner() ? html`<a class="btn primary" href="#/media/settings">${icon("key-round")} تنظیم کلید OpenRouter</a>` : html`<p class="small">از مدیر بخواهید کلید را در تنظیمات استودیو وارد کند.</p>`}
      </div>`);
      return;
    }
    if (!canCreate()) {
      composer.innerHTML = String(html`<div class="stack s12"><h2>${icon("eye")} فقط مشاهده</h2>
        <p class="small muted" style="line-height:2">دسترسی شما به استودیو «فقط مشاهده» است؛ ساخت محتوا هزینه دارد و فقط «سازنده‌ها» می‌توانند. کتابخانه را ببینید.</p>
        <a class="btn soft" href="#/media/library">${icon("library")} کتابخانه</a></div>`);
      return;
    }
    const image = st.mode === "image";
    composer.innerHTML = String(html`
      <div class="seg" role="group" aria-label="نوع خروجی">
        <button class="${!image ? "on" : ""}" data-mode="video">${icon("video", "sm")} ویدیو</button>
        <button class="${image ? "on" : ""}" data-mode="image">${icon("image", "sm")} تصویر</button>
      </div>
      <div>
        <div class="c-label"><span>مدل</span><label class="check small"><span class="switch" style="transform:scale(.8)"><input type="checkbox" id="compare" ${st.compare ? raw("checked") : ""}><span></span></span>مقایسه تا ۳ مدل</label></div>
        <button class="model-trigger" id="pick">${pickerFace()}</button>
        <div class="sel-models" id="selChips"></div>
        <p class="small warn-ink mt8 hidden" id="compat"></p>
      </div>
      <div>
        <div class="c-label"><label for="prompt">متن درخواست (پرامپت)</label><button class="btn xs ghost" id="ideasBtn">${icon("lightbulb", "sm")} ایده</button></div>
        <div class="prompt-box"><textarea class="textarea" id="prompt" dir="auto" maxlength="50000"
          placeholder="${image ? "محصول، ترکیب‌بندی، نور، رنگ، بافت و سبک را توصیف کنید… (انگلیسی نتیجه بهتری می‌دهد)" : "محصول، بافت، حرکت، دوربین، نور و حس را توصیف کنید… (انگلیسی نتیجه بهتری می‌دهد)"}"></textarea>
          <span class="prompt-count" id="pcount">۰</span></div>
        <div class="ideas hidden" id="ideas">${IDEAS.map((i) => html`<button class="idea" data-prompt="${i.prompt}"><b>${i.label}</b><span class="ltr" style="display:block;text-align:left">${i.prompt}</span></button>`)}</div>
      </div>
      <div>
        <div class="c-label"><span>${image ? "تصویر مرجع" : "تصویر شروع / مرجع"} <span class="muted">(اختیاری)</span></span>
          <button class="btn xs ghost" id="refBtn">${icon("image", "sm")} افزودن</button></div>
        <div class="stack s8 hidden" id="refBox">
          ${!image ? html`<div class="chips" id="frameTabs">
            <button class="chip" data-frame="reference">مرجع سبک</button><button class="chip" data-frame="first_frame">فریم اول</button><button class="chip" data-frame="last_frame">فریم آخر</button></div>` : ""}
          <input class="input ltr" id="refUrl" placeholder="https://… (آدرس عمومی عکس)">
          <p class="tiny muted" id="refNote"></p>
        </div>
      </div>
      <div>
        <div class="c-label"><span>تنظیمات خروجی</span><span class="badge" id="capBadge"></span></div>
        <div class="settings-grid">
          <div class="field"><label>نسبت تصویر</label><select class="select sm" id="aspect"></select></div>
          ${!image ? html`<div class="field"><label>مدت</label><select class="select sm" id="duration"></select></div>`
            : html`<div class="field"><label>تعداد</label><select class="select sm" id="count"></select></div>`}
          <div class="field"><label>کیفیت / ابعاد</label><select class="select sm" id="resolution"></select></div>
          ${image ? html`<div class="field"><label>فرمت</label><select class="select sm" id="format"></select></div>
            <div class="field"><label>کیفیت رندر</label><select class="select sm" id="quality"></select></div>
            <div class="field"><label>پس‌زمینه</label><select class="select sm" id="background"></select></div>`
            : html`<div class="field"><label>صدا</label><label class="check small" style="height:38px"><span class="switch"><input type="checkbox" id="audio"><span></span></span><span id="audioText">صدای اصلی</span></label></div>`}
        </div>
      </div>
      <details class="adv"><summary>${icon("sliders-horizontal", "sm")} پیشرفته</summary>
        <div class="stack s12">
          <div class="field"><label>Seed (برای تکرارپذیری)</label><input class="input sm ltr" id="seed" inputmode="numeric" placeholder="خالی = تصادفی"></div>
          <div class="field"><label>گزینه‌های ارائه‌دهنده (JSON)</label><textarea class="textarea ltr" id="provider" rows="3" placeholder='{"options": {}}' style="min-height:70px;font-family:ui-monospace,monospace;font-size:12px"></textarea>
            <div class="hint" id="passHint"></div></div>
        </div></details>
      <div class="gen-foot">
        <div class="gen-meta"><span id="outCount"></span><span id="priceHint"></span></div>
        <button class="btn brand lg block" id="generate">${icon("wand-sparkles")} <span id="genLabel">بساز</span></button>
        <div class="gen-meta"><span>هزینه این ماه: ${usd(M.config.month_spend) || "$0"}${M.config.monthly_limit_usd ? ` از ${usd(M.config.monthly_limit_usd)}` : ""}</span>
          <a class="small" href="#/media/library">کتابخانه ←</a></div>
      </div>`);
    const s = prefs()[st.mode] || {};
    if (s.prompt) $("#prompt", composer).value = s.prompt;
    syncCapabilities(true);
    updateFooter();
  }

  function pickerFace() {
    const sel = selected();
    if (!models().length) return html`<span class="prov skeleton">··</span><span class="mt-copy"><strong>${M.loaded.has(st.mode) ? "مدلی برنگشت" : "در حال خواندن مدل‌ها…"}</strong><small>OpenRouter</small></span>${icon("chevron-down", "sm")}`;
    if (!sel.length) return html`<span class="prov">?</span><span class="mt-copy"><strong>یک مدل انتخاب کنید</strong><small>${fa(models().length)} مدل در دسترس</small></span>${icon("chevron-down", "sm")}`;
    if (sel.length > 1) return html`<span class="prov" style="--h:250">${fa(sel.length)}</span><span class="mt-copy"><strong>${fa(sel.length)} مدل برای مقایسه</strong><small>تنظیمات مشترک</small></span>${icon("chevron-down", "sm")}`;
    return html`${provAvatar(sel[0].id)}<span class="mt-copy"><strong>${sel[0].name || sel[0].id}</strong><small>${sel[0].id}</small></span>${icon("chevron-down", "sm")}`;
  }

  function fill(id, values, { current, preferred, label = (v) => v } = {}) {
    const el = $(`#${id}`, composer);
    if (!el) return;
    const prev = current ?? el.value;
    el.innerHTML = String(html`<option value="">پیش‌فرض مدل</option>${values.map((v) => html`<option value="${v}">${label(v)}</option>`)}`);
    const vs = values.map(String);
    el.value = vs.includes(String(prev)) ? String(prev) : preferred && vs.includes(String(preferred)) ? String(preferred) : vs[0] || "";
    el.disabled = !values.length;
  }

  function syncCapabilities(useSaved = false) {
    const sel = selected();
    const saved = useSaved ? prefs()[st.mode] || {} : {};
    $("#pick", composer).innerHTML = String(pickerFace());
    $("#selChips", composer).innerHTML = st.compare && sel.length > 1 ? String(html`${sel.map((m) => html`<span class="chip on" style="height:30px">${m.name || m.id}
      <button class="btn icon xs ghost" data-unsel="${m.id}" aria-label="حذف">${icon("x", "sm")}</button></span>`)}`) : "";
    const missing = [];
    if (st.mode === "image") {
      const ratios = commonEnum(sel, "aspect_ratio"), res = commonEnum(sel, "resolution");
      fill("aspect", ratios, { current: saved.aspect, preferred: "1:1" });
      fill("resolution", res.map((v) => `resolution:${v}`), { current: saved.resolution, preferred: res.includes("1K") ? "resolution:1K" : undefined, label: (v) => v.split(":")[1] });
      const cr = commonRange(sel, "n");
      const counts = [];
      if (cr) for (let v = Math.max(1, cr.min); v <= Math.min(cr.max, MAX_IMAGES); v++) counts.push(String(v));
      fill("count", counts, { current: saved.count, preferred: "1", label: (v) => `${fa(v)} تصویر` });
      fill("format", commonEnum(sel, "output_format"), { current: saved.format, label: (v) => FORMAT[v] || v.toUpperCase() });
      fill("quality", commonEnum(sel, "quality"), { current: saved.quality, label: (v) => QUALITY[v] || v });
      fill("background", commonEnum(sel, "background"), { current: saved.background, label: (v) => BACKGROUND[v] || v });
      const seedOk = sel.length && sel.every((m) => supports(m, "seed"));
      $("#seed", composer).disabled = !seedOk;
      const refs = commonRange(sel, "input_references");
      const maxRefs = refs ? refs.max : 0;
      $("#refBtn", composer).disabled = maxRefs < 1;
      if (maxRefs < 1) { $("#refBox", composer).classList.add("hidden"); $("#refUrl", composer).value = ""; }
      $("#refNote", composer).textContent = maxRefs >= 1 ? `همه مدل‌های انتخابی تصویر مرجع می‌پذیرند (تا ${fa(maxRefs)} عدد).` : "مدل‌های انتخابی تصویر مرجع نمی‌پذیرند.";
      sel.forEach((m) => ensureImagePricing(m, () => { $("#pick", composer).innerHTML = String(pickerFace()); updateFooter(); }));
      if (sel.length > 1) { if (!ratios.length) missing.push("نسبت تصویر"); if (!res.length) missing.push("کیفیت"); }
      $("#capBadge", composer).textContent = sel.length > 1 ? `اشتراک ${fa(sel.length)} مدل` : `${fa(ratios.length)} نسبت`;
    } else {
      const ratios = common(sel, "supported_aspect_ratios");
      const durations = common(sel, "supported_durations").sort((a, b) => Number(a) - Number(b));
      const resOpts = [...common(sel, "supported_resolutions").map((v) => `resolution:${v}`), ...common(sel, "supported_sizes").map((v) => `size:${v}`)];
      fill("aspect", ratios, { current: saved.aspect, preferred: "16:9" });
      fill("duration", durations, { current: saved.duration, preferred: durations.includes("5") ? "5" : durations[0], label: (v) => `${fa(v)} ثانیه` });
      fill("resolution", resOpts, { current: saved.resolution, preferred: resOpts.includes("resolution:720p") ? "resolution:720p" : resOpts[0], label: (v) => v.split(":")[1] });
      const audioOk = sel.length && sel.every((m) => m.generate_audio === true);
      const audio = $("#audio", composer);
      audio.disabled = !audioOk;
      audio.checked = audioOk && (useSaved ? saved.audio === true : audio.checked);   // audio is billed extra: off until asked
      $("#audioText", composer).textContent = audioOk ? "صدای اصلی" : "پشتیبانی نمی‌شود";
      const seedOk = sel.length && sel.every((m) => m.seed !== null && m.seed !== false && m.seed !== undefined);
      $("#seed", composer).disabled = !seedOk;
      $("#refBtn", composer).disabled = false;
      const frames = common(sel, "supported_frame_images");
      $$("#frameTabs [data-frame]", composer).forEach((b) => {
        const ok = b.dataset.frame === "reference" || frames.includes(b.dataset.frame);
        b.disabled = !ok;
        b.classList.toggle("on", b.dataset.frame === st.imageMode);
      });
      if (st.imageMode !== "reference" && !frames.includes(st.imageMode)) {
        st.imageMode = "reference";
        $$("#frameTabs [data-frame]", composer).forEach((b) => b.classList.toggle("on", b.dataset.frame === "reference"));
      }
      $("#refNote", composer).textContent = st.imageMode === "reference" ? "پشتیبانی از تصویر مرجع به ارائه‌دهنده بستگی دارد؛ OpenRouter بررسی می‌کند."
        : `همه مدل‌های انتخابی ${st.imageMode === "first_frame" ? "فریم اول" : "فریم آخر"} را پشتیبانی می‌کنند.`;
      if (sel.length > 1) { if (!ratios.length) missing.push("نسبت تصویر"); if (!durations.length) missing.push("مدت"); if (!resOpts.length) missing.push("کیفیت"); }
      $("#capBadge", composer).textContent = sel.length > 1 ? `اشتراک ${fa(sel.length)} مدل` : `${fa(ratios.length)} نسبت`;
    }
    syncResolution();
    if ($("#seed", composer).disabled) $("#seed", composer).value = "";
    const pass = common(sel, "allowed_passthrough_parameters");
    $("#passHint", composer).textContent = pass.length ? `پارامترهای مشترک: ${pass.join("، ")}` : "به همان شکل برای OpenRouter فرستاده و آنجا بررسی می‌شود.";
    const compat = $("#compat", composer);
    compat.classList.toggle("hidden", !missing.length);
    compat.textContent = missing.length ? `مدل‌ها در ${missing.join("، ")} اشتراک ندارند؛ برای آن‌ها پیش‌فرض هر مدل استفاده می‌شود.` : "";
    updateFooter();
  }
  function syncResolution() {
    const exact = ($("#resolution", composer)?.value || "").startsWith("size:");
    const aspect = $("#aspect", composer);
    if (aspect) { aspect.disabled = exact || aspect.options.length <= 1; aspect.title = exact ? "ابعاد دقیق، نسبت را مشخص کرده" : ""; }
  }
  function readSettings() {
    const v = (id) => $(`#${id}`, composer)?.value || "";
    return { prompt: $("#prompt", composer)?.value || "", aspect: v("aspect"), duration: v("duration"), resolution: v("resolution"), count: v("count"),
      format: v("format"), quality: v("quality"), background: v("background"), audio: !!$("#audio", composer)?.checked };
  }
  const imageCount = () => { const n = Number($("#count", composer)?.value); return Number.isSafeInteger(n) && n >= 1 ? Math.min(n, MAX_IMAGES) : 1; };

  function buildFields() {
    const prompt = $("#prompt", composer).value.trim();
    if (!prompt) throw new Error("متن درخواست را بنویسید.");
    const f = { prompt };
    const aspect = $("#aspect", composer).value, res = $("#resolution", composer).value;
    const exact = res.startsWith("size:");
    if (!exact && aspect) f.aspect_ratio = aspect;
    if (res.startsWith("resolution:")) f.resolution = res.slice(11);
    else if (exact) f.size = res.slice(5);
    const seedEl = $("#seed", composer);
    if (!seedEl.disabled && seedEl.value.trim()) {
      const seed = Number(seedEl.value.replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
      if (!Number.isSafeInteger(seed) || seed < 0 || seed > 4294967295) throw new Error("Seed باید عدد صحیح بین ۰ و ۴۲۹۴۹۶۷۲۹۵ باشد.");
      f.seed = seed;
    }
    const url = $("#refBox", composer).classList.contains("hidden") ? "" : $("#refUrl", composer).value.trim();
    if (url) {
      let parsed;
      try { parsed = new URL(url); } catch (e) { throw new Error("آدرس تصویر مرجع معتبر نیست."); }
      if (parsed.protocol !== "https:") throw new Error("آدرس تصویر باید HTTPS و عمومی باشد.");
      if (st.mode === "video" && st.imageMode !== "reference") f.frame_images = [{ type: "image_url", image_url: { url }, frame_type: st.imageMode }];
      else f.input_references = [{ type: "image_url", image_url: { url } }];
    }
    const raw_ = $("#provider", composer).value.trim();
    if (raw_) {
      let p;
      try { p = JSON.parse(raw_); } catch (e) { throw new Error("گزینه‌های ارائه‌دهنده باید JSON معتبر باشد."); }
      if (!p || typeof p !== "object" || Array.isArray(p)) throw new Error("گزینه‌های ارائه‌دهنده باید یک شیء JSON باشد.");
      f.provider = p;
    }
    if (st.mode === "image") {
      if (imageCount() > 1) f.n = imageCount();
      for (const [id, key] of [["format", "output_format"], ["quality", "quality"], ["background", "background"]]) if ($(`#${id}`, composer).value) f[key] = $(`#${id}`, composer).value;
    } else {
      if ($("#duration", composer).value) f.duration = Number($("#duration", composer).value);
      if (!$("#audio", composer).disabled) f.generate_audio = $("#audio", composer).checked;
    }
    return f;
  }

  function updateFooter() {
    const out = $("#outCount", composer);
    if (!out) return;
    const sel = selected();
    const outputs = st.mode === "image" ? Math.max(sel.length, 1) * imageCount() : Math.max(sel.length, 1);
    out.textContent = `${fa(outputs)} خروجی`;
    const skus = sel.reduce((a, m) => a + pricingEntries(m).length, 0);
    $("#priceHint", composer).textContent = skus ? "قیمت هر مدل قبل از ارسال نشان داده می‌شود" : sel.length ? "هزینه نهایی را OpenRouter تعیین می‌کند" : "";
    $("#genLabel", composer).textContent = st.mode === "image" ? (outputs > 1 ? `ساخت ${fa(outputs)} تصویر` : "ساخت تصویر") : sel.length > 1 ? `ساخت ${fa(sel.length)} ویدیو` : "ساخت ویدیو";
    $("#pcount", composer).textContent = fa($("#prompt", composer).value.length);
    $("#generate", composer).disabled = st.submitting || !sel.length;
  }

  async function switchMode(mode) {
    if (mode === st.mode) return;
    persist();
    st.mode = mode;
    drawComposer();
    await ensureModels();
  }
  async function ensureModels() {
    try {
      await loadModels(st.mode);
    } catch (e) {
      toast(e.message, "error");
    }
    const known = st.selection[st.mode].filter((id) => models().some((m) => m.id === id));
    st.selection[st.mode] = known.length ? known.slice(0, st.compare ? MAX_COMPARE : 1) : models().length ? [models()[0].id] : [];
    if ($("#pick", composer)) syncCapabilities(true);
  }

  function openPicker() {
    let term = "";
    const s = sheet({ title: st.compare ? `انتخاب تا ${fa(MAX_COMPARE)} مدل برای مقایسه` : "انتخاب مدل", size: "wide",
      body: html`<div class="stack s12"><div class="input-wrap">${icon("search")}<input class="input" id="msearch" placeholder="جستجوی مدل… (مثلاً veo، kling، gpt-image)" autocomplete="off"></div>
        <div class="small muted" id="mcount"></div><div class="model-list" id="mlist"></div></div>`,
      foot: html`<button class="btn primary" data-close>${icon("check")} تأیید</button>` });
    const draw = () => {
      const list = models().filter((m) => `${m.name || ""} ${m.id} ${m.description || ""}`.toLowerCase().includes(term));
      s.root.querySelector("#mcount").textContent = `${fa(list.length)} مدل${st.compare ? ` · ${fa(st.selection[st.mode].length)} از ${fa(MAX_COMPARE)} انتخاب شده` : ""}`;
      s.root.querySelector("#mlist").innerHTML = list.length ? String(html`${list.map((m) => html`<button class="model-opt ${st.selection[st.mode].includes(m.id) ? "on" : ""}" data-model="${m.id}">
        ${provAvatar(m.id)}<span class="mo-copy"><strong>${m.name || m.id}</strong>
          <span class="model-tags"><span>${m.id.split("/")[0]}</span>${capabilityTags(m).map((t) => html`<span>${t}</span>`)}
            <span title="${describePricing(m, 20)}">${pricingEntries(m).length ? describePricing(m, 1) : "قیمت: —"}</span></span></span>
        <span class="tick">${icon("check", "sm")}</span></button>`)}`) : String(emptyState("search", "مدلی پیدا نشد"));
    };
    s.root.querySelector("#msearch").addEventListener("input", (e) => { term = e.target.value.trim().toLowerCase(); draw(); });
    s.root.querySelector("#mlist").addEventListener("click", (e) => {
      const b = e.target.closest("[data-model]");
      if (!b) return;
      const id = b.dataset.model, sel = st.selection[st.mode];
      if (!st.compare) { st.selection[st.mode] = [id]; syncCapabilities(); persist(); s.close(); return; }
      if (sel.includes(id)) { if (sel.length === 1) return toast("حداقل یک مدل لازم است", "error"); st.selection[st.mode] = sel.filter((x) => x !== id); }
      else if (sel.length >= MAX_COMPARE) return toast(`حداکثر ${fa(MAX_COMPARE)} مدل`, "error");
      else st.selection[st.mode] = [...sel, id];
      syncCapabilities();
      persist();
      draw();
    });
    draw();
  }

  function confirmGenerate() {
    let fields;
    try { fields = buildFields(); } catch (e) { return toast(e.message, "error"); }
    const sel = selected();
    if (!sel.length) return toast("یک مدل انتخاب کنید", "error");
    const kind = st.mode === "image" ? "تصویر" : "ویدیو";
    const rows = st.mode === "image"
      ? { "نسبت": fields.aspect_ratio || (fields.size ? "از ابعاد" : "پیش‌فرض"), "تعداد": fa(fields.n || 1), "کیفیت": fields.resolution || fields.size || "پیش‌فرض", "فرمت": fields.output_format || "پیش‌فرض" }
      : { "نسبت": fields.aspect_ratio || (fields.size ? "از ابعاد" : "پیش‌فرض"), "مدت": fields.duration ? `${fa(fields.duration)} ثانیه` : "پیش‌فرض", "کیفیت": fields.resolution || fields.size || "پیش‌فرض", "صدا": fields.generate_audio ? "بله" : "خیر" };
    const s = sheet({
      title: "شروع ساخت؟",
      body: html`<div class="stack s12">
        <div class="callout warn">${icon("dollar-sign")}<div>${sel.length > 1 ? `${fa(sel.length)} کار جداگانه و هزینه‌دار ${kind} با همین متن و تنظیمات ارسال می‌شود.` : `یک کار هزینه‌دار ساخت ${kind} به OpenRouter ارسال می‌شود.`}
          ${M.config.monthly_limit_usd ? ` هزینه این ماه تا الان ${usd(M.config.month_spend) || "$0"} از سقف ${usd(M.config.monthly_limit_usd)} است.` : ""}</div></div>
        <div class="confirm-models">${sel.map((m) => html`<div class="list-item">${provAvatar(m.id, "sm")}<div class="grow"><b>${m.name || m.id}</b><small title="${describePricing(m, 20)}">${describePricing(m, 4)}</small></div></div>`)}</div>
        <dl class="spec-list">${Object.entries(rows).map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
      </div>`,
      foot: html`<button class="btn brand" id="go">${icon("wand-sparkles")} بله، بساز</button><button class="btn ghost" data-close>انصراف</button>`,
    });
    s.root.querySelector("#go").onclick = async (e) => {
      e.target.disabled = true;
      s.close();
      await submit(fields, sel);
    };
  }
  async function submit(fields, sel) {
    st.submitting = true;
    updateFooter();
    persist();
    try {
      const r = await api("/api/media/generate", { method: "POST", body: { kind: st.mode, models: sel.map((m) => ({ id: m.id, name: m.name || m.id })), fields } });
      st.batch = r.items;
      drawStage();
      toast(st.mode === "image" ? "در حال ساخت؛ معمولاً کمتر از یک دقیقه" : "کار ارسال شد؛ ساخت ویدیو ممکن است چند دقیقه طول بکشد (می‌توانید صفحه را ببندید)", "info", { timeout: 6000 });
      loadConfig().catch(() => {});
    } finally {
      st.submitting = false;
      updateFooter();
    }
  }

  async function restoreFrom(id) {
    let g;
    try { g = await api(`/api/media/generations/${id}`); } catch (e) { return; }
    st.mode = g.kind;
    st.compare = false;
    drawComposer();
    await ensureModels();
    if (models().some((m) => m.id === g.model_id)) { st.selection[st.mode] = [g.model_id]; syncCapabilities(); }
    const r = g.request || {};
    $("#prompt", composer).value = g.prompt || r.prompt || "";
    const set = (sel, v) => { const el = $(sel, composer); if (el && v !== undefined && v !== null && [...el.options].some((o) => o.value === String(v))) el.value = String(v); };
    set("#aspect", r.aspect_ratio);
    set("#resolution", r.resolution ? `resolution:${r.resolution}` : r.size ? `size:${r.size}` : "");
    set("#duration", r.duration);
    set("#count", r.n || 1);
    set("#format", r.output_format);
    set("#quality", r.quality);
    set("#background", r.background);
    if ($("#audio", composer) && !$("#audio", composer).disabled && typeof r.generate_audio === "boolean") $("#audio", composer).checked = r.generate_audio;
    if (r.seed !== undefined && !$("#seed", composer).disabled) $("#seed", composer).value = r.seed;
    if (r.provider) $("#provider", composer).value = JSON.stringify(r.provider, null, 2);
    const frame = r.frame_images?.[0], ref = r.input_references?.[0];
    if (frame || ref) {
      st.imageMode = frame?.frame_type || "reference";
      $("#refBox", composer).classList.remove("hidden");
      $("#refUrl", composer).value = frame?.image_url?.url || ref?.image_url?.url || "";
      syncCapabilities();
    }
    syncResolution();
    updateFooter();
    toast("تنظیمات قبلی برگشت؛ برای ساخت دوباره تأیید کنید", "info");
    setTimeout(confirmGenerate, 150);
  }

  // composer events (delegated: the composer is redrawn on mode change)
  composer.addEventListener("click", (e) => {
    const t = e.target.closest("button, [data-mode]");
    if (!t) return;
    if (t.dataset.mode) switchMode(t.dataset.mode);
    else if (t.id === "pick") { if (models().length) openPicker(); }
    else if (t.dataset.unsel) { if (st.selection[st.mode].length > 1) { st.selection[st.mode] = st.selection[st.mode].filter((x) => x !== t.dataset.unsel); syncCapabilities(); persist(); } }
    else if (t.id === "ideasBtn") $("#ideas", composer).classList.toggle("hidden");
    else if (t.dataset.prompt) { $("#prompt", composer).value = t.dataset.prompt; updateFooter(); persist(); }
    else if (t.id === "refBtn") { $("#refBox", composer).classList.toggle("hidden"); if (!$("#refBox", composer).classList.contains("hidden")) $("#refUrl", composer).focus(); }
    else if (t.dataset.frame && !t.disabled) { st.imageMode = t.dataset.frame; syncCapabilities(); persist(); }
    else if (t.id === "generate") confirmGenerate();
  });
  composer.addEventListener("change", (e) => {
    if (e.target.id === "compare") {
      st.compare = e.target.checked;
      if (!st.compare && st.selection[st.mode].length > 1) st.selection[st.mode] = st.selection[st.mode].slice(0, 1);
      syncCapabilities();
    }
    if (e.target.id === "resolution") syncResolution();
    updateFooter();
    persist();
  });
  composer.addEventListener("input", (e) => { if (e.target.id === "prompt") { updateFooter(); clearTimeout(composer._t); composer._t = setTimeout(persist, 400); } });
  const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canCreate()) { e.preventDefault(); confirmGenerate(); } };
  document.addEventListener("keydown", onKey);

  // ------------------------------------------------------------ stage (results)
  function drawStage() {
    if (!st.batch.length) {
      stage.innerHTML = String(html`<section class="card"><div class="stage-empty">
        <span class="gen-orb">${icon("sparkles")}</span>
        <h2>زیبایی را جادویی نشان بده</h2>
        <p class="small muted">یک ایده انتخاب کنید یا متن خودتان را بنویسید. همه ساخته‌ها در کتابخانه مشترک تیم ذخیره می‌شوند.</p>
        ${canCreate() && M.config.configured ? html`<div class="starters">${IDEAS.map((i) => html`<button class="starter" data-starter="${i.prompt}">
          <span class="s-ico">${icon(i.ico)}</span><b>${i.label}</b><span class="ltr" style="text-align:left;font-size:11.5px">${i.prompt.slice(0, 90)}…</span></button>`)}</div>` : ""}
      </div></section>`);
      return;
    }
    stage.innerHTML = String(html`<div class="row"><h2 class="grow">${st.batch.length > 1 ? `مقایسه ${fa(st.batch.length)} مدل` : "نتیجه"}</h2>
        <a class="btn sm ghost" href="#/media/library">${icon("library", "sm")} کتابخانه</a></div>
      <div class="results ${st.batch.length === 1 ? "single" : ""}">${st.batch.map(resultCard)}</div>`);
  }
  stage.addEventListener("click", (e) => {
    const s = e.target.closest("[data-starter]");
    if (s && $("#prompt", composer)) { $("#prompt", composer).value = s.dataset.starter; updateFooter(); persist(); $("#prompt", composer).focus(); }
  });
  bindCardActions(stage, { onRetry: (id) => restoreFrom(id) });

  // the most recent batch of this user (survives reloads: generations live on the server)
  const recent = await api("/api/media/generations?mine=true&limit=6").catch(() => []);
  if (recent.length) st.batch = recent.filter((g) => g.batch_id === recent[0].batch_id).reverse();
  drawComposer();
  drawStage();
  if (M.config.configured && canCreate()) ensureModels();

  const offLive = onMedia((ev) => {
    if (ev.type !== "generation" || !ev.item) return;
    const i = st.batch.findIndex((g) => g.id === ev.item.id);
    if (i < 0) return;
    const prevStatus = st.batch[i].status;
    st.batch[i] = ev.item;
    const card = stage.querySelector(`[data-gen="${ev.item.id}"]`);
    if (card && (prevStatus !== ev.item.status || TERMINAL.has(ev.item.status))) card.outerHTML = String(resultCard(ev.item));
  });
  const tick = setInterval(() => {
    for (const g of st.batch) if (!TERMINAL.has(g.status)) { const el = stage.querySelector(`[data-elapsed="${g.id}"]`); if (el) el.textContent = elapsed(g); }
  }, 1000);
  if (query.get("retry")) restoreFrom(Number(query.get("retry")));
  return () => { offLive(); clearInterval(tick); document.removeEventListener("keydown", onKey); persist(); };
}
