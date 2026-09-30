/* پوستهٔ تم، برگهٔ حساب و ترجیح‌های کاربر. منطق سفارش این‌جا نیست. */
(function () {
  var root = document.documentElement;

  function headerColor() {
    var c = getComputedStyle(root).getPropertyValue("--lb-header").trim();
    try {
      var w = window.Bale && Bale.WebApp;
      if (w && w.setHeaderColor && c) w.setHeaderColor(c);
    } catch (e) {}
  }

  function haptic(kind) {
    var h = window.Bale && Bale.WebApp && Bale.WebApp.HapticFeedback;
    if (h) {
      if (kind === "selection" && h.selectionChanged) h.selectionChanged();
      else if (h.notificationOccurred && (kind === "success" || kind === "warning" || kind === "error")) h.notificationOccurred(kind);
      else if (h.impactOccurred) h.impactOccurred(kind === "selection" ? "light" : kind);
      return;
    }
    var iframe = window.Bale && Bale.WebApp && Bale.WebApp.isIframe;
    if (!iframe && navigator.vibrate) {
      var map = { selection: 8, light: 10, medium: 18, success: [12, 40, 12], warning: [20, 60, 20], error: [30, 50, 30, 50, 30] };
      navigator.vibrate(map[kind] || 10);
    }
  }
  window.lbHaptic = haptic;

  var toastTimer = 0;
  window.lbToast = function (text) {
    var old = document.getElementById("lb-toast");
    if (old) old.remove();
    var el = document.createElement("div");
    el.id = "lb-toast";
    el.className = "lb-toast";
    el.textContent = text;
    document.body.appendChild(el);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.remove(); }, 2600);
  };

  function themeLabel() {
    return root.dataset.theme === "dark" ? "حالت روشن" : "حالت تاریک";
  }

  function paintButton(btn) {
    var t = themeLabel();
    btn.setAttribute("aria-label", t);
    btn.setAttribute("title", t);
    btn.setAttribute("aria-pressed", root.dataset.theme === "dark" ? "true" : "false");
  }

  function authHeaders(json) {
    var init = (window.Bale && Bale.WebApp && Bale.WebApp.initData) || "";
    var headers = {};
    if (init) headers["X-Bale-Init-Data"] = init;
    if (json) headers["Content-Type"] = "application/json";
    return headers;
  }

  function prefsUrl() {
    var api = window.__LIVE_API || "/miniapp/api";
    var d = new URLSearchParams(location.search).get("debug_bale_id") || "";
    return api + "/me/prefs" + (d ? "?debug_bale_id=" + encodeURIComponent(d) : "");
  }

  function savePrefs(body) {
    var d = new URLSearchParams(location.search).get("debug_bale_id") || "";
    var payload = d ? Object.assign({ debug_bale_id: d }, body) : body;
    fetch(prefsUrl(), { method: "PATCH", headers: authHeaders(true), body: JSON.stringify(payload) }).catch(function () {});
  }

  function apply(next, source) {
    root.dataset.theme = next;
    root.dataset.themeSource = source;
    root.dataset.bale = next;
    root.style.colorScheme = next;
    headerColor();
  }

  function rays() {
    var s = "";
    for (var i = 0; i < 8; i++) {
      var a = (Math.PI / 4) * i;
      s += '<circle cx="' + (12 + Math.cos(a) * 10).toFixed(2) + '" cy="' + (12 + Math.sin(a) * 10).toFixed(2) + '" r="1.1"/>';
    }
    return s;
  }

  function toggle(e) {
    var next = root.dataset.theme === "dark" ? "light" : "dark";
    var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    var go = function () {
      apply(next, "user");
      document.querySelectorAll("button.tt").forEach(paintButton);
    };
    if (document.startViewTransition && !reduce && e && e.currentTarget) {
      var box = e.currentTarget.getBoundingClientRect();
      root.style.setProperty("--tt-x", box.x + 22 + "px");
      root.style.setProperty("--tt-y", box.y + 22 + "px");
      document.startViewTransition(go);
    } else {
      root.classList.add("theme-anim");
      go();
      setTimeout(function () { root.classList.remove("theme-anim"); }, 260);
    }
    try { localStorage.setItem("lb.theme", next); } catch (err) {}
    savePrefs({ theme: next });
    haptic("selection");
  }

  function mount(header) {
    if (!header || header.querySelector("button.tt")) return;
    var row = header.querySelector(":scope > div");
    if (!row) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tt";
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">' +
      '<mask id="lb-tt-m"><rect width="24" height="24" fill="#fff"/><circle class="tt-cut" cx="8" cy="8" r="7" fill="#000"/></mask>' +
      '<circle class="tt-core" cx="13" cy="13" r="8.5" fill="currentColor" mask="url(#lb-tt-m)"/>' +
      '<g class="tt-rays" fill="currentColor">' + rays() + "</g>" +
      '<g class="tt-stars" fill="currentColor">' +
      '<path d="M4.5 2.2l.55 1.35 1.35.55-1.35.55-.55 1.35-.55-1.35L2.6 4.1l1.35-.55z"/>' +
      '<path d="M9.2 1l.35.85.85.35-.85.35-.35.85-.35-.85-.85-.35.85-.35z"/>' +
      "</g></svg>";
    paintButton(btn);
    btn.addEventListener("click", toggle);
    row.appendChild(btn);
  }

  function watch() {
    document.querySelectorAll("header").forEach(mount);
  }

  function closeSheet() {
    var back = document.getElementById("lb-account");
    if (back) back.remove();
  }

  function openAccount() {
    closeSheet();
    var back = document.createElement("div");
    back.id = "lb-account";
    back.className = "lb-sheet-back";
    var manual = root.dataset.themeSource === "user";
    back.innerHTML =
      '<div class="lb-sheet" role="dialog" aria-label="حساب">' +
      '<div class="lb-handle"></div>' +
      "<h2>حساب</h2>" +
      '<a class="row" href="/miniapp/rules/">شرایط و قوانین</a>' +
      (manual ? '<button type="button" class="row" id="lb-theme-reset">برگشت به تم بله</button>' : "") +
      '<p style="margin:16px 0 8px;font-size:12px;color:var(--lb-text-2)">نسخهٔ ۴٫۰٫۰</p>' +
      "</div>";
    back.addEventListener("click", function (ev) {
      if (ev.target === back) closeSheet();
    });
    document.body.appendChild(back);
    var reset = document.getElementById("lb-theme-reset");
    if (reset) {
      reset.addEventListener("click", function () {
        try { localStorage.removeItem("lb.theme"); } catch (e) {}
        savePrefs({ theme: "" });
        var w = window.Bale && Bale.WebApp;
        var b = (w && w.colorScheme) || "light";
        var bg = w && w.themeParams && w.themeParams.bg_color;
        if (bg && /^#([0-9a-f]{6})$/i.test(bg)) {
          var n = parseInt(bg.slice(1), 16);
          var l = (0.2126 * (n >> 16) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
          b = l < 0.4 ? "dark" : "light";
        }
        apply(b, "bale");
        document.querySelectorAll("button.tt").forEach(paintButton);
        closeSheet();
      });
    }
  }
  window.lbOpenAccount = openAccount;

  var mo = new MutationObserver(watch);
  mo.observe(document.documentElement, { childList: true, subtree: true });
  watch();

  if (root.dataset.themeSource !== "user") {
    fetch(prefsUrl(), { headers: authHeaders(false) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var t = j && j.prefs && j.prefs.theme;
        if ((t === "light" || t === "dark") && root.dataset.themeSource !== "user") {
          apply(t, "user");
          try { localStorage.setItem("lb.theme", t); } catch (e) {}
          document.querySelectorAll("button.tt").forEach(paintButton);
        }
      })
      .catch(function () {});
  }
  headerColor();

  function markReady() {
    try {
      var w = window.Bale && Bale.WebApp;
      if (!w || w.__lbReady) return;
      w.__lbReady = true;
      if (w.expand) w.expand();
      if (w.ready) w.ready();
      if (w.SettingsButton && w.SettingsButton.show) w.SettingsButton.show();
      if (w.onEvent) {
        w.onEvent("settingsButtonClicked", function () {
          if (window.lbOpenAccount) window.lbOpenAccount();
        });
      }
    } catch (e) {}
  }
  if (document.getElementById("root")) requestAnimationFrame(markReady);
  else document.addEventListener("DOMContentLoaded", markReady);
})();
