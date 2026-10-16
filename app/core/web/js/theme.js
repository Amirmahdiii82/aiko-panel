// Runs before the page paints (plain script, no module): apply the saved light/dark choice and expose the
// asset version used for cache busting. Kept out of index.html so the CSP can forbid inline scripts.
(function () {
  try { const t = localStorage.getItem("aiko-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* private mode */ }
  const meta = document.querySelector('meta[name="aiko-version"]');
  window.AIKO_VERSION = meta ? meta.content : "";

  // The phone status bar follows <meta name="theme-color">, which only knows the OS scheme. When the theme was
  // picked by hand, point both tags at that theme's page color so the bar matches the app.
  const PAGE = { light: "#F5EEE9", dark: "#1A1420" };
  window.aikoSyncThemeColor = function () {
    const t = document.documentElement.dataset.theme;
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => {
      const own = (m.media || "").includes("dark") ? PAGE.dark : PAGE.light;
      m.content = PAGE[t] || own;
    });
  };
  window.aikoSyncThemeColor();
})();
