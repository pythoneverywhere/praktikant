/* Переключение тёмной / светлой темы.
   Подключать в <head> БЕЗ defer, чтобы тема применялась до отрисовки (без мигания). */
(function () {
  var KEY = "praktika_theme";
  var root = document.documentElement;

  var SUN =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>';

  function readSaved() {
    try {
      return localStorage.getItem(KEY);
    } catch (_) {
      return null;
    }
  }

  function current() {
    return root.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#f6f4ef" : "#0d0c0a");
  }

  function updateButtons() {
    var isLight = current() === "light";
    var label = isLight ? "Включить тёмную тему" : "Включить светлую тему";
    document.querySelectorAll(".theme-toggle").forEach(function (btn) {
      btn.innerHTML = isLight ? MOON : SUN;
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
    });
  }

  function toggle() {
    var next = current() === "light" ? "dark" : "light";
    apply(next);
    try {
      localStorage.setItem(KEY, next);
    } catch (_) {}
    updateButtons();
  }

  apply(readSaved() === "light" ? "light" : "dark");

  function init() {
    var buttons = document.querySelectorAll(".theme-toggle");
    if (!buttons.length) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "theme-toggle theme-toggle--float";
      document.body.appendChild(btn);
      buttons = [btn];
    }
    Array.prototype.forEach.call(buttons, function (btn) {
      btn.addEventListener("click", toggle);
    });
    updateButtons();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.Theme = { toggle: toggle, get: current };
})();
