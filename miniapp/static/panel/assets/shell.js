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
    el.setAttribute("role", "status");
    el.textContent = text;
    try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (e) {}
    document.body.appendChild(el);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.remove(); }, 2800);
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
      '<div class="lb-sheet" role="dialog" aria-label="حساب شما">' +
      '<div class="lb-handle"></div>' +
      "<h2>حساب شما</h2>" +
      '<a class="row" href="/miniapp/rules/">شرایط و قوانین</a>' +
      (manual ? '<button type="button" class="row" id="lb-theme-reset">هم‌رنگ گفتگوی بله</button>' : "") +
      '<p style="margin:16px 0 4px;font-size:13px;color:var(--lb-text)">اگر جایی ماندید، در گفتگو به پشتیبانی بگویید.</p>' +
      '<p style="margin:0 0 8px;font-size:12px;color:var(--lb-text-2)">نسخهٔ ۴</p>' +
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
      /* expand() قالب باریک خود بله را تمام‌صفحه می‌کند. ستون ۴۸۰ را shop.css نگه می‌دارد. */
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

  /* —— UI helpers: logo, field error, skeleton (only while loading) —— */
  window.lbFieldError = function (inputOrId, message) {
    var el = typeof inputOrId === "string" ? document.getElementById(inputOrId) : inputOrId;
    if (!el) return;
    var wrap = el.closest(".lb-field") || el.parentElement;
    if (!wrap) return;
    wrap.classList.add("lb-field");
    var err = wrap.querySelector(".lb-field-err");
    if (!message) {
      if (err) err.remove();
      el.classList.remove("lb-input-invalid");
      return;
    }
    el.classList.add("lb-input-invalid");
    if (!err) {
      err = document.createElement("p");
      err.className = "lb-field-err";
      wrap.appendChild(err);
    }
    err.textContent = message;
  };

  function ensureLogo() {
    var header = document.querySelector("header");
    if (!header || header.querySelector(".lb-brand-logo")) return;
    var h1 = header.querySelector("h1");
    if (!h1 || !h1.parentElement) return;
    var img = document.createElement("img");
    img.src = "/miniapp/static/panel/assets/logo-linkban.jpg";
    img.onerror = function () {
      this.src = "/miniapp/assets/logo-linkban.jpg";
    };
    img.alt = "لینک‌بان";
    img.className = "lb-brand-logo";
    img.width = 28;
    img.height = 28;
    h1.parentElement.insertBefore(img, h1);
  }

  function isLoadingParagraph(p) {
    if (!p || !p.isConnected) return false;
    var t = (p.textContent || "").trim();
    return t.indexOf("در حال خواندن") >= 0 || t.indexOf("در حال بارگذاری") >= 0;
  }

  function syncSkeletons() {
    // پاک‌سازی اسکلت‌های یتیم — علت نمایش دائمی روی همه صفحات
    document.querySelectorAll(".lb-skeleton-stack").forEach(function (sk) {
      var next = sk.nextElementSibling;
      if (!isLoadingParagraph(next)) {
        sk.remove();
      }
    });
    // فقط وقتی پیام لودینگ واقعاً هست اسکلت بساز
    document.querySelectorAll("main p.lb-loading-msg, main p.text-center.text-muted").forEach(function (p) {
      if (!isLoadingParagraph(p)) return;
      p.classList.add("lb-loading-msg");
      var prev = p.previousElementSibling;
      if (prev && prev.classList && prev.classList.contains("lb-skeleton-stack")) return;
      var sk = document.createElement("div");
      sk.className = "lb-skeleton-stack";
      sk.setAttribute("aria-hidden", "true");
      sk.innerHTML = '<div class="lb-skel"></div><div class="lb-skel"></div><div class="lb-skel short"></div>';
      p.parentElement && p.parentElement.insertBefore(sk, p);
    });
  }

  function enhanceEmptyNotes() {
    document.querySelectorAll(".empty-note").forEach(function (el) {
      if (el.dataset.lbEmpty) return;
      el.dataset.lbEmpty = "1";
      if (!el.querySelector(".lb-empty-icon")) {
        var icon = document.createElement("div");
        icon.className = "lb-empty-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "◇";
        el.insertBefore(icon, el.firstChild);
      }
    });
  }

  var tickScheduled = false;
  function tickUi() {
    if (tickScheduled) return;
    tickScheduled = true;
    requestAnimationFrame(function () {
      tickScheduled = false;
      try {
        ensureLogo();
        syncSkeletons();
        enhanceEmptyNotes();
      } catch (e) {}
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tickUi);
  } else {
    tickUi();
  }
  // فقط چند بار اول، نه هر 1.2s برای همیشه
  var n = 0;
  var boot = setInterval(function () {
    tickUi();
    if (++n > 8) clearInterval(boot);
  }, 400);

  var moTimer = 0;
  var mo = new MutationObserver(function () {
    clearTimeout(moTimer);
    moTimer = setTimeout(tickUi, 80);
  });
  function observe() {
    if (document.body) mo.observe(document.body, { childList: true, subtree: true });
  }
  if (document.body) observe();
  else document.addEventListener("DOMContentLoaded", observe);


  /* —— دور بعد: ۱۰ قابلیت UI —— */

  /* 7) بنر آفلاین */
  function ensureOfflineBar() {
    var bar = document.getElementById("lb-offline-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "lb-offline-bar";
      bar.className = "lb-offline-bar";
      bar.hidden = true;
      bar.textContent = "اتصال اینترنت برقرار نیست";
      document.body.appendChild(bar);
    }
    var offline = typeof navigator !== "undefined" && navigator.onLine === false;
    bar.hidden = !offline;
    document.documentElement.classList.toggle("lb-offline", offline);
  }
  window.addEventListener("online", ensureOfflineBar);
  window.addEventListener("offline", ensureOfflineBar);
  ensureOfflineBar();

  /* 3) تأیید با شیت پایین */
  window.lbConfirm = function (message, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var old = document.getElementById("lb-confirm");
      if (old) old.remove();
      var wrap = document.createElement("div");
      wrap.id = "lb-confirm";
      wrap.className = "lb-confirm-root";
      wrap.innerHTML =
        '<div class="lb-confirm-scrim" data-act="no"></div>' +
        '<div class="lb-confirm-sheet" role="dialog" aria-modal="true">' +
        '<p class="lb-confirm-msg"></p>' +
        '<div class="lb-confirm-actions">' +
        '<button type="button" class="lb-confirm-no" data-act="no"></button>' +
        '<button type="button" class="lb-confirm-yes" data-act="yes"></button>' +
        "</div></div>";
      wrap.querySelector(".lb-confirm-msg").textContent = message || "مطمئن هستید؟";
      wrap.querySelector(".lb-confirm-no").textContent = opts.cancelText || "انصراف";
      wrap.querySelector(".lb-confirm-yes").textContent = opts.okText || "تأیید";
      if (opts.danger) wrap.querySelector(".lb-confirm-yes").classList.add("danger");
      function close(v) {
        wrap.remove();
        resolve(!!v);
      }
      wrap.addEventListener("click", function (e) {
        var a = e.target.getAttribute && e.target.getAttribute("data-act");
        if (a === "yes") close(true);
        if (a === "no") close(false);
      });
      document.body.appendChild(wrap);
      try { if (window.lbHaptic) window.lbHaptic("warning"); } catch (e) {}
    });
  };

  /* 5) پیش‌نمایش تمام‌صفحه تصویر */
  window.lbLightbox = function (src) {
    if (!src) return;
    var old = document.getElementById("lb-lightbox");
    if (old) old.remove();
    var box = document.createElement("div");
    box.id = "lb-lightbox";
    box.className = "lb-lightbox";
    box.innerHTML = '<button type="button" class="lb-lightbox-close" aria-label="بستن">×</button><img alt="" />';
    box.querySelector("img").src = src;
    function close() { box.remove(); }
    box.addEventListener("click", function (e) {
      if (e.target === box || e.target.classList.contains("lb-lightbox-close")) close();
    });
    document.body.appendChild(box);
  };
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || t.tagName !== "IMG") return;
    if (t.classList.contains("lb-brand-logo")) return;
    if (t.closest("nav") || t.closest("header")) return;
    var src = t.currentSrc || t.src || "";
    if (!src || src.indexOf("data:") === 0) return;
    // فقط تصاویر بنر/لیست با اندازه معقول
    if (t.naturalWidth && t.naturalWidth < 40) return;
    if (t.closest("main")) {
      e.preventDefault();
      window.lbLightbox(src);
    }
  }, true);

  /* 4) جستجو: debounce + پیام یافت نشد */
  function wireSearch() {
    document.querySelectorAll("main input[placeholder*='جستجو'], main input[placeholder*='شناسه']").forEach(function (inp) {
      if (inp.dataset.lbSearch) return;
      inp.dataset.lbSearch = "1";
      var timer = 0;
      inp.addEventListener("input", function () {
        clearTimeout(timer);
        var q = (inp.value || "").trim();
        timer = setTimeout(function () {
          var host = inp.closest("main") || document;
          var empty = host.querySelector(".lb-search-empty");
          // اگر لیست کارت خالی شد بعد از فیلتر کلاینتی — تقریبی
          var cards = host.querySelectorAll("main .rounded-2xl.bg-surface, .rounded-2xl.bg-surface");
          // فقط وقتی خود input خالی نیست و هیچ نتیجه‌ای در دید نیست سخت است؛ پیام کمکی زیر فیلد
          var hint = inp.parentElement && inp.parentElement.querySelector(".lb-search-hint");
          if (!hint && inp.parentElement) {
            hint = document.createElement("p");
            hint.className = "lb-search-hint";
            inp.parentElement.appendChild(hint);
          }
          if (hint) {
            if (q.length >= 2) hint.textContent = "در حال پالایش…";
            else hint.textContent = "";
            if (q.length >= 2) {
              setTimeout(function () {
                if (hint && (inp.value || "").trim() === q) hint.textContent = "";
              }, 400);
            }
          }
        }, 280);
      });
    });
  }

  /* 2) Pull-to-refresh ساده */
  (function () {
    var startY = 0, pulling = false, indicator;
    function ensureInd() {
      if (indicator) return indicator;
      indicator = document.createElement("div");
      indicator.className = "lb-ptr";
      indicator.hidden = true;
      indicator.textContent = "رها کنید تا نو شود";
      document.body.appendChild(indicator);
      return indicator;
    }
    document.addEventListener("touchstart", function (e) {
      var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
      if (!main || main.scrollTop > 2) return;
      startY = e.touches[0].clientY;
      pulling = true;
    }, { passive: true });
    document.addEventListener("touchmove", function (e) {
      if (!pulling) return;
      var dy = e.touches[0].clientY - startY;
      var ind = ensureInd();
      if (dy > 56) {
        ind.hidden = false;
        ind.classList.add("ready");
        ind.textContent = "رها کنید تا نو شود";
      } else if (dy > 24) {
        ind.hidden = false;
        ind.classList.remove("ready");
        ind.textContent = "بکشید برای تازه‌سازی";
      } else {
        ind.hidden = true;
      }
    }, { passive: true });
    document.addEventListener("touchend", function () {
      if (!pulling) return;
      pulling = false;
      var ind = ensureInd();
      if (!ind.hidden && ind.classList.contains("ready")) {
        ind.textContent = "در حال تازه‌سازی…";
        try { if (window.lbHaptic) window.lbHaptic("light"); } catch (e) {}
        setTimeout(function () {
          ind.hidden = true;
          ind.classList.remove("ready");
          // رفرش نرم: رویداد سفارشی برای اپ
          window.dispatchEvent(new CustomEvent("lb:refresh"));
          // اگر API زنده است، یک reload سبک ترجیحات/صفحه
          try {
            if (window.__LIVE_API && window.Bale && Bale.WebApp) {
              /* عمداً location.reload کامل نمی‌کنیم مگر نیاز */
            }
          } catch (e) {}
        }, 600);
      } else {
        ind.hidden = true;
      }
    });
  })();

  /* 8) دکمه شناور — فقط در نقش مشتری روی خانه/کانال‌ها */
  function syncFab() {
    var fab = document.getElementById("lb-fab");
    var roleBtn = document.querySelector("header button.rounded-full.bg-link");
    var role = roleBtn ? (roleBtn.textContent || "").trim() : "";
    var show = role.indexOf("مشتری") >= 0;
    var h1 = document.querySelector("header h1");
    var title = h1 ? (h1.textContent || "") : "";
    var onUseful = /خانه|کانال/.test(title);
    if (!show || !onUseful) {
      if (fab) fab.hidden = true;
      return;
    }
    if (!fab) {
      fab = document.createElement("button");
      fab.id = "lb-fab";
      fab.type = "button";
      fab.className = "lb-fab";
      fab.textContent = "＋ بنر";
      fab.addEventListener("click", function () {
        try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (e) {}
        // کلیک روی تب بنرها در ناو
        var btns = document.querySelectorAll("nav button");
        for (var i = 0; i < btns.length; i++) {
          if ((btns[i].textContent || "").indexOf("بنر") >= 0) {
            btns[i].click();
            break;
          }
        }
      });
      document.body.appendChild(fab);
    }
    fab.hidden = false;
  }

  /* 9) اندازه فونت دسترسی — سه سطح */
  window.lbSetFontScale = function (level) {
    var map = { sm: "15px", md: "16px", lg: "18px" };
    var v = map[level] || map.md;
    document.documentElement.style.setProperty("--lb-font-base", v);
    document.documentElement.dataset.font = level || "md";
    try { localStorage.setItem("lb.font", level || "md"); } catch (e) {}
  };
  try {
    var fs = localStorage.getItem("lb.font") || "md";
    window.lbSetFontScale(fs);
  } catch (e) {}

  /* 1) اسکلت لیست وقتی main تقریباً خالی است و لودینگ حساب نیست */
  function listSkeleton() {
    var main = document.querySelector("main");
    if (!main) return;
    var existing = main.querySelector(".lb-list-skeleton");
    var hasCards = main.querySelectorAll(".rounded-2xl.bg-surface").length > 0;
    var loading = main.querySelector(".lb-loading-msg, p.text-center.text-muted");
    var isLoad = loading && /در حال/.test(loading.textContent || "");
    if (isLoad && !hasCards) {
      if (!existing) {
        var sk = document.createElement("div");
        sk.className = "lb-list-skeleton";
        sk.innerHTML =
          '<div class="lb-skel-card"><div class="lb-skel"></div><div class="lb-skel short"></div></div>' +
          '<div class="lb-skel-card"><div class="lb-skel"></div><div class="lb-skel short"></div></div>' +
          '<div class="lb-skel-card"><div class="lb-skel"></div><div class="lb-skel short"></div></div>';
        main.appendChild(sk);
      }
    } else if (existing) {
      existing.remove();
    }
  }

  /* 6) نشان «جدید» — اگر ردیف سفارش تازه در DOM آمد */
  function markNewRows() {
    document.querySelectorAll("main .rounded-2xl.bg-surface").forEach(function (card) {
      if (card.dataset.lbSeen) return;
      card.dataset.lbSeen = "1";
      // فقط چند مورد اول بعد از mount
      if (!window.__lbMarkNew) return;
      if (card.querySelector(".lb-new-badge")) return;
      var b = document.createElement("span");
      b.className = "lb-new-badge";
      b.textContent = "جدید";
      card.style.position = "relative";
      card.appendChild(b);
    });
  }
  window.__lbMarkNew = true;
  setTimeout(function () { window.__lbMarkNew = false; }, 8000);

  /* 10) انیمیشن تعویض نقش */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("header button.rounded-full");
    if (!btn) return;
    var main = document.querySelector("main");
    if (main) {
      main.classList.remove("lb-role-swap");
      void main.offsetWidth;
      main.classList.add("lb-role-swap");
    }
  }, true);

  var prevTick = tickUi;
  tickUi = function () {
    if (typeof prevTick === "function") prevTick();
    try {
      ensureOfflineBar();
      wireSearch();
      syncFab();
      listSkeleton();
      markNewRows();
    } catch (e) {}
  };


  /* —— دور بعدی UI —— */

  /* 1) دکمه بازگشت به بالا */
  function syncScrollTop() {
    var btn = document.getElementById("lb-scroll-top");
    var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
    if (!main) return;
    if (!btn) {
      btn = document.createElement("button");
      btn.id = "lb-scroll-top";
      btn.type = "button";
      btn.className = "lb-scroll-top";
      btn.setAttribute("aria-label", "برو بالا");
      btn.textContent = "↑";
      btn.hidden = true;
      btn.addEventListener("click", function () {
        main.scrollTo({ top: 0, behavior: "smooth" });
        try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (e) {}
      });
      document.body.appendChild(btn);
      main.addEventListener("scroll", function () {
        btn.hidden = main.scrollTop < 180;
      }, { passive: true });
    }
  }

  /* 2) کپی با لمس طولانی روی متن‌های @ و مبالغ */
  window.lbCopy = function (text) {
    text = String(text || "").trim();
    if (!text) return Promise.resolve(false);
    function ok() {
      if (window.lbToast) window.lbToast("کپی شد");
      try { if (window.lbHaptic) window.lbHaptic("success"); } catch (e) {}
      return true;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(ok).catch(function () {
        return fallback();
      });
    }
    function fallback() {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        return ok();
      } catch (e) {
        return false;
      }
    }
    return Promise.resolve(fallback());
  };
  (function () {
    var timer = 0, target = null, startText = "";
    document.addEventListener("touchstart", function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var el = t.closest("main span, main p, main code, main .text-link, main .font-bold");
      if (!el) return;
      var tx = (el.textContent || "").trim();
      if (tx.length < 2 || tx.length > 80) return;
      if (!/^@/.test(tx) && !/\d/.test(tx) && tx.indexOf("تومان") < 0) return;
      target = el;
      startText = tx;
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (target === el) window.lbCopy(startText);
      }, 520);
    }, { passive: true });
    document.addEventListener("touchend", function () {
      clearTimeout(timer);
      target = null;
    });
    document.addEventListener("touchmove", function () {
      clearTimeout(timer);
      target = null;
    }, { passive: true });
  })();

  /* 3) ریپل روی دکمه‌های اصلی */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("main button.bg-link, main button.bg-ok, .lb-fab");
    if (!btn) return;
    var r = document.createElement("span");
    r.className = "lb-ripple";
    var rect = btn.getBoundingClientRect();
    var size = Math.max(rect.width, rect.height);
    r.style.width = r.style.height = size + "px";
    r.style.left = e.clientX - rect.left - size / 2 + "px";
    r.style.top = e.clientY - rect.top - size / 2 + "px";
    btn.classList.add("lb-ripple-host");
    btn.appendChild(r);
    setTimeout(function () { r.remove(); }, 500);
  }, true);

  /* 4) هزتیک هنگام تعویض تب ناو */
  document.addEventListener("click", function (e) {
    var navBtn = e.target.closest && e.target.closest("nav button");
    if (!navBtn) return;
    try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (err) {}
    var main = document.querySelector("main");
    if (main) {
      main.classList.remove("lb-page-in");
      void main.offsetWidth;
      main.classList.add("lb-page-in");
    }
  }, true);

  /* 5) جلوگیری از دابل‌سابمیت دکمه‌های اصلی */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("main button.bg-link, main button.bg-ok");
    if (!btn || btn.disabled) return;
    if (btn.dataset.lbBusy) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    btn.dataset.lbBusy = "1";
    btn.classList.add("lb-busy");
    setTimeout(function () {
      delete btn.dataset.lbBusy;
      btn.classList.remove("lb-busy");
    }, 900);
  }, true);

  /* 6) پدینگ صفحه هنگام باز شدن کیبورد */
  if (window.visualViewport) {
    var vv = window.visualViewport;
    function onVv() {
      var gap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      document.documentElement.style.setProperty("--lb-kb", gap > 40 ? gap + "px" : "0px");
      document.documentElement.classList.toggle("lb-kb-open", gap > 40);
    }
    vv.addEventListener("resize", onVv);
    vv.addEventListener("scroll", onVv);
    onVv();
  }

  /* 7) فلش موفقیت کوتاه */
  window.lbSuccessFlash = function (msg) {
    var el = document.createElement("div");
    el.className = "lb-success-flash";
    el.innerHTML = '<span class="lb-success-check">✓</span><span></span>';
    el.querySelector("span:last-child").textContent = msg || "انجام شد";
    document.body.appendChild(el);
    try { if (window.lbHaptic) window.lbHaptic("success"); } catch (e) {}
    setTimeout(function () { el.remove(); }, 1600);
  };

  /* 8) کاهش حرکت اگر کاربر خواسته */
  try {
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.documentElement.classList.add("lb-reduce-motion");
    }
  } catch (e) {}

  /* 9) هایلایت لینک‌های @username برای کپی */
  function decorateHandles() {
    document.querySelectorAll("main .text-muted, main .text-sm, main .text-xs").forEach(function (el) {
      if (el.dataset.lbHandle) return;
      var t = el.childNodes.length === 1 && el.firstChild && el.firstChild.nodeType === 3 ? el.textContent : null;
      if (!t || !/^@[A-Za-z0-9_]{3,}$/.test(t.trim())) return;
      el.dataset.lbHandle = "1";
      el.classList.add("lb-handle");
      el.title = "لمس طولانی برای کپی";
    });
  }

  /* 10) وضعیت شبکه ضعیف — اگر fetch طول بکشد */
  window.lbNetWatch = function (ms) {
    var id = "lb-slow-net";
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      el.className = "lb-slow-net";
      el.textContent = "اتصال کند است…";
      el.hidden = true;
      document.body.appendChild(el);
    }
    el.hidden = false;
    clearTimeout(window.__lbSlowT);
    window.__lbSlowT = setTimeout(function () { el.hidden = true; }, ms || 4000);
  };

  var _prevTick2 = tickUi;
  tickUi = function () {
    if (typeof _prevTick2 === "function") _prevTick2();
    try {
      syncScrollTop();
      decorateHandles();
    } catch (e) {}
  };


  /* —— دور بعد UI —— */

  /* 1) بنر خطای سراسری + تلاش دوباره */
  window.lbShowError = function (message, onRetry) {
    var id = "lb-global-error";
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      el.className = "lb-global-error";
      el.innerHTML =
        '<p class="lb-global-error-msg"></p>' +
        '<button type="button" class="lb-global-error-retry">تلاش دوباره</button>' +
        '<button type="button" class="lb-global-error-close" aria-label="بستن">×</button>';
      document.body.appendChild(el);
      el.querySelector(".lb-global-error-close").onclick = function () {
        el.hidden = true;
      };
    }
    el.querySelector(".lb-global-error-msg").textContent = message || "خطایی رخ داد";
    var retry = el.querySelector(".lb-global-error-retry");
    retry.hidden = !onRetry;
    retry.onclick = function () {
      el.hidden = true;
      try { onRetry && onRetry(); } catch (e) {}
    };
    el.hidden = false;
    try { if (window.lbHaptic) window.lbHaptic("error"); } catch (e) {}
  };
  window.lbHideError = function () {
    var el = document.getElementById("lb-global-error");
    if (el) el.hidden = true;
  };

  /* 2) رهگیری fetchهای ناموفق API مینی‌اپ */
  if (!window.__lbFetchPatched && typeof window.fetch === "function") {
    window.__lbFetchPatched = true;
    var _fetch = window.fetch.bind(window);
    window.fetch = function () {
      var args = arguments;
      var url = String((args[0] && args[0].url) || args[0] || "");
      var slow = setTimeout(function () {
        if (window.lbNetWatch) window.lbNetWatch(5000);
      }, 2500);
      return _fetch.apply(null, args).then(function (res) {
        clearTimeout(slow);
        if (!res.ok && url.indexOf("/miniapp/") >= 0 && res.status >= 500) {
          window.lbShowError("سرور پاسخ نداد (" + res.status + ")", function () {
            window.dispatchEvent(new CustomEvent("lb:refresh"));
          });
        }
        return res;
      }).catch(function (err) {
        clearTimeout(slow);
        if (url.indexOf("/miniapp/") >= 0) {
          window.lbShowError("ارتباط برقرار نشد", function () {
            window.dispatchEvent(new CustomEvent("lb:refresh"));
          });
        }
        throw err;
      });
    };
  }

  /* 3) نوار پیشرفت کوچک بالای صفحه */
  window.lbProgress = function (show) {
    var el = document.getElementById("lb-top-progress");
    if (!el) {
      el = document.createElement("div");
      el.id = "lb-top-progress";
      el.className = "lb-top-progress";
      el.innerHTML = '<div class="lb-top-progress-bar"></div>';
      document.body.appendChild(el);
    }
    el.classList.toggle("on", !!show);
    el.hidden = !show;
  };

  /* 4) مخفی کردن FAB هنگام شیت/لایتباکس */
  function syncOverlaysChrome() {
    var open =
      document.getElementById("lb-confirm") ||
      document.getElementById("lb-lightbox") ||
      document.querySelector(".lb-sheet:not([hidden])");
    document.documentElement.classList.toggle("lb-overlay-open", !!open);
  }

  /* 5) ذخیرهٔ موقعیت اسکرول هر صفحه (تقریبی با عنوان) */
  var scrollMap = {};
  try {
    scrollMap = JSON.parse(sessionStorage.getItem("lb.scroll") || "{}");
  } catch (e) {}
  function pageKey() {
    var h = document.querySelector("header h1");
    return h ? (h.textContent || "").trim() : "page";
  }
  function saveScroll() {
    var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
    if (!main) return;
    scrollMap[pageKey()] = main.scrollTop;
    try { sessionStorage.setItem("lb.scroll", JSON.stringify(scrollMap)); } catch (e) {}
  }
  function restoreScroll() {
    var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
    if (!main) return;
    var y = scrollMap[pageKey()];
    if (typeof y === "number" && y > 0) {
      requestAnimationFrame(function () { main.scrollTop = y; });
    }
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("nav button")) {
      saveScroll();
      setTimeout(restoreScroll, 120);
    }
  }, true);

  /* 6) راهنمای یک‌باره فیلتر افقی */
  function filterHint() {
    try {
      if (localStorage.getItem("lb.filterHint") === "1") return;
    } catch (e) {}
    var row = document.querySelector("main .lb-chips, main .flex:has(> button.lb-chip)");
    if (!row || row.dataset.lbHint) return;
    row.dataset.lbHint = "1";
    var tip = document.createElement("div");
    tip.className = "lb-filter-hint";
    tip.textContent = "← برای دیدن بقیه بکشید";
    row.parentElement && row.parentElement.insertBefore(tip, row.nextSibling);
    setTimeout(function () {
      tip.remove();
      try { localStorage.setItem("lb.filterHint", "1"); } catch (e) {}
    }, 3200);
  }

  /* 7) انتقال نرم تم */
  document.documentElement.classList.add("lb-theme-anim");

  /* 8) فوکوس اولین فیلد خطا بعد از submit ناموفق */
  window.lbFocusInvalid = function () {
    var el = document.querySelector("main .lb-input-invalid, main input:invalid");
    if (el && el.focus) {
      el.focus();
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  };

  /* 9) لرزش کوتاه فیلد نامعتبر */
  window.lbShake = function (el) {
    if (!el) return;
    el.classList.remove("lb-shake");
    void el.offsetWidth;
    el.classList.add("lb-shake");
    setTimeout(function () { el.classList.remove("lb-shake"); }, 450);
  };

  /* 10) شمارنده کاراکتر برای textareaهای کپشن */
  function wireCounters() {
    document.querySelectorAll("main textarea").forEach(function (ta) {
      if (ta.dataset.lbCounter) return;
      ta.dataset.lbCounter = "1";
      var max = parseInt(ta.getAttribute("maxlength") || "0", 10);
      var counter = document.createElement("div");
      counter.className = "lb-char-count";
      function upd() {
        var n = (ta.value || "").length;
        counter.textContent = max ? n + " / " + max : n + " نویسه";
        counter.classList.toggle("over", max && n > max);
      }
      ta.addEventListener("input", upd);
      upd();
      if (ta.parentElement) ta.parentElement.appendChild(counter);
    });
  }

  var _prevTick3 = tickUi;
  tickUi = function () {
    if (typeof _prevTick3 === "function") _prevTick3();
    try {
      syncOverlaysChrome();
      filterHint();
      wireCounters();
    } catch (e) {}
  };

})();