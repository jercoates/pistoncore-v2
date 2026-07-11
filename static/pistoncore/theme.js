/* Shared across every PistonCore page (loaded by templates/base.html).
 * Persists in localStorage under "pistoncore_theme" -- the SAME preference
 * pistoncore-nav.js reads to sync webCoRE's own dashboard theme (which has
 * a real, already-vendored dark mode: colorSchemeService.toggleDarkMode(),
 * confirmed against dashboard/index.html:61 <body data-theme="{{theme}}">
 * and the CSS variables in dashboard/css/app.css). No stock file touched.
 */
(function () {
  var STORAGE_KEY = "pistoncore_theme";

  function currentTheme() {
    return localStorage.getItem(STORAGE_KEY) ||
      (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  apply(currentTheme());

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      localStorage.setItem(STORAGE_KEY, next);
      apply(next);
    });
  });
})();
