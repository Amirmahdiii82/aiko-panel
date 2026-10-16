// Runs before the page paints (plain script, no module): apply the saved light/dark choice and expose the
// asset version used for cache busting. Kept out of index.html so the CSP can forbid inline scripts.
(function () {
  try { const t = localStorage.getItem("aiko-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* private mode */ }
  const meta = document.querySelector('meta[name="aiko-version"]');
  window.AIKO_VERSION = meta ? meta.content : "";
})();
