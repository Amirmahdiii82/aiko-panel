// Runs before the page paints (plain script, no module): set the light/dark theme and expose the asset version used
// for cache busting. Kept out of index.html so the CSP can forbid inline scripts.
// <html data-theme> is always set — to the choice saved with the theme button, or else dark, the panel's own look —
// so the stylesheets only need one dark palette ([data-theme="dark"]).
(function () {
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem("aiko-theme"); } catch (e) { /* private mode */ }
  root.dataset.theme = saved || "dark";
  const meta = document.querySelector('meta[name="aiko-version"]');
  window.AIKO_VERSION = meta ? meta.content : "";

  // The phone status bar follows <meta name="theme-color">: point both tags at the current theme's page colour.
  const PAGE = { light: "#ECEAED", dark: "#0D0C0F" };
  window.aikoSyncThemeColor = function () {
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => { m.content = PAGE[root.dataset.theme]; });
  };
  window.aikoSyncThemeColor();
})();
