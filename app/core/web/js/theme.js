// Runs before the page paints (plain script, no module): set the light/dark theme and expose the asset version used
// for cache busting. Kept out of index.html so the CSP can forbid inline scripts.
// <html data-theme> is always set — to the choice saved with the theme button, or else to the system's — so the
// stylesheets only need one dark palette ([data-theme="dark"]). Without a saved choice it follows the system live.
(function () {
  const root = document.documentElement;
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  let saved = null;
  try { saved = localStorage.getItem("aiko-theme"); } catch (e) { /* private mode */ }
  root.dataset.theme = saved || (system.matches ? "dark" : "light");
  const meta = document.querySelector('meta[name="aiko-version"]');
  window.AIKO_VERSION = meta ? meta.content : "";

  // The phone status bar follows <meta name="theme-color">: point both tags at the current theme's page colour.
  const PAGE = { light: "#F0F0EE", dark: "#0B0B0C" };
  window.aikoSyncThemeColor = function () {
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => { m.content = PAGE[root.dataset.theme]; });
  };
  window.aikoSyncThemeColor();
  system.addEventListener("change", (e) => {
    let picked = null;
    try { picked = localStorage.getItem("aiko-theme"); } catch (err) { /* private mode */ }
    if (picked) return;
    root.dataset.theme = e.matches ? "dark" : "light";
    window.aikoSyncThemeColor();
    window.dispatchEvent(new Event("aiko-theme"));
  });
})();
