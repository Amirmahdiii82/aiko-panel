// The selection pill: in every tab group (sections, a module's pages, segmented controls, the phone's bottom bar) the
// current item sits on one shared pane of glass that slides to the next item. Its two edges move separately: the
// leading edge goes first and faster, the trailing edge catches up, so the pane stretches a little on the way and
// settles. The pane is clipped with clip-path inset() on two registered properties (--pl / --pr in ui.css), so each
// edge gets its own duration and curve. Groups are found by one document-wide observer: pages need no code for it.
import { reducedMotion } from "./core.js";

const GROUPS = ".modnav, .subnav, .seg, .bottom-nav";
const OUT = "cubic-bezier(0.215, 0.61, 0.355, 1)";        // the leading edge: quick, then eases in
const IN_OUT = "cubic-bezier(0.645, 0.045, 0.355, 1)";    // the trailing edge: waits a beat, then catches up
const LEAD = 360, TRAIL = 550;
// pages often redraw a whole control on click: a group with the same labels drawn again right after a tap or a key is
// the same control, so its pill starts from where the old one stood
const recent = new Map();
const REDRAW_MS = 1000;
let touched = -Infinity;
for (const type of ["pointerdown", "keydown"]) addEventListener(type, () => { touched = performance.now(); }, true);
const labels = (box) => [...box.querySelectorAll(":scope > a, :scope > button")].map((e) => e.textContent.trim()).join("|");

function attach(box) {
  if (box._pill) return;
  const pill = document.createElement("span");
  pill.className = "slide-pill";
  pill.setAttribute("aria-hidden", "true");
  box._pill = pill;
  box.classList.add("has-pill");
  let prev = null;

  const place = (animate) => {
    const on = box.querySelector(":scope > .on");
    if (!pill.isConnected) box.prepend(pill);
    if (!on || !on.getClientRects().length) { pill.style.opacity = "0"; prev = null; return; }
    pill.style.width = `${box.scrollWidth}px`;
    const p = pill.getBoundingClientRect(), r = on.getBoundingClientRect();
    const edges = { l: r.left - p.left, r: p.right - r.right, t: r.top - p.top, b: p.bottom - r.bottom };
    // nothing moved (a resize observer's first call, a redraw of the same selection): leave a running slide alone
    if (prev && pill.style.opacity === "1" && ["l", "r", "t", "b"].every((k) => Math.abs(edges[k] - prev[k]) <= 1)) return;
    const move = animate && prev && pill.style.opacity === "1" && !reducedMotion();
    if (move && Math.abs(edges.l - prev.l) > 1) {
      const right = edges.l > prev.l;
      pill.style.transition = right
        ? `--pl ${TRAIL}ms ${IN_OUT}, --pr ${LEAD}ms ${OUT}`
        : `--pl ${LEAD}ms ${OUT}, --pr ${TRAIL}ms ${IN_OUT}`;
    } else {
      pill.style.transition = "none";
    }
    for (const k of ["l", "r", "t", "b"]) pill.style.setProperty(`--p${k}`, `${edges[k]}px`);
    pill.style.opacity = "1";
    prev = edges;
    recent.set(labels(box), edges);
  };
  const resume = () => {
    const last = recent.get(labels(box));
    if (!last || performance.now() - touched > REDRAW_MS || !box.querySelector(":scope > .on")) return false;
    box.prepend(pill);
    pill.style.transition = "none";
    for (const k of ["l", "r", "t", "b"]) pill.style.setProperty(`--p${k}`, `${last[k]}px`);
    pill.style.opacity = "1";
    prev = last;
    pill.getBoundingClientRect();   // commit the old position before moving
    return true;
  };

  let queued = false;
  const schedule = (animate) => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; place(animate); });
  };
  // a selection slides, whether the page flips a class or redraws the group's buttons; a resize only re-measures
  new MutationObserver(() => schedule(true))
    .observe(box, { attributes: true, attributeFilter: ["class"], subtree: true, childList: true });
  new ResizeObserver(() => schedule(false)).observe(box);
  place(resume());
}

function scan() {
  document.querySelectorAll(GROUPS).forEach(attach);
}

let pending = false;
new MutationObserver(() => {
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => { pending = false; scan(); });
}).observe(document.documentElement, { childList: true, subtree: true });
scan();
