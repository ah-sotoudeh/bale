/* پوستهٔ تم، برگهٔ حساب و ترجیح‌های کاربر. منطق سفارش این‌جا نیست. */
(function () {

  function lbSafeRemove(el) {
    try {
      if (!el) return;
      if (typeof el.remove === "function" && el.isConnected !== false) {
        var p = el.parentNode;
        if (p) p.removeChild(el);
        else el.remove();
      }
    } catch (err) {}
  }
  /* cache initData ASAP */
  try {
    var _id = (window.Bale && Bale.WebApp && Bale.WebApp.initData) || (window.Telegram && Telegram.WebApp && Telegram.WebApp.initData) || "";
    if (_id) localStorage.setItem("lb.initData", _id);
    document.addEventListener("DOMContentLoaded", function () {
      try {
        var id2 = (window.Bale && Bale.WebApp && Bale.WebApp.initData) || "";
        if (id2) localStorage.setItem("lb.initData", id2);
      } catch (e) {}
    });
  } catch (e) {}


  /* —— تایم‌لاین وضعیت سفارش (الگوی ad-marketplace) —— */
  var ORDER_STEPS = [
    { key: "waiting_banner", label: "بنر" },
    { key: "waiting_managers", label: "مدیر" },
    { key: "waiting_customer_confirm", label: "تأیید" },
    { key: "waiting_payment", label: "پرداخت" },
    { key: "paid", label: "انتشار" },
    { key: "completed", label: "پایان" },
  ];

  function lbCleanupInputWraps() {
    /* فقط یک‌بار قبل از hydrate؛ جابه‌جایی مداوم با React می‌جنگد */
    if (window.__lbWrapCleaned) return;
    window.__lbWrapCleaned = true;
    try {
      document.querySelectorAll("main .lb-input-wrap").forEach(function (wrap) {
        var inp = wrap.querySelector("input, textarea");
        var parent = wrap.parentNode;
        if (!inp || !parent) {
          lbSafeRemove(wrap);
          return;
        }
        try {
          /* برگرداندن input به parent اصلی و حذف wrap اضافی */
          parent.insertBefore(inp, wrap);
          lbSafeRemove(wrap);
          try { delete inp.dataset.lbClear; } catch (e2) {}
        } catch (e) {}
      });
    } catch (e) {}
  }

  function orderStepIndex(status) {
    for (var i = 0; i < ORDER_STEPS.length; i++) if (ORDER_STEPS[i].key === status) return i;
    if (status === "rejected" || status === "cancelled") return -1;
    return 0;
  }
  function injectOrderTimelines() {
    try {
      document.querySelectorAll("[data-order-status], .lb-order-card, main li").forEach(function (card) {
        if (card.querySelector(".lb-timeline")) return;
        var st =
          card.getAttribute("data-order-status") ||
          card.getAttribute("data-status") ||
          "";
        if (!st) {
          var txt = card.textContent || "";
          if (/منتظر پرداخت/.test(txt)) st = "waiting_payment";
          else if (/منتظر پاسخ مدیر/.test(txt)) st = "waiting_managers";
          else if (/منتظر تأیید بنر/.test(txt)) st = "waiting_banner";
          else if (/پرداخت شد|در حال انتشار/.test(txt)) st = "paid";
          else if (/تمام شد|تکمیل/.test(txt)) st = "completed";
          else return;
        }
        var idx = orderStepIndex(st);
        var tl = document.createElement("div");
        tl.className = "lb-timeline";
        ORDER_STEPS.forEach(function (s, i) {
          var step = document.createElement("div");
          step.className =
            "lb-tl-step" + (idx < 0 ? "" : i < idx ? " done" : i === idx ? " current" : "");
          step.innerHTML = '<span class="lb-tl-dot"></span><span class="lb-tl-lab">' + s.label + "</span>";
          tl.appendChild(step);
        });
        card.appendChild(tl);
      });
    } catch (e) {}
  }

  /* —— فیلتر کاتالوگ مشتری —— */
  function ensureCatalogFilters() {
    try {
      var h1 = document.querySelector("header h1");
      var title = h1 ? (h1.textContent || "").trim() : "";
      var main = document.querySelector("main");
      if (!main) return;
      var isCatalog =
        title === "لینک‌بان" ||
        title === "خانه" ||
        title.indexOf("کانال") >= 0 && document.body.innerText.indexOf("تعرفه") >= 0;
      /* فقط نقش مشتری */
      var roleBtn = document.querySelector("header button.rounded-full.bg-link, .lb-acc-role.on");
      var roleTxt = roleBtn ? (roleBtn.textContent || "") : "";
      var customer =
        /مشتری/.test(roleTxt) ||
        (window.__LB_DEMO_ROLE === "customer") ||
        (!roleTxt && !(window.__LB_DEMO_ROLE === "manager" || window.__LB_DEMO_ROLE === "operator"));
      var bar = document.getElementById("lb-cat-filters");
      if (!customer) {
        if (bar) bar.hidden = true;
        return;
      }
      if (!bar) {
        bar = document.createElement("div");
        bar.id = "lb-cat-filters";
        bar.className = "lb-cat-filters";
        bar.innerHTML =
          '<button type="button" class="lb-cat-chip on" data-f="all">همه</button>' +
          '<button type="button" class="lb-cat-chip" data-f="m10">بالای ۱۰هزار عضو</button>' +
          '<button type="button" class="lb-cat-chip" data-f="m40">بالای ۴۰هزار</button>' +
          '<button type="button" class="lb-cat-chip" data-f="p100">زیر ۱۰۰ هزار تومان</button>' +
          '<button type="button" class="lb-cat-chip" data-f="p200">زیر ۲۰۰ هزار</button>';
        main.insertBefore(bar, main.firstChild);
        bar.addEventListener("click", function (e) {
          var b = e.target.closest("[data-f]");
          if (!b) return;
          bar.querySelectorAll(".lb-cat-chip").forEach(function (x) {
            x.classList.toggle("on", x === b);
          });
          applyCatalogFilter(b.getAttribute("data-f"));
        });
      }
      bar.hidden = false;
    } catch (e) {}
  }
  function applyCatalogFilter(f) {
    document.querySelectorAll("main button.lb-ch-row, main li").forEach(function (row) {
      var t = row.textContent || "";
      var show = true;
      var mem = 0;
      var mk = t.match(/([\\d٫,\\.]+)\\s*k?\\s*عضو/);
      if (mk) {
        var raw = mk[1].replace(/[٫,]/g, ".");
        mem = parseFloat(raw) || 0;
        if (/k/i.test(mk[0])) mem *= 1000;
      }
      /* اعداد فارسی */
      var fa = "۰۱۲۳۴۵۶۷۸۹";
      var eng = t.replace(/[۰-۹]/g, function (d) {
        return String(fa.indexOf(d));
      });
      var priceM = eng.match(/([\\d,]+)\\s*تومان/);
      var price = priceM ? parseInt(priceM[1].replace(/,/g, ""), 10) : 0;
      if (f === "m10") show = mem >= 10000;
      if (f === "m40") show = mem >= 40000;
      if (f === "p100") show = price > 0 && price < 100000;
      if (f === "p200") show = price > 0 && price < 200000;
      row.style.display = show ? "" : "none";
    });
  }

  /* tick: timeline + filters */
  var _tickUi = typeof tickUi === "function" ? tickUi : null;

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
    if (!header) return;
    var row = header.querySelector(":scope > div");
    if (!row) return;
    row.classList.add("lb-header-row");
    if (header.querySelector("button.tt")) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tt";
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">' +
      '<mask id="lb-tt-m"><rect width="24" height="24" fill="#fff"/><circle class="tt-cut" cx="8" cy="8" r="7" fill="#000"/></mask>' +
      '<circle class="tt-core" cx="13" cy="13" r="8.5" fill="currentColor" mask="url(#lb-tt-m)"/>' +
      '<g class="tt-rays" fill="currentColor">' + rays() + "</g>" +
      '<g class="tt-stars" fill="currentColor">' +
      '<path d="M4.5 2.2l.55 1.35 1.35.55-1.35.55-.55 1.35-.55-1.35L2.6 4.1l1.35-.55z"/>' +
      '<path d="M9.2 1l.35.85.85.35-.85.35-.35.85-.35-.85-.85-.35.85-.35z"/>' +
      "</g></svg>";
    paintButton(btn);
    btn.addEventListener("click", toggle);
    /* سمت راست بصری */
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
    var u = getBaleUser ? getBaleUser() : null;
    if (!u) {
      try {
        var w = window.Bale && Bale.WebApp;
        u = w && w.initDataUnsafe && w.initDataUnsafe.user;
      } catch (e) {}
    }
    var name = u
      ? [u.first_name || u.firstName || "", u.last_name || u.lastName || ""].join(" ").trim() || (u.username ? "@" + u.username : "کاربر")
      : "کاربر";
    var uname = u && u.username ? "@" + u.username : "";
    var initials = (typeof userInitials === "function") ? userInitials(u) : "؟";
    var photo = u && (u.photo_url || u.photoUrl);

    /* نقش‌ها از store/me — هدر نقش‌ها را مخفی کردیم */
    var me = window.__lbMe || {};
    var curRole = me.role || "customer";
    try {
      curRole = localStorage.getItem("lb_role") || curRole;
    } catch (e) {}
    var roleDefs = [
      { id: "customer", label: "مشتری" },
      { id: "manager", label: "کانال‌دار" },
    ];
    if (me.isOperator || me.debug) {
      roleDefs.push({ id: "operator", label: "پشتیبانی" });
    }
    var rolesHtml = '<p class="lb-acc-label">نقش فعال</p><div class="lb-acc-roles">';
    roleDefs.forEach(function (r) {
      rolesHtml +=
        '<button type="button" class="lb-acc-role' + (r.id === curRole ? " on" : "") + '" data-role-id="' + r.id + '">' +
        r.label +
        "</button>";
    });
    rolesHtml += "</div>";
    var roleBtns = roleDefs; /* for click handler length check */

    back.innerHTML =
      '<div class="lb-sheet" role="dialog" aria-label="حساب شما">' +
      '<div class="lb-handle"></div>' +
      '<div class="lb-acc-head">' +
      (photo
        ? '<img class="lb-acc-photo" src="' + photo + '" alt="" />'
        : '<div class="lb-acc-photo lb-acc-photo-fallback">' + initials + "</div>") +
      '<div class="lb-acc-meta"><div class="lb-acc-name"></div><div class="lb-acc-user"></div></div>' +
      "</div>" +
      rolesHtml +
      '<a class="row" href="/miniapp/rules/">شرایط و قوانین</a>' +
      '<button type="button" class="row" id="lb-font-sm">اندازه متن: کوچک</button>' +
      '<button type="button" class="row" id="lb-font-md">اندازه متن: متوسط</button>' +
      '<button type="button" class="row" id="lb-font-lg">اندازه متن: بزرگ</button>' +
      (manual ? '<button type="button" class="row" id="lb-theme-reset">هم‌رنگ گفتگوی بله</button>' : "") +
      '<p class="lb-acc-foot">اگر جایی ماندید، در گفتگو به پشتیبانی بگویید.</p>' +
      "</div>";
    back.addEventListener("click", function (ev) {
      if (ev.target === back) closeSheet();
    });
    document.body.appendChild(back);
    var nameEl = back.querySelector(".lb-acc-name");
    var userEl = back.querySelector(".lb-acc-user");
    if (nameEl) nameEl.textContent = name;
    if (userEl) userEl.textContent = uname;

    back.querySelectorAll("[data-role-id]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var rid = btn.getAttribute("data-role-id");
        if (!rid) return;
        try {
          localStorage.setItem("lb_role", rid);
          localStorage.setItem("lb_role_chosen", "1");
        } catch (e) {}
        var applied = false;
        try {
          if (typeof window.__lbSetRole === "function") {
            window.__lbSetRole(rid);
            applied = true;
          }
        } catch (e) {}
        closeSheet();
        try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (e) {}
        if (!applied) {
          try { location.reload(); } catch (e2) {}
        }
      });
    });

    function bindFont(id, level) {
      var b = document.getElementById(id);
      if (b) b.addEventListener("click", function () {
        if (window.lbSetFontScale) window.lbSetFontScale(level);
        if (window.lbToast) window.lbToast("اندازه متن تنظیم شد");
        closeSheet();
      });
    }
    bindFont("lb-font-sm", "sm");
    bindFont("lb-font-md", "md");
    bindFont("lb-font-lg", "lg");

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

  function getBaleUser() {
    try {
      var w = window.Bale && Bale.WebApp;
      var u = (w && w.initDataUnsafe && w.initDataUnsafe.user) || (w && w.initDataUnsafe) || null;
      if (u && u.user) u = u.user;
      return u || null;
    } catch (e) {
      return null;
    }
  }

  function userInitials(u) {
    if (!u) return "؟";
    var a = (u.first_name || u.firstName || "").trim();
    var b = (u.last_name || u.lastName || "").trim();
    if (a || b) return ((a[0] || "") + (b[0] || "")).toUpperCase() || a.slice(0, 2);
    if (u.username) return String(u.username).slice(0, 2).toUpperCase();
    return "من";
  }

  function ensureAvatar() {
    var header = document.querySelector("header");
    if (!header) return;

    /* مخفی سوییچ نقش */
    header.querySelectorAll(":scope > div.px-3").forEach(function (row) {
      row.classList.add("lb-roles-hidden");
    });
    header.querySelectorAll("div").forEach(function (row) {
      var btns = row.querySelectorAll("button.rounded-full");
      if (btns.length >= 2 && btns.length <= 4) {
        var txt = row.textContent || "";
        if (/پشتیبانی|کانال|مشتری/.test(txt)) row.classList.add("lb-roles-hidden");
      }
    });

    /* اگر از هاست ثابت قبلی مانده، حذف کن */
    var fixed = document.getElementById("lb-user-avatar-btn");
    if (fixed && fixed.classList.contains("lb-user-avatar-fixed")) {
      try { fixed.parentNode && fixed.parentNode.removeChild(fixed); } catch (e) {}
    }

    if (header.querySelector(".lb-user-avatar")) return;
    var h1 = header.querySelector("h1");
    if (!h1 || !h1.parentElement) return;
    var row = h1.parentElement;
    row.classList.add("lb-header-row");
    h1.classList.add("lb-header-title");

    var u = getBaleUser();
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "lb-user-avatar";
    btn.setAttribute("aria-label", "حساب و تنظیمات");
    var photo = u && (u.photo_url || u.photoUrl);
    if (photo) {
      var img = document.createElement("img");
      img.src = photo;
      img.alt = "";
      btn.appendChild(img);
    } else {
      var span = document.createElement("span");
      span.className = "lb-user-avatar-initials";
      span.textContent = userInitials(u);
      btn.appendChild(span);
    }
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (window.lbOpenAccount) window.lbOpenAccount();
      try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (err) {}
    });
    /* فقط insert — تم را جابه‌جا نکن (باعث removeChild می‌شد) */
    row.insertBefore(btn, row.firstChild);
  }

  function ensureLogo() {
    ensureAvatar();
  }

  function isLoadingParagraph(p) {
    if (!p || !p.isConnected) return false;
    var t = (p.textContent || "").trim();
    return t.indexOf("در حال خواندن") >= 0 || t.indexOf("در حال بارگذاری") >= 0;
  }

  function syncSkeletons() {
    // فقط پاک‌سازی اسکلت‌های یتیم — دیگر داخل درخت React چیزی تزریق نکن
    document.querySelectorAll(".lb-skeleton-stack, .lb-list-skeleton").forEach(function (sk) {
      lbSafeRemove(sk);
    });
  }

  function enhanceEmptyNotes() {
    /* disabled — inject into React tree caused removeChild */
    return;
  }

  var tickScheduled = false;
  function tickUi() {
    if (tickScheduled) return;
    tickScheduled = true;
    requestAnimationFrame(function () {
      tickScheduled = false;
      try {
        lbCleanupInputWraps();
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
      fab.addEventListener("click", function (ev) {
        ev.preventDefault();
        try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (e) {}
        var btns = document.querySelectorAll("nav button");
        for (var i = 0; i < btns.length; i++) {
          if ((btns[i].textContent || "").indexOf("بنر") >= 0) {
            btns[i].click();
            break;
          }
        }
        /* بعد از کلیک همان جایگاه ثابت بماند */
        fab.style.left = "16px";
        fab.style.right = "auto";
        fab.style.insetInlineStart = "16px";
        fab.style.insetInlineEnd = "auto";
      });
      document.body.appendChild(fab);
    }
    fab.hidden = false;
    fab.style.left = "16px";
    fab.style.right = "auto";
    fab.style.insetInlineStart = "16px";
    fab.style.insetInlineEnd = "auto";
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
    /* اسکلت لیست را غیرفعال کردیم — با React تداخل و خطای removeChild می‌داد */
    var main = document.querySelector("main");
    if (!main) return;
    var existing = main.querySelector(".lb-list-skeleton");
    if (existing) lbSafeRemove(existing);
  }

  /* 6) نشان «جدید» — اگر ردیف سفارش تازه در DOM آمد */
  function markNewRows() {
    /* نشان «جدید» فقط از دادهٔ API روی فهرست مشتری (is_new) — نه تزریق عمومی */
    document.querySelectorAll(".lb-new-badge:not(.lb-new-real)").forEach(function (b) {
      lbSafeRemove(b);
    });
  }
  window.__lbMarkNew = false;

  /* 10) انیمیشن تعویض نقش */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("header button.rounded-full, .lb-acc-role");
    if (!btn) return;
    var main = document.querySelector("main");
    if (main) {
      main.classList.add("lb-role-swap");
      setTimeout(function () { main.classList.remove("lb-role-swap"); }, 280);
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

  /* 2) پایش fetch — فقط شمارش خطا، بدون مزاحمت برای کاربر عادی */
  if (!window.__lbFetchPatched && typeof window.fetch === "function") {
    window.__lbFetchPatched = true;
    var _fetch = window.fetch.bind(window);
    var _failCount = 0;
    window.fetch = function () {
      var args = arguments;
      var url = String((args[0] && args[0].url) || args[0] || "");
      return _fetch.apply(null, args).then(function (res) {
        if (url.indexOf("/miniapp/api") >= 0 && res.status >= 500) {
          _failCount++;
          /* فقط بعد از ۳ خطای ۵۰۰ متوالی پیام بده */
          if (_failCount >= 3) {
            _failCount = 0;
            if (window.lbShowError) {
              console.warn("lb api 5xx"); if(false) window.lbShowError("سرور پاسخ نداد", function () {
                window.dispatchEvent(new CustomEvent("lb:refresh"));
              });
            }
          }
        } else if (res.ok) {
          _failCount = 0;
          if (window.lbHideError) window.lbHideError();
        }
        return res;
      }).catch(function (err) {
        /* خطای شبکه prefs و غیره را بی‌صدا نادیده بگیر مگر چندبار پشت‌سرهم */
        _failCount++;
        if (_failCount >= 5 && url.indexOf("/miniapp/api") >= 0) {
          _failCount = 0;
          if (window.lbShowError) {
            console.warn("lb network"); if(false) window.lbShowError("ارتباط برقرار نشد", function () {
              window.dispatchEvent(new CustomEvent("lb:refresh"));
            });
          }
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


  /* —— ۲۰ بهبود بعدی —— */

  /* 1) تاریخ نسبی ساده روی متن‌های «دقایق پیش» اگر data-ts باشد */
  window.lbRelativeTime = function (ts) {
    var d = typeof ts === "number" ? ts : Date.parse(ts);
    if (!d) return "";
    var sec = Math.round((Date.now() - d) / 1000);
    if (sec < 60) return "همین الان";
    if (sec < 3600) return Math.floor(sec / 60) + " دقیقه پیش";
    if (sec < 86400) return Math.floor(sec / 3600) + " ساعت پیش";
    if (sec < 604800) return Math.floor(sec / 86400) + " روز پیش";
    return new Date(d).toLocaleDateString("fa-IR");
  };

  /* 2) فرمت عدد فارسی */
  window.lbFaNum = function (n) {
    try {
      return Number(n).toLocaleString("fa-IR");
    } catch (e) {
      return String(n);
    }
  };

  /* 3) قفل اسکرول بدنه هنگام اورلی */
  function lockBodyScroll(lock) {
    document.documentElement.classList.toggle("lb-scroll-lock", !!lock);
  }
  var _syncOv = typeof syncOverlaysChrome === "function" ? syncOverlaysChrome : function () {};
  syncOverlaysChrome = function () {
    _syncOv();
    var open =
      document.getElementById("lb-confirm") ||
      document.getElementById("lb-lightbox") ||
      document.getElementById("lb-global-error") && !document.getElementById("lb-global-error").hidden;
    lockBodyScroll(!!open);
  };

  /* 4) دکمه اشتراک لینک صفحه (در صورت وجود) */
  window.lbShare = function (title, url) {
    url = url || location.href;
    title = title || document.title || "لینک‌بان";
    if (navigator.share) {
      return navigator.share({ title: title, url: url }).catch(function () {});
    }
    return window.lbCopy(url);
  };

  /* 5) ویبره کوتاه موفقیت روی فرم‌های ok toast */
  var _toast = window.lbToast;
  if (typeof _toast === "function") {
    window.lbToast = function (text) {
      _toast(text);
      var t = String(text || "");
      if (/شد|ثبت|موفق|کپی|انجام/.test(t)) {
        try { if (window.lbHaptic) window.lbHaptic("success"); } catch (e) {}
      }
    };
  }

  /* 6) نشان اتصال دوباره بعد از آفلاین */
  window.addEventListener("online", function () {
    if (window.lbToast) window.lbToast("اتصال برقرار شد");
    try { if (window.lbHaptic) window.lbHaptic("success"); } catch (e) {}
  });

  /* 7) جلوگیری از زوم دابل‌تپ iOS روی کنترل‌ها */
  document.addEventListener("dblclick", function (e) {
    if (e.target.closest && e.target.closest("button, a, nav, header")) {
      e.preventDefault();
    }
  }, { passive: false });

  /* 8) کلاس صفحه فعلی روی html از روی h1 */
  function syncPageClass() {
    var h = document.querySelector("header h1");
    var t = h ? (h.textContent || "").trim() : "";
    document.documentElement.dataset.page = t || "";
  }

  /* 9) هایلایت ردیف تازه با فلش سبز */
  window.lbHighlightRow = function (el) {
    if (!el) return;
    el.classList.add("lb-row-flash");
    setTimeout(function () { el.classList.remove("lb-row-flash"); }, 1200);
  };

  /* 10) میانبر کیبورد: Escape بستن اورلی */
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var lb = document.getElementById("lb-lightbox");
    if (lb) { lb.remove(); return; }
    var c = document.getElementById("lb-confirm");
    if (c) { c.remove(); return; }
    if (window.lbHideError) window.lbHideError();
  });

  /* 11) اسکلت دکمه‌ای برای اکشن در حال انجام */
  window.lbButtonLoading = function (btn, on) {
    if (!btn) return;
    if (on) {
      btn.dataset.lbLabel = btn.textContent;
      btn.classList.add("lb-btn-loading");
      btn.disabled = true;
      btn.textContent = "…";
    } else {
      btn.classList.remove("lb-btn-loading");
      btn.disabled = false;
      if (btn.dataset.lbLabel) btn.textContent = btn.dataset.lbLabel;
    }
  };

  /* 12) تشخیص تم سیستم و پیشنهاد */
  try {
    if (!localStorage.getItem("lb.theme") && window.matchMedia) {
      var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      /* فقط اگر کاربر دستی تنظیم نکرده — shell تم را از قبل مدیریت می‌کند */
      document.documentElement.dataset.systemTheme = prefersDark ? "dark" : "light";
    }
  } catch (e) {}

  /* 13) لمس بیرون برای بستن منوی حساب اگر باز باشد */
  document.addEventListener("click", function (e) {
    var sheet = document.querySelector(".lb-sheet, [data-lb-sheet]");
    if (!sheet) return;
  }, true);

  /* 14) نشان «در حال ذخیره» کوچک */
  window.lbSaving = function (on) {
    var el = document.getElementById("lb-saving");
    if (!el) {
      el = document.createElement("div");
      el.id = "lb-saving";
      el.className = "lb-saving";
      el.textContent = "در حال ذخیره…";
      document.body.appendChild(el);
    }
    el.hidden = !on;
  };

  /* 15) بهبود دسترسی: aria-live برای toast */
  (function () {
    var live = document.getElementById("lb-aria-live");
    if (!live) {
      live = document.createElement("div");
      live.id = "lb-aria-live";
      live.className = "lb-aria-live";
      live.setAttribute("aria-live", "polite");
      live.setAttribute("role", "status");
      document.body.appendChild(live);
    }
    var _t = window.lbToast;
    if (typeof _t === "function") {
      window.lbToast = function (text) {
        _t(text);
        live.textContent = text || "";
      };
    }
  })();

  /* 16) لود تنبل تصاویر داخل main */
  function lazyImages() {
    document.querySelectorAll("main img[src]:not([data-lb-lazy])").forEach(function (img) {
      img.dataset.lbLazy = "1";
      img.loading = "lazy";
      img.decoding = "async";
    });
  }

  /* 17) حاشیه امن برای FAB تا با scroll-top تداخل نکند */
  function layoutFabs() {
    var fab = document.getElementById("lb-fab");
    var top = document.getElementById("lb-scroll-top");
    if (fab) {
      fab.style.left = "16px";
      fab.style.right = "auto";
    }
    if (fab && top && !fab.hidden && !top.hidden) {
      top.style.bottom = "calc(180px + env(safe-area-inset-bottom))";
    } else if (top) {
      top.style.bottom = "";
    }
  }

  /* 18) پیش‌نمایش خالی تصویر شکسته */
  document.addEventListener("error", function (e) {
    var t = e.target;
    if (t && t.tagName === "IMG" && t.closest("main")) {
      t.classList.add("lb-img-broken");
      t.alt = t.alt || "تصویر در دسترس نیست";
    }
  }, true);

  /* 19) کلاس compact برای صفحات شلوغ */
  function syncCompact() {
    var main = document.querySelector("main");
    if (!main) return;
    var n = main.querySelectorAll(".rounded-2xl.bg-surface").length;
    main.classList.toggle("lb-compact", n > 6);
  }

  /* 20) انیمیشن شمارش موجودی (اگر data-lb-count) */
  window.lbAnimateNumber = function (el, to) {
    if (!el) return;
    var from = parseInt(String(el.textContent).replace(/[^\d-]/g, ""), 10) || 0;
    to = Number(to) || 0;
    var steps = 12, i = 0;
    var timer = setInterval(function () {
      i++;
      var v = Math.round(from + (to - from) * (i / steps));
      el.textContent = window.lbFaNum ? window.lbFaNum(v) : String(v);
      if (i >= steps) clearInterval(timer);
    }, 30);
  };

  var _prevTick4 = tickUi;
  tickUi = function () {
    if (typeof _prevTick4 === "function") _prevTick4();
    try {
      syncPageClass();
      lazyImages();
      layoutFabs();
      syncCompact();
      syncOverlaysChrome();
    } catch (e) {}
  };


  /* —— ۲۰ بهبود بعدی (دور تازه) —— */

  /* 1) کپی سریع با دابل‌کلیک روی مبلغ/شناسه */
  document.addEventListener("dblclick", function (e) {
    var el = e.target.closest && e.target.closest("main .font-bold, main .text-link, main code");
    if (!el) return;
    var t = (el.textContent || "").trim();
    if (t.length >= 2 && t.length <= 64 && window.lbCopy) window.lbCopy(t);
  });

  /* 2) نشان «در حال ارسال» روی submit */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || form.tagName !== "FORM") return;
    var btn = form.querySelector("button[type=submit], button.bg-link");
    if (btn && window.lbButtonLoading) window.lbButtonLoading(btn, true);
  }, true);

  /* 3) ذخیره پیش‌نویس textarea در sessionStorage */
  function wireDrafts() {
    document.querySelectorAll("main textarea[name], main textarea[id]").forEach(function (ta) {
      if (ta.dataset.lbDraft) return;
      ta.dataset.lbDraft = "1";
      var key = "lb.draft." + (ta.name || ta.id || "ta");
      try {
        var saved = sessionStorage.getItem(key);
        if (saved && !ta.value) ta.value = saved;
      } catch (e) {}
      ta.addEventListener("input", function () {
        try { sessionStorage.setItem(key, ta.value || ""); } catch (e) {}
      });
    });
  }
  window.lbClearDraft = function (name) {
    try { sessionStorage.removeItem("lb.draft." + name); } catch (e) {}
  };

  /* 4) هشدار خروج اگر پیش‌نویس دارد */
  window.addEventListener("beforeunload", function (e) {
    try {
      for (var i = 0; i < sessionStorage.length; i++) {
        var k = sessionStorage.key(i);
        if (k && k.indexOf("lb.draft.") === 0 && sessionStorage.getItem(k)) {
          e.preventDefault();
          e.returnValue = "";
          return;
        }
      }
    } catch (err) {}
  });

  /* 5) فوکوس تله داخل confirm sheet */
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Tab") return;
    var sheet = document.querySelector("#lb-confirm .lb-confirm-sheet");
    if (!sheet) return;
    var focusables = sheet.querySelectorAll("button");
    if (!focusables.length) return;
    var first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });

  /* 6) اسکرول به لنگر داخلی */
  window.lbScrollTo = function (sel) {
    var el = typeof sel === "string" ? document.querySelector(sel) : sel;
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.add("lb-row-flash");
    setTimeout(function () { el.classList.remove("lb-row-flash"); }, 1000);
  };


  /* ─── آنبوردینگ: نقش + ثبت کسب‌وکار (منطق چاوش/پنجره، تم لینک‌بان) ─── */
  var __lbOb = { step: 'role', role: '', biz: { name: '', category: '', mode: '', region: '', url: '' } };

  var LB_OB_CATS = [
    'آموزش زبان خارجی', 'آموزش فنی و حرفه‌ای', 'آموزش کامپیوتر و فناوری',
    'فروشگاه اینترنتی', 'خدمات زیبایی و سلامت', 'املاک', 'خودرو و وسایل نقلیه',
    'کالای دیجیتال', 'خانه و آشپزخانه', 'خدمات کسب‌وکار', 'سرگرمی و رسانه',
    'غذا و رستوران', 'پوشاک و مد', 'مسافرت و گردشگری', 'سایر'
  ];

  function lbObDone() {
    try {
      if (localStorage.getItem('lb_role_chosen') === '1') {
        var biz = null;
        try { biz = JSON.parse(localStorage.getItem('lb_business') || 'null'); } catch (e) {}
        var role = localStorage.getItem('lb_role') || '';
        if (role === 'manager' || role === 'operator') return true;
        if (role === 'customer' && biz && biz.name) return true;
        if (role === 'customer' && !biz) return false;
      }
    } catch (e) {}
    return false;
  }

  function lbObSaveLocal() {
    try {
      localStorage.setItem('lb_role', __lbOb.role);
      localStorage.setItem('lb_role_chosen', '1');
      if (__lbOb.role === 'customer' && __lbOb.biz.name) {
        localStorage.setItem('lb_business', JSON.stringify(__lbOb.biz));
      }
    } catch (e) {}
    try {
      if (typeof window.__lbSetRole === 'function') window.__lbSetRole(__lbOb.role);
    } catch (e) {}
  }

  function lbObSaveServer() {
    var payload = { onboarded: {} };
    payload.onboarded[__lbOb.role] = true;
    if (__lbOb.role === 'customer' && __lbOb.biz.name) {
      payload.business = __lbOb.biz;
    }
    var headers = { 'Content-Type': 'application/json' };
    try {
      if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
        headers['X-Bale-Init-Data'] = window.Telegram.WebApp.initData;
      }
    } catch (e) {}
    try {
      var q = new URLSearchParams(location.search);
      if (q.get('debug_bale_id')) headers['X-Debug-Bale-Id'] = q.get('debug_bale_id');
    } catch (e) {}
    fetch('/miniapp/api/me/prefs', {
      method: 'POST',
      headers: headers,
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).catch(function () {});
  }

  function lbObClose() {
    var el = document.getElementById('lb-ob-root');
    if (el) el.remove();
    document.documentElement.classList.remove('lb-ob-lock');
  }

  function lbObRender() {
    if (lbObDone()) { lbObClose(); return; }
    document.documentElement.classList.add('lb-ob-lock');
    var root = document.getElementById('lb-ob-root');
    if (!root) {
      root = document.createElement('div');
      root.id = 'lb-ob-root';
      root.className = 'lb-ob-root';
      document.body.appendChild(root);
    }
    var step = __lbOb.step;
    var progress = 10;
    if (step === 'role') progress = 15;
    else if (step === 'name') progress = 35;
    else if (step === 'category') progress = 55;
    else if (step === 'mode') progress = 75;
    else if (step === 'region') progress = 90;
    else if (step === 'done') progress = 100;

    var html = '<div class="lb-ob-progress"><i style="width:' + progress + '%"></i></div><div class="lb-ob-body">';

    if (step === 'role') {
      html +=
        '<div class="lb-ob-title">چطور می‌خواهید از لینک‌بان استفاده کنید؟</div>' +
        '<p class="lb-ob-sub">نقش خود را انتخاب کنید. هر وقت بخواهید می‌توانید بین نقش‌ها جابه‌جا شوید.</p>' +
        '<div class="lb-ob-cards">' +
        '<button type="button" class="lb-ob-card" data-ob="role-customer">' +
        '<div class="ico">📣</div><h3>آگهی‌دهنده (کسب‌وکار)</h3>' +
        '<p>اگر محصول یا خدمتی دارید و می‌خواهید در کانال‌های بله دیده شوید، این نقش را انتخاب کنید.</p></button>' +
        '<button type="button" class="lb-ob-card" data-ob="role-manager">' +
        '<div class="ico">📡</div><h3>مدیر کانال (ناشر)</h3>' +
        '<p>اگر کانال بله دارید و می‌خواهید با انتشار تبلیغ درآمد بگیرید، این نقش مناسب شماست.</p></button>' +
        '</div>';
    } else if (step === 'name') {
      html +=
        '<div class="lb-ob-title">نام کسب‌وکارتان چیست؟</div>' +
        '<p class="lb-ob-sub">نامی وارد کنید که مشتری‌ها شما را با آن می‌شناسند.</p>' +
        '<div class="lb-ob-field"><label>نام کسب‌وکار</label>' +
        '<input id="lb-ob-name" type="text" maxlength="80" placeholder="مثلاً طیبستان" value="' +
        (__lbOb.biz.name || '').replace(/"/g, '&quot;') + '" /></div>';
    } else if (step === 'category') {
      html +=
        '<div class="lb-ob-title">صنف فعالیت‌تان چیست؟</div>' +
        '<p class="lb-ob-sub">نزدیک‌ترین صنف به کسب‌وکارتان را انتخاب کنید.</p>' +
        '<div class="lb-ob-field lb-ob-search"><input id="lb-ob-cat-q" type="search" placeholder="جستجوی صنف…" /></div>' +
        '<div class="lb-ob-cats" id="lb-ob-cats"></div>';
    } else if (step === 'mode') {
      html +=
        '<div class="lb-ob-title">کسب‌وکارتان چطور فعالیت می‌کند؟</div>' +
        '<p class="lb-ob-sub">این اطلاعات کمک می‌کند پیشنهادهای دقیق‌تری بدهیم.</p>' +
        '<div class="lb-ob-opts">' +
        '<button type="button" class="lb-ob-opt' + (__lbOb.biz.mode === 'offline' ? ' on' : '') + '" data-ob="mode-offline"><span class="radio"></span><div><b>حضوری</b><span>مشتری‌ها به محل کسب‌وکارتان می‌آیند</span></div></button>' +
        '<button type="button" class="lb-ob-opt' + (__lbOb.biz.mode === 'online' ? ' on' : '') + '" data-ob="mode-online"><span class="radio"></span><div><b>آنلاین</b><span>از طریق سایت، اینستاگرام یا پیام‌رسان می‌فروشید</span></div></button>' +
        '<button type="button" class="lb-ob-opt' + (__lbOb.biz.mode === 'both' ? ' on' : '') + '" data-ob="mode-both"><span class="radio"></span><div><b>هر دو</b><span>محل حضوری دارید و آنلاین هم می‌فروشید</span></div></button>' +
        '</div>';
      if (__lbOb.biz.mode === 'online' || __lbOb.biz.mode === 'both') {
        html +=
          '<div class="lb-ob-field" style="margin-top:14px"><label>آدرس اینترنتی کسب‌وکار (اختیاری)</label>' +
          '<input id="lb-ob-url" type="text" placeholder="instagram.com/yourpage" value="' +
          (__lbOb.biz.url || '').replace(/"/g, '&quot;') + '" /></div>';
      }
    } else if (step === 'region') {
      html +=
        '<div class="lb-ob-title">محدوده فعالیت کسب‌وکارتان کجاست؟</div>' +
        '<p class="lb-ob-sub">به مشتری‌های کدام شهرها خدمت می‌دهید؟</p>' +
        '<div class="lb-ob-opts">' +
        '<button type="button" class="lb-ob-opt' + (__lbOb.biz.region === 'all' ? ' on' : '') + '" data-ob="region-all"><span class="radio"></span><div><b>سراسر ایران</b><span>بدون محدودیت جغرافیایی</span></div></button>' +
        '<button type="button" class="lb-ob-opt' + (__lbOb.biz.region === 'cities' ? ' on' : '') + '" data-ob="region-cities"><span class="radio"></span><div><b>یک یا چند شهر</b><span>فعلاً می‌توانید بعداً شهرها را تکمیل کنید</span></div></button>' +
        '</div>';
    } else if (step === 'done') {
      var letter = (__lbOb.biz.name || 'ک').slice(0, 1);
      html +=
        '<div class="lb-ob-success">' +
        '<div class="check">✓</div>' +
        '<div class="lb-ob-title">کسب‌وکارتان با موفقیت ثبت شد</div>' +
        '<div class="lb-ob-biz-chip"><span class="ava">' + letter + '</span><div style="text-align:start"><b>' +
        (__lbOb.biz.name || '') + '</b><div style="font-size:12px;color:#64748b">' +
        (__lbOb.biz.category || '') + '</div></div></div>' +
        '<p class="lb-ob-sub">از اینجا می‌توانید اطلاعات را کامل کنید و برای رشد و تبلیغات اقدام کنید.</p>' +
        '</div>';
    }

    html += '</div><div class="lb-ob-foot">';
    if (step === 'role') {
      html += '';
    } else if (step === 'done') {
      html += '<button type="button" class="lb-ob-btn" data-ob="finish">شروع رشد و تبلیغات</button>';
      html += '<button type="button" class="lb-ob-btn ghost" data-ob="finish">ورود به برنامه</button>';
    } else {
      var can = true;
      if (step === 'name') can = !!(__lbOb.biz.name && __lbOb.biz.name.trim());
      if (step === 'category') can = !!__lbOb.biz.category;
      if (step === 'mode') can = !!__lbOb.biz.mode;
      if (step === 'region') can = !!__lbOb.biz.region;
      html += '<button type="button" class="lb-ob-btn" data-ob="next"' + (can ? '' : ' disabled') + '>ادامه</button>';
      html += '<button type="button" class="lb-ob-btn ghost" data-ob="back">قبلی</button>';
    }
    html += '</div>';
    root.innerHTML = html;

    if (step === 'category') {
      var box = document.getElementById('lb-ob-cats');
      function paintCats(q) {
        q = (q || '').trim();
        box.innerHTML = '';
        LB_OB_CATS.filter(function (c) { return !q || c.indexOf(q) >= 0; }).forEach(function (c) {
          var b = document.createElement('button');
          b.type = 'button';
          b.textContent = c;
          if (c === __lbOb.biz.category) b.className = 'on';
          b.onclick = function () {
            __lbOb.biz.category = c;
            lbObRender();
          };
          box.appendChild(b);
        });
      }
      paintCats('');
      var sq = document.getElementById('lb-ob-cat-q');
      if (sq) sq.oninput = function () { paintCats(sq.value); };
    }

    root.onclick = function (e) {
      var btn = e.target.closest('[data-ob]');
      if (!btn) return;
      var act = btn.getAttribute('data-ob');
      if (act === 'role-customer') {
        __lbOb.role = 'customer';
        __lbOb.step = 'name';
        lbObRender();
      } else if (act === 'role-manager') {
        __lbOb.role = 'manager';
        __lbOb.biz = { name: '', category: '', mode: '', region: '', url: '' };
        lbObSaveLocal();
        lbObSaveServer();
        lbObClose();
      } else if (act.indexOf('mode-') === 0) {
        __lbOb.biz.mode = act.slice(5);
        lbObRender();
      } else if (act.indexOf('region-') === 0) {
        __lbOb.biz.region = act.slice(7);
        lbObRender();
      } else if (act === 'next') {
        if (step === 'name') {
          var inp = document.getElementById('lb-ob-name');
          __lbOb.biz.name = (inp && inp.value || '').trim();
          if (!__lbOb.biz.name) return;
          __lbOb.step = 'category';
        } else if (step === 'category') {
          if (!__lbOb.biz.category) return;
          __lbOb.step = 'mode';
        } else if (step === 'mode') {
          if (!__lbOb.biz.mode) return;
          var u = document.getElementById('lb-ob-url');
          if (u) __lbOb.biz.url = (u.value || '').trim();
          __lbOb.step = 'region';
        } else if (step === 'region') {
          if (!__lbOb.biz.region) return;
          __lbOb.step = 'done';
          lbObSaveLocal();
          lbObSaveServer();
        }
        lbObRender();
      } else if (act === 'back') {
        if (step === 'name') __lbOb.step = 'role';
        else if (step === 'category') __lbOb.step = 'name';
        else if (step === 'mode') __lbOb.step = 'category';
        else if (step === 'region') __lbOb.step = 'mode';
        lbObRender();
      } else if (act === 'finish') {
        lbObClose();
      }
    };
  }

  function ensureOnboarding() {
    try {
      if (lbObDone()) { lbObClose(); return; }
      lbObRender();
    } catch (e) {}
  }

  /* جستجوی کاتالوگ: فقط کلاس */
  function enhanceCatSearch() {
    try {
      document.querySelectorAll("main input[placeholder*='جست‌وجو'], main input[placeholder*='جستجو'], input.lb-cat-search").forEach(function (inp) {
        inp.classList.add("lb-cat-search");
      });
    } catch (e) {}
  }

  function isCustomerCatalog() {
    return !!(document.querySelector("main .lb-filter-row") && document.querySelector("main input.lb-cat-search, main input[placeholder*='جست']"));
  }

  function closeLbSheet() {
    var el = document.getElementById("lb-sheet");
    if (el) el.remove();
  }

  function openLbSheet(title, bodyBuild) {
    closeLbSheet();
    var back = document.createElement("div");
    back.id = "lb-sheet";
    back.className = "lb-sheet-back";
    var sheet = document.createElement("div");
    sheet.className = "lb-sheet";
    var hd = document.createElement("div");
    hd.className = "lb-sheet-hd";
    var tit = document.createElement("span");
    tit.textContent = title;
    var x = document.createElement("button");
    x.type = "button";
    x.setAttribute("aria-label", "بستن");
    x.textContent = "×";
    x.onclick = closeLbSheet;
    hd.appendChild(tit);
    hd.appendChild(x);
    sheet.appendChild(hd);
    bodyBuild(sheet);
    back.appendChild(sheet);
    back.addEventListener("click", function (e) { if (e.target === back) closeLbSheet(); });
    document.body.appendChild(back);
    return back;
  }

  function filterChips() {
    return Array.prototype.slice.call(document.querySelectorAll("main .lb-filter-row button.lb-chip, main .lb-filter-row .lb-chip"));
  }
  function sortChips() {
    return Array.prototype.slice.call(document.querySelectorAll("main .lb-sort-row button.lb-chip, main .lb-sort-row .lb-chip"));
  }
  function chipByText(chips, text) {
    text = (text || "").replace(/\s+/g, "");
    for (var i = 0; i < chips.length; i++) {
      var t = (chips[i].textContent || "").replace(/\s+/g, "").replace(/↓/g, "");
      if (t === text || t.indexOf(text) === 0) return chips[i];
    }
    return null;
  }

  /* state for client-side package + multi category */
  window.__lbCatUi = window.__lbCatUi || { pkg: false, cats: {} };

  function applyClientCardFilter() {
    var st = window.__lbCatUi;
    var cards = document.querySelectorAll("main .lb-cat-card");
    var catKeys = Object.keys(st.cats).filter(function (k) { return st.cats[k]; });
    cards.forEach(function (card) {
      var hide = false;
      if (st.pkg) {
        if (!card.querySelector(".lb-pkg-badge")) hide = true;
      }
      if (!hide && catKeys.length) {
        var txt = card.textContent || "";
        var ok = catKeys.some(function (lab) { return txt.indexOf(lab) >= 0; });
        if (!ok) hide = true;
      }
      card.classList.toggle("lb-hide-card", hide);
    });
  }

  function clickChip(chip) {
    if (chip) try { chip.click(); } catch (e) {}
  }

  function openCategorySheet() {
    var chips = filterChips();
    /* category chips = all except همه / نشان / آماده */
    var skip = { "همه": 1, "نشان‌شده‌ها": 1, "نشانشدهها": 1, "آمادهانتشار": 1, "آماده انتشار": 1 };
    var cats = chips.filter(function (c) {
      var t = (c.textContent || "").trim();
      var key = t.replace(/\s+/g, "");
      return t && !skip[t] && !skip[key];
    });
    /* also include آماده انتشار as optional in sheet */
    var ready = chipByText(chips, "آماده انتشار");

    openLbSheet("دسته‌بندی", function (sheet) {
      var st = window.__lbCatUi;
      if (ready) {
        var o0 = document.createElement("button");
        o0.type = "button";
        o0.className = "lb-sheet-opt" + (ready.classList.contains("on") ? " on" : "");
        o0.innerHTML = '<span>آماده انتشار</span><span class="ck"></span>';
        o0.onclick = function () {
          clickChip(ready);
          setTimeout(function () {
            o0.classList.toggle("on", ready.classList.contains("on"));
            syncCatBar();
          }, 30);
        };
        sheet.appendChild(o0);
      }
      cats.forEach(function (chip) {
        var lab = (chip.textContent || "").trim();
        var o = document.createElement("button");
        o.type = "button";
        o.className = "lb-sheet-opt" + (st.cats[lab] ? " on" : "");
        o.innerHTML = '<span></span><span class="ck"></span>';
        o.querySelector("span").textContent = lab;
        o.onclick = function () {
          st.cats[lab] = !st.cats[lab];
          o.classList.toggle("on", !!st.cats[lab]);
          /* برای سازگاری با React: اگر فقط یکی روشن است همان chip را بزن؛ وگرنه همه */
          var active = Object.keys(st.cats).filter(function (k) { return st.cats[k]; });
          var allChip = chipByText(filterChips(), "همه");
          if (active.length === 0) {
            clickChip(allChip);
          } else if (active.length === 1) {
            var one = chipByText(filterChips(), active[0]);
            clickChip(one || allChip);
          } else {
            clickChip(allChip);
          }
          setTimeout(function () {
            applyClientCardFilter();
            syncCatBar();
          }, 40);
        };
        sheet.appendChild(o);
      });
      var foot = document.createElement("div");
      foot.className = "lb-sheet-foot";
      var clear = document.createElement("button");
      clear.type = "button";
      clear.textContent = "پاک کردن";
      clear.onclick = function () {
        window.__lbCatUi.cats = {};
        clickChip(chipByText(filterChips(), "همه"));
        applyClientCardFilter();
        syncCatBar();
        closeLbSheet();
      };
      var done = document.createElement("button");
      done.type = "button";
      done.className = "primary";
      done.textContent = "اعمال";
      done.onclick = function () {
        applyClientCardFilter();
        syncCatBar();
        closeLbSheet();
      };
      foot.appendChild(clear);
      foot.appendChild(done);
      sheet.appendChild(foot);
    });
  }

  function openSortSheet() {
    var chips = sortChips();
    if (!chips.length) return;
    openLbSheet("مرتب‌سازی بر اساس", function (sheet) {
      chips.forEach(function (chip) {
        var base = (chip.textContent || "").replace(/\s*↓\s*$/, "").trim();
        if (!base) return;
        var isOn = chip.classList.contains("on");
        var isRev = (chip.textContent || "").indexOf("↓") >= 0;

        var row = document.createElement("div");
        row.className = "lb-sort-row-ui";

        var title = document.createElement("span");
        title.className = "lb-sort-title";
        title.textContent = base;
        if (isOn) title.classList.add("on");
        row.appendChild(title);

        var dirs = document.createElement("div");
        dirs.className = "lb-sort-dirs";

        function mkBtn(wantRev, arrow) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "lb-sort-dir" + (isOn && isRev === wantRev ? " on" : "");
          b.setAttribute("aria-label", base + (wantRev ? " صعودی" : " نزولی"));
          b.innerHTML = arrow;
          b.onclick = function (e) {
            e.stopPropagation();
            if (!chip.classList.contains("on")) {
              clickChip(chip);
              if (wantRev) {
                setTimeout(function () { clickChip(chip); }, 30);
              }
            } else {
              var nowRev = (chip.textContent || "").indexOf("↓") >= 0;
              if (nowRev !== wantRev) clickChip(chip);
            }
            setTimeout(function () {
              syncCatBar();
              closeLbSheet();
            }, 50);
          };
          return b;
        }

        /* فلش بالا = مقدار بیشتر اول (rev=false برای بازدید؛ برای قیمت = گران‌تر = rev true) */
        /* ساده‌سازی UX: بالا = !rev در React بعد از انتخاب، پایین = rev */
        /* برای قیمت/cpm پیش‌فرض !rev = ارزان؛ کاربر فلش بالا را «بیشتر» می‌فهمد */
        var up = mkBtn(false, '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>');
        var down = mkBtn(true, '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>');
        dirs.appendChild(up);
        dirs.appendChild(down);
        row.appendChild(dirs);
        sheet.appendChild(row);
      });
    });
  }

  function syncCatBar() {
    var bar = document.getElementById("lb-cat-bar");
    if (!bar) return;
    var chips = filterChips();
    var allOn = false, favOn = false;
    chips.forEach(function (c) {
      var t = (c.textContent || "").trim();
      if (t === "همه" && c.classList.contains("on")) allOn = true;
      if (t.indexOf("نشان") >= 0 && c.classList.contains("on")) favOn = true;
    });
    var st = window.__lbCatUi;
    var catCount = Object.keys(st.cats).filter(function (k) { return st.cats[k]; }).length;
    bar.querySelectorAll("[data-act]").forEach(function (btn) {
      var act = btn.getAttribute("data-act");
      if (act === "all") btn.classList.toggle("on", allOn && !favOn && !st.pkg && catCount === 0);
      if (act === "fav") btn.classList.toggle("on", favOn);
      if (act === "pkg") btn.classList.toggle("on", !!st.pkg);
      if (act === "cat") {
        btn.classList.toggle("on", catCount > 0);
        var tx = btn.querySelector(".tx");
        if (tx) tx.textContent = catCount ? ("دسته (" + catCount + ")") : "دسته‌بندی";
      }
      if (act === "sort") {
        var sc = sortChips().filter(function (c) { return c.classList.contains("on"); })[0];
        var tx = btn.querySelector(".tx");
        if (tx && sc) {
          var lab = (sc.textContent || "").trim();
          tx.textContent = lab || "مرتب‌سازی";
        } else if (tx) tx.textContent = "مرتب‌سازی";
        btn.classList.toggle("on", !!sc);
      }
    });
  }

  function ensureCatalogToolbar() {
    try {
      if (!isCustomerCatalog()) {
        var bar = document.getElementById("lb-cat-bar");
        if (bar) bar.remove();
        closeLbSheet();
        return;
      }
      enhanceCatSearch();
      var filter = document.querySelector("main .lb-filter-row");
      if (!filter) return;

      var bar = document.getElementById("lb-cat-bar");
      if (!bar) {
        bar = document.createElement("div");
        bar.id = "lb-cat-bar";
        bar.className = "lb-cat-bar";
        bar.innerHTML =
          '<button type="button" class="lb-cat-bar-item" data-act="all">همه</button>' +
          '<button type="button" class="lb-cat-bar-item" data-act="fav">نشان‌شده</button>' +
          '<button type="button" class="lb-cat-bar-item" data-act="pkg">مجموعه</button>' +
          '<button type="button" class="lb-cat-bar-item is-btn" data-act="cat"><span class="tx">دسته‌بندی</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></button>' +
          '<button type="button" class="lb-cat-bar-item is-btn" data-act="sort"><span class="tx">مرتب‌سازی</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M7 12h10M10 18h4"/></svg></button>';
        if (filter.parentNode) {
          filter.parentNode.insertBefore(bar, filter);
        }
        bar.addEventListener("click", function (e) {
          var btn = e.target.closest("[data-act]");
          if (!btn) return;
          var act = btn.getAttribute("data-act");
          var chips = filterChips();
          if (act === "all") {
            window.__lbCatUi.pkg = false;
            window.__lbCatUi.cats = {};
            clickChip(chipByText(chips, "همه"));
            setTimeout(function () { applyClientCardFilter(); syncCatBar(); }, 40);
          } else if (act === "fav") {
            window.__lbCatUi.pkg = false;
            clickChip(chipByText(chips, "نشان‌شده‌ها") || chipByText(chips, "نشان‌شده"));
            setTimeout(function () { applyClientCardFilter(); syncCatBar(); }, 40);
          } else if (act === "pkg") {
            window.__lbCatUi.pkg = !window.__lbCatUi.pkg;
            if (window.__lbCatUi.pkg) {
              clickChip(chipByText(chips, "همه"));
            }
            setTimeout(function () { applyClientCardFilter(); syncCatBar(); }, 40);
          } else if (act === "cat") {
            openCategorySheet();
          } else if (act === "sort") {
            openSortSheet();
          }
        });
      } else if (filter.parentNode && bar.nextElementSibling !== filter) {
        filter.parentNode.insertBefore(bar, filter);
      }
      applyClientCardFilter();
      syncCatBar();
    } catch (e) {}
  }

  /* 7) وضعیت «خالی از نتیجه جستجو» زیر لیست */
  function searchEmptyState() {
    var inp = document.querySelector("main input[placeholder*='جستجو']");
    if (!inp) return;
    var q = (inp.value || "").trim();
    var main = document.querySelector("main");
    if (!main) return;
    var box = main.querySelector(".lb-no-results");
    var cards = main.querySelectorAll(".rounded-2xl.bg-surface");
    var visible = 0;
    cards.forEach(function (c) {
      if (c.offsetParent !== null) visible++;
    });
    if (q.length >= 2 && visible === 0 && !main.querySelector(".empty-note")) {
      if (!box) {
        box = document.createElement("div");
        box.className = "lb-no-results empty-note";
        box.textContent = "نتیجه‌ای پیدا نشد";
        main.appendChild(box);
      }
    } else if (box) {
      box.remove();
    }
  }

  /* 8) نشان تعداد فیلتر فعال */
  function filterActiveCount() {
    var on = document.querySelectorAll("main button.lb-chip.on, main button.lb-pill.bg-link, main button.rounded-full.bg-link").length;
    var host = document.querySelector("main .lb-chips");
    if (!host) return;
    var badge = host.querySelector(".lb-filter-count");
    if (on <= 1) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "lb-filter-count";
      host.appendChild(badge);
    }
    badge.textContent = on + " فیلتر";
  }

  /* 9) لرزش ناو وقتی badge جدید می‌آید */
  var lastBadge = "";
  function watchNavBadge() {
    var badges = document.querySelectorAll("nav .lb-nav-badge, nav span.absolute");
    var sig = "";
    badges.forEach(function (b) { sig += (b.textContent || "").trim(); });
    if (sig && sig !== lastBadge && lastBadge !== "") {
      try { if (window.lbHaptic) window.lbHaptic("warning"); } catch (e) {}
      document.querySelector("nav") && document.querySelector("nav").classList.add("lb-nav-pulse");
      setTimeout(function () {
        var n = document.querySelector("nav");
        if (n) n.classList.remove("lb-nav-pulse");
      }, 500);
    }
    lastBadge = sig;
  }

  /* 10) پین کردن هدر کارت اول (اختیاری با کلاس) */
  /* CSS-only mostly */

  /* 11) حالت خواندن بهتر برای کپشن‌های بلند */
  function expandCaptions() {
    document.querySelectorAll("main .line-clamp-2, main #lbTestCap").forEach(function (el) {
      if (el.dataset.lbExp) return;
      el.dataset.lbExp = "1";
      el.addEventListener("click", function () {
        el.classList.toggle("lb-caption-open");
      });
    });
  }

  /* 12) جلوگیری از submit خالی */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("main button.bg-link");
    if (!btn) return;
    var form = btn.closest("form");
    if (!form) return;
    var required = form.querySelectorAll("[required]");
    var bad = null;
    required.forEach(function (inp) {
      if (!bad && !(inp.value || "").trim()) bad = inp;
    });
    if (bad) {
      e.preventDefault();
      e.stopPropagation();
      if (window.lbFieldError) window.lbFieldError(bad, "این فیلد لازم است");
      if (window.lbShake) window.lbShake(bad);
      bad.focus();
    }
  }, true);

  /* 13) نشانگر اسکرول افقی فیلتر */
  function filterScrollCue() {
    document.querySelectorAll("main .lb-chips").forEach(function (row) {
      if (row.dataset.lbCue) return;
      row.dataset.lbCue = "1";
      row.addEventListener("scroll", function () {
        row.classList.toggle("lb-scrolled-end", row.scrollLeft + row.clientWidth >= row.scrollWidth - 4);
        row.classList.toggle("lb-scrolled-start", Math.abs(row.scrollLeft) > 4);
      }, { passive: true });
    });
  }

  /* 14) تأخیر نمایش FAB تا بعد از لود */
  setTimeout(function () {
    document.documentElement.classList.add("lb-ready");
  }, 400);

  /* 15) گزارش نسخه UI در console برای دیباگ */
  try {
    console.info("[linkban-ui] build helpers active");
  } catch (e) {}

  /* 16) لمس و نگه‌داشتن روی کارت = کلاس selected */
  (function () {
    var t = 0, card = null;
    document.addEventListener("touchstart", function (e) {
      card = e.target.closest && e.target.closest("main .rounded-2xl.bg-surface");
      if (!card) return;
      t = setTimeout(function () {
        if (card) card.classList.add("lb-card-selected");
        try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (err) {}
      }, 450);
    }, { passive: true });
    document.addEventListener("touchend", function () {
      clearTimeout(t);
      setTimeout(function () {
        document.querySelectorAll(".lb-card-selected").forEach(function (c) {
          c.classList.remove("lb-card-selected");
        });
      }, 800);
    });
  })();

  /* 17) همگام‌سازی رنگ status bar بله با تم */
  function syncStatusBar() {
    try {
      var w = window.Bale && Bale.WebApp;
      if (!w) return;
      var dark = document.documentElement.dataset.theme === "dark";
      if (w.setHeaderColor) {
        var c = getComputedStyle(document.documentElement).getPropertyValue("--lb-header").trim();
        if (c) w.setHeaderColor(c);
      }
      if (w.setBackgroundColor) {
        var b = getComputedStyle(document.documentElement).getPropertyValue("--lb-bg").trim();
        if (b) w.setBackgroundColor(b);
      }
    } catch (e) {}
  }

  /* 18) debounce عمومی */
  window.lbDebounce = function (fn, ms) {
    var t;
    return function () {
      var ctx = this, args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, ms || 300);
    };
  };

  /* 19) throttle عمومی */
  window.lbThrottle = function (fn, ms) {
    var last = 0;
    return function () {
      var now = Date.now();
      if (now - last < (ms || 200)) return;
      last = now;
      return fn.apply(this, arguments);
    };
  };

  /* 20) پاک‌سازی toastهای تکراری پشت‌سرهم */
  var lastToast = "";
  var lastToastAt = 0;
  var _toast2 = window.lbToast;
  if (typeof _toast2 === "function") {
    window.lbToast = function (text) {
      var now = Date.now();
      if (text === lastToast && now - lastToastAt < 1200) return;
      lastToast = text;
      lastToastAt = now;
      _toast2(text);
    };
  }

  var _prevTick5 = tickUi;
  tickUi = function () {
    if (typeof _prevTick5 === "function") _prevTick5();
    try {
      wireDrafts();
      enhanceCatSearch();
      ensureOnboarding();
      ensureCatalogToolbar();
      searchEmptyState();
      filterActiveCount();
      watchNavBadge();
      expandCaptions();
      filterScrollCue();
      syncStatusBar();
    } catch (e) {}
  };


  /* —— ۲۰ بهبود بعدی —— */

  /* 1) سوایپ راست/چپ روی نقش‌ها برای عوض کردن */
  (function () {
    var startX = 0, startY = 0;
    var headerRoles = null;
    document.addEventListener("touchstart", function (e) {
      headerRoles = document.querySelector("header > div.px-3");
      if (!headerRoles || !headerRoles.contains(e.target)) {
        headerRoles = null;
        return;
      }
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
    }, { passive: true });
    document.addEventListener("touchend", function (e) {
      if (!headerRoles) return;
      var dx = e.changedTouches[0].clientX - startX;
      var dy = e.changedTouches[0].clientY - startY;
      if (Math.abs(dx) < 50 || Math.abs(dy) > 40) return;
      var btns = Array.prototype.slice.call(headerRoles.querySelectorAll("button.rounded-full"));
      var active = headerRoles.querySelector("button.rounded-full.bg-link");
      var i = btns.indexOf(active);
      if (i < 0) return;
      // RTL: swipe left (dx negative in screen?) — visual next
      var next = dx < 0 ? i - 1 : i + 1;
      if (next >= 0 && next < btns.length) {
        btns[next].click();
        try { if (window.lbHaptic) window.lbHaptic("selection"); } catch (err) {}
      }
      headerRoles = null;
    }, { passive: true });
  })();

  /* 2) تأیید قبل از پاک کردن فیلد با دکمه clear */
  window.lbClearField = function (el) {
    if (!el) return;
    el.value = "";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    if (window.lbFieldError) window.lbFieldError(el, null);
  };

  /* 3) دکمه پاک‌کن — غیرفعال: جابه‌جایی input زیر React باعث
     تکرار فیلد و خطای removeChild می‌شد. */
  function wireClearButtons() {
    /* no-op: هرگز parent React-managed را تغییر نده */
    return;
  }

  /* 4) یادآوری آخرین نقش */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("header button.rounded-full");
    if (!btn) return;
    try { localStorage.setItem("lb.lastRole", (btn.textContent || "").trim()); } catch (err) {}
  }, true);

  /* 5) نشان نسخه مینی‌اپ مخفی با ۵ ضربه روی لوگو */
  (function () {
    var taps = 0, t0 = 0;
    document.addEventListener("click", function (e) {
      if (!e.target.classList || !e.target.classList.contains("lb-brand-logo")) return;
      var now = Date.now();
      if (now - t0 > 2000) taps = 0;
      t0 = now;
      taps++;
      if (taps >= 5) {
        taps = 0;
        if (window.lbToast) window.lbToast("لینک‌بان UI · helpers on");
      }
    });
  })();

  /* 6) پیش‌بارگذاری تصاویر بعدی لیست */
  function prefetchThumbs() {
    document.querySelectorAll("main img[src]").forEach(function (img, i) {
      if (i < 8) return;
      if (img.dataset.lbPrefetch) return;
      img.dataset.lbPrefetch = "1";
    });
  }

  /* 7) کلاس «صفحه اسکرول‌شده» برای فشردن هدر */
  function wireMainScrollClass() {
    var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
    if (!main || main.dataset.lbScrollCls) return;
    main.dataset.lbScrollCls = "1";
    main.addEventListener("scroll", window.lbThrottle ? window.lbThrottle(function () {
      document.documentElement.classList.toggle("lb-scrolled", main.scrollTop > 12);
    }, 100) : function () {
      document.documentElement.classList.toggle("lb-scrolled", main.scrollTop > 12);
    }, { passive: true });
  }

  /* 8) پنهان کردن FAB هنگام اسکرول به پایین */
  var lastY = 0;
  function wireFabHideOnScroll() {
    var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
    if (!main || main.dataset.lbFabScroll) return;
    main.dataset.lbFabScroll = "1";
    main.addEventListener("scroll", function () {
      var y = main.scrollTop;
      var hide = y > lastY && y > 80;
      document.documentElement.classList.toggle("lb-fab-hide", hide);
      lastY = y;
    }, { passive: true });
  }

  /* 9) نرمال‌سازی اعداد فارسی به انگلیسی در input */
  window.lbToEnDigits = function (s) {
    return String(s || "").replace(/[۰-۹]/g, function (d) {
      return "۰۱۲۳۴۵۶۷۸۹".indexOf(d);
    }).replace(/[٠-٩]/g, function (d) {
      return "٠١٢٣٤٥٦٧٨٩".indexOf(d);
    });
  };
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!t || t.tagName !== "INPUT") return;
    if (t.type !== "tel" && t.type !== "number" && t.inputMode !== "numeric") return;
    var v = t.value;
    var n = window.lbToEnDigits(v);
    if (n !== v) {
      var pos = t.selectionStart;
      t.value = n;
      try { t.setSelectionRange(pos, pos); } catch (err) {}
    }
  }, true);

  /* 10) نمایش قدرت اتصال تقریبی */
  function netInfo() {
    try {
      var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!c) return;
      document.documentElement.dataset.conn = c.effectiveType || "";
      if (c.effectiveType === "2g" || c.effectiveType === "slow-2g") {
        if (window.lbNetWatch) window.lbNetWatch(6000);
      }
    } catch (e) {}
  }
  netInfo();

  /* 11) بازیابی فوکوس بعد از بستن لایتبکس */
  var lastFocus = null;
  document.addEventListener("click", function (e) {
    if (e.target.tagName === "IMG" && e.target.closest("main")) lastFocus = e.target;
  }, true);
  var _lb = window.lbLightbox;
  if (typeof _lb === "function") {
    window.lbLightbox = function (src) {
      _lb(src);
      setTimeout(function () {
        var box = document.getElementById("lb-lightbox");
        if (!box) return;
        var obs = new MutationObserver(function () {
          if (!document.getElementById("lb-lightbox") && lastFocus) {
            try { lastFocus.focus(); } catch (e) {}
            obs.disconnect();
          }
        });
        obs.observe(document.body, { childList: true });
      }, 50);
    };
  }

  /* 12) علامت‌گذاری لینک‌های خارجی */
  function markExternalLinks() {
    document.querySelectorAll("main a[href]").forEach(function (a) {
      if (a.dataset.lbExt) return;
      var href = a.getAttribute("href") || "";
      if (/^https?:/i.test(href) && href.indexOf(location.host) < 0) {
        a.dataset.lbExt = "1";
        a.classList.add("lb-external");
        a.setAttribute("rel", "noopener noreferrer");
        a.setAttribute("target", "_blank");
      }
    });
  }

  /* 13) شمارش معکوس ساده */
  window.lbCountdown = function (el, seconds, done) {
    if (!el) return;
    var left = seconds | 0;
    el.textContent = left;
    el.classList.add("lb-countdown");
    var id = setInterval(function () {
      left--;
      el.textContent = left;
      if (left <= 0) {
        clearInterval(id);
        el.classList.remove("lb-countdown");
        if (done) done();
      }
    }, 1000);
    return id;
  };

  /* 14) جلوگیری از کشیدن تصویر */
  document.addEventListener("dragstart", function (e) {
    if (e.target.tagName === "IMG") e.preventDefault();
  });

  /* 15) کلاس جهت اسکرول */
  var scrollDirY = 0;
  function wireScrollDir() {
    var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
    if (!main || main.dataset.lbDir) return;
    main.dataset.lbDir = "1";
    main.addEventListener("scroll", function () {
      var y = main.scrollTop;
      document.documentElement.dataset.scrollDir = y > scrollDirY ? "down" : "up";
      scrollDirY = y;
    }, { passive: true });
  }

  /* 16) همگام‌سازی عنوان document با h1 */
  function syncDocTitle() {
    var h = document.querySelector("header h1");
    if (!h) return;
    var t = (h.textContent || "").trim();
    if (t) document.title = t + " · لینک‌بان";
  }

  /* 17) حافظه آخرین صفحه ناو */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("nav button");
    if (!btn) return;
    try { sessionStorage.setItem("lb.lastNav", (btn.textContent || "").trim()); } catch (err) {}
  }, true);

  /* 18) وضعیت خالی بودن کلیپ‌بورد API */
  window.lbCanClipboard = !!(navigator.clipboard && navigator.clipboard.writeText);

  /* 19) نرم‌سازی ورود صفحه با view transition اگر پشتیبانی شود */
  document.addEventListener("click", function (e) {
    var nav = e.target.closest && e.target.closest("nav button, header button.rounded-full");
    if (!nav || !document.startViewTransition) return;
    /* فقط اگر مرورگر پشتیبانی کند — React خودش DOM را عوض می‌کند */
  }, true);

  /* 20) جمع‌آوری خطاهای JS کوچک در toast (فقط یک‌بار) */
  window.addEventListener("error", function (e) {
    if (window.__lbErrShown) return;
    if (!e || !e.message) return;
    if (/Script error|ResizeObserver|Loading CSS/i.test(e.message)) return;
    window.__lbErrShown = true;
    /* عمداً toast عمومی نشان نمی‌دهیم تا کاربر نترسد؛ فقط کنسول */
    try { console.warn("[linkban]", e.message); } catch (err) {}
  });

  var _prevTick6 = tickUi;
  tickUi = function () {
    if (typeof _prevTick6 === "function") _prevTick6();
    try {
      wireClearButtons();
      prefetchThumbs();
      wireMainScrollClass();
      wireFabHideOnScroll();
      markExternalLinks();
      wireScrollDir();
      syncDocTitle();
      syncHeaderBack();
    } catch (e) {}
  };


  /* —— ۲۰ بهبود بعدی —— */

  /* 1) پین نوار فیلتر با سایه وقتی sticky فعال است */
  function wireStickyFilterShadow() {
    document.querySelectorAll("main .lb-chips").forEach(function (row) {
      if (row.dataset.lbSticky) return;
      row.dataset.lbSticky = "1";
      var main = document.querySelector("main");
      if (!main) return;
      main.addEventListener("scroll", function () {
        var top = row.getBoundingClientRect().top;
        row.classList.toggle("lb-sticky-on", top <= 2);
      }, { passive: true });
    });
  }

  /* 2) میانبر: دابل‌تپ ناو خانه = اسکرول بالا */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("nav button");
    if (!btn) return;
    var label = (btn.textContent || "").trim();
    if (label.indexOf("خانه") < 0) return;
    var now = Date.now();
    if (btn._lbLastTap && now - btn._lbLastTap < 350) {
      var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
      if (main) main.scrollTo({ top: 0, behavior: "smooth" });
    }
    btn._lbLastTap = now;
  }, true);

  /* 3) ذخیره عرض viewport برای CSS */
  function syncVh() {
    document.documentElement.style.setProperty("--lb-vh", window.innerHeight + "px");
  }
  window.addEventListener("resize", syncVh);
  syncVh();

  /* 4) کلاس «کیبورد باز روی iOS» از focus input */
  document.addEventListener("focusin", function (e) {
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) {
      document.documentElement.classList.add("lb-field-focus");
    }
  });
  document.addEventListener("focusout", function () {
    setTimeout(function () {
      var a = document.activeElement;
      if (!a || !/INPUT|TEXTAREA|SELECT/.test(a.tagName)) {
        document.documentElement.classList.remove("lb-field-focus");
      }
    }, 80);
  });

  /* 5) پیش‌نمایش طول متن فارسی بدون برش وسط کلمه در toast */
  var _toast3 = window.lbToast;
  if (typeof _toast3 === "function") {
    window.lbToast = function (text) {
      var t = String(text || "");
      if (t.length > 120) t = t.slice(0, 117) + "…";
      _toast3(t);
    };
  }

  /* 6) نشان «به‌روز شد» لحظه‌ای بعد از refresh */
  window.addEventListener("lb:refresh", function () {
    if (window.lbToast) window.lbToast("در حال به‌روزرسانی…");
    if (window.lbProgress) {
      window.lbProgress(true);
      setTimeout(function () { window.lbProgress(false); }, 1200);
    }
  });

  /* 7) حافظه آخرین جستجو */
  function wireSearchMemory() {
    document.querySelectorAll("main input[placeholder*='جستجو']").forEach(function (inp) {
      if (inp.dataset.lbMem) return;
      inp.dataset.lbMem = "1";
      try {
        var s = sessionStorage.getItem("lb.search");
        if (s && !inp.value) {
          inp.value = s;
          inp.dispatchEvent(new Event("input", { bubbles: true }));
        }
      } catch (e) {}
      inp.addEventListener("input", function () {
        try { sessionStorage.setItem("lb.search", inp.value || ""); } catch (e) {}
      });
    });
  }

  /* 8) حذف پیش‌نویس بعد از موفقیت toast ثبت */
  var _toast4 = window.lbToast;
  if (typeof _toast4 === "function") {
    window.lbToast = function (text) {
      _toast4(text);
      if (/ثبت|ذخیره|ارسال شد|انجام شد/.test(String(text || ""))) {
        try {
          var keys = [];
          for (var i = 0; i < sessionStorage.length; i++) {
            var k = sessionStorage.key(i);
            if (k && k.indexOf("lb.draft.") === 0) keys.push(k);
          }
          keys.forEach(function (k) { sessionStorage.removeItem(k); });
        } catch (e) {}
      }
    };
  }

  /* 9) هایلایت فیلد فوکوس‌شده parent */
  document.addEventListener("focusin", function (e) {
    document.querySelectorAll(".lb-field-active").forEach(function (x) {
      x.classList.remove("lb-field-active");
    });
    var t = e.target;
    if (t && /INPUT|TEXTAREA|SELECT/.test(t.tagName)) {
      var p = t.closest(".lb-field, .lb-input-wrap, label, div");
      if (p) p.classList.add("lb-field-active");
    }
  });

  /* 10) لمس بیرون input = blur (بستن کیبورد) */
  document.addEventListener("touchend", function (e) {
    var a = document.activeElement;
    if (!a || !/INPUT|TEXTAREA/.test(a.tagName)) return;
    if (e.target === a || (a.contains && a.contains(e.target))) return;
    if (e.target.closest && e.target.closest("button, a, label")) return;
    a.blur();
  }, { passive: true });

  /* 11) نشانگر پر شدن فرم (درصد فیلدهای پر) */
  window.lbFormProgress = function (form) {
    if (!form) return 0;
    var fields = form.querySelectorAll("input, textarea, select");
    var n = 0, f = 0;
    fields.forEach(function (el) {
      if (el.type === "hidden" || el.disabled) return;
      n++;
      if ((el.value || "").trim()) f++;
    });
    return n ? Math.round((f / n) * 100) : 0;
  };

  /* 12) ارتعاش خطا روی lbShake */
  var _shake = window.lbShake;
  if (typeof _shake === "function") {
    window.lbShake = function (el) {
      _shake(el);
      try { if (window.lbHaptic) window.lbHaptic("error"); } catch (e) {}
    };
  }

  /* 13) تشخیص صفحه RTL اجباری */
  document.documentElement.setAttribute("dir", "rtl");
  document.documentElement.lang = document.documentElement.lang || "fa";

  /* 14) کلاس وضعیت شبکه online/offline روی html */
  function syncOnlineClass() {
    document.documentElement.classList.toggle("lb-online", navigator.onLine !== false);
    document.documentElement.classList.toggle("lb-offline", navigator.onLine === false);
  }
  window.addEventListener("online", syncOnlineClass);
  window.addEventListener("offline", syncOnlineClass);
  syncOnlineClass();

  /* 15) جلوگیری از باز شدن چند لایتبکس */
  var _lb2 = window.lbLightbox;
  if (typeof _lb2 === "function") {
    window.lbLightbox = function (src) {
      var old = document.getElementById("lb-lightbox");
      if (old) old.remove();
      _lb2(src);
    };
  }

  /* 16) انیمیشن عدد بج ناو */
  function animateBadges() {
    document.querySelectorAll("nav .lb-nav-badge, nav span.absolute").forEach(function (b) {
      if (b.dataset.lbAnim === b.textContent) return;
      b.dataset.lbAnim = b.textContent;
      b.classList.remove("lb-badge-pop");
      void b.offsetWidth;
      b.classList.add("lb-badge-pop");
    });
  }

  /* 17) long-press روی ناو = haptic + جلوگیری از context menu */
  document.addEventListener("contextmenu", function (e) {
    if (e.target.closest && e.target.closest("nav, header")) e.preventDefault();
  });

  /* 18) همگام safe-area CSS variables از env */
  function syncSafe() {
    /* env() در CSS هست؛ فقط کلاس کمکی */
    document.documentElement.classList.add("lb-safe");
  }
  syncSafe();

  /* 19) پاک کردن session search با دکمه clear */
  document.addEventListener("click", function (e) {
    if (!e.target.classList || !e.target.classList.contains("lb-clear-btn")) return;
    try { sessionStorage.removeItem("lb.search"); } catch (err) {}
  });

  /* 20) گزارش آماده‌بودن UI */
  window.lbUiReady = true;
  try {
    window.dispatchEvent(new CustomEvent("lb:ui-ready"));
  } catch (e) {}

  var _prevTick7 = tickUi;
  tickUi = function () {
    if (typeof _prevTick7 === "function") _prevTick7();
    try {
      wireStickyFilterShadow();
      wireSearchMemory();
      animateBadges();
    } catch (e) {}
  };


  /* —— ۲۰ بهبود بعدی —— */

  /* 1) سوایپ پایین روی هدر = refresh */
  (function () {
    var y0 = 0, pulling = false;
    document.addEventListener("touchstart", function (e) {
      var h = document.querySelector("header");
      if (!h || !h.contains(e.target)) return;
      y0 = e.touches[0].clientY;
      pulling = true;
    }, { passive: true });
    document.addEventListener("touchend", function (e) {
      if (!pulling) return;
      pulling = false;
      var dy = e.changedTouches[0].clientY - y0;
      if (dy > 64) {
        window.dispatchEvent(new CustomEvent("lb:refresh"));
        try { if (window.lbHaptic) window.lbHaptic("light"); } catch (err) {}
      }
    }, { passive: true });
  })();

  /* 2) ذخیره تم ترجیحی از Bale اگر کاربر دستی نگذاشته */
  try {
    if (!localStorage.getItem("lb.theme")) {
      var w = window.Bale && Bale.WebApp;
      var cs = w && w.colorScheme;
      if (cs === "dark" || cs === "light") {
        document.documentElement.dataset.baleScheme = cs;
      }
    }
  } catch (e) {}

  /* 3) نشان «در حال تایپ» روی textarea با کلاس */
  document.addEventListener("input", function (e) {
    if (!e.target || e.target.tagName !== "TEXTAREA") return;
    e.target.classList.add("lb-typing");
    clearTimeout(e.target._lbTypeT);
    e.target._lbTypeT = setTimeout(function () {
      e.target.classList.remove("lb-typing");
    }, 600);
  });

  /* 4) اسکرول افقی فیلتر با شیفت چرخ ماوس */
  document.addEventListener("wheel", function (e) {
    var row = e.target.closest && e.target.closest(".lb-chips, main .flex:has(> button.lb-chip)");
    if (!row) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      row.scrollLeft += e.deltaY;
      e.preventDefault();
    }
  }, { passive: false });

  /* 5) میانبر: نگه داشتن خانه = برو به سفارش‌ها اگر badge دارد */
  (function () {
    var t = 0;
    document.addEventListener("touchstart", function (e) {
      var btn = e.target.closest && e.target.closest("nav button");
      if (!btn || (btn.textContent || "").indexOf("خانه") < 0) return;
      t = setTimeout(function () {
        var orders = null;
        document.querySelectorAll("nav button").forEach(function (b) {
          if ((b.textContent || "").indexOf("سفارش") >= 0) orders = b;
        });
        if (orders) orders.click();
      }, 550);
    }, { passive: true });
    document.addEventListener("touchend", function () { clearTimeout(t); });
  })();

  /* 6) نرمال‌سازی فاصله‌های اضافی در paste */
  document.addEventListener("paste", function (e) {
    var t = e.target;
    if (!t || t.tagName !== "INPUT") return;
    if (t.dataset.lbNoPasteNorm) return;
    setTimeout(function () {
      t.value = String(t.value || "").replace(/\s+/g, " ").trim();
      t.dispatchEvent(new Event("input", { bubbles: true }));
    }, 0);
  });

  /* 7) تشخیص overscroll و کلاس */
  function wireOverscroll() {
    var main = document.querySelector("main.overflow-y-auto") || document.querySelector("main");
    if (!main || main.dataset.lbOver) return;
    main.dataset.lbOver = "1";
    main.addEventListener("scroll", function () {
      var atTop = main.scrollTop <= 0;
      var atBot = main.scrollTop + main.clientHeight >= main.scrollHeight - 2;
      document.documentElement.classList.toggle("lb-at-top", atTop);
      document.documentElement.classList.toggle("lb-at-bottom", atBot);
    }, { passive: true });
  }

  /* 8) لود فونت Vazirmatn با کلاس آماده */
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () {
      document.documentElement.classList.add("lb-fonts-ready");
    });
  } else {
    document.documentElement.classList.add("lb-fonts-ready");
  }

  /* 9) جلوگیری از ورود فاصله در ابتدای input */
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!t || t.tagName !== "INPUT") return;
    if (t.type && t.type !== "text" && t.type !== "search") return;
    if (/^\s+/.test(t.value)) {
      t.value = t.value.replace(/^\s+/, "");
    }
  });

  /* 10) کلاس صفحه از data-page برای استایل اختصاصی */
  /* قبلاً syncPageClass — فقط CSS */

  /* 11) پیش‌بارگذاری مسیر لوگو جایگزین */
  (function () {
    var i = new Image();
    i.src = "/miniapp/static/panel/assets/logo-linkban.jpg";
  })();

  /* 12) نمایش زمان آخرین refresh */
  window.__lbLastRefresh = Date.now();
  window.addEventListener("lb:refresh", function () {
    window.__lbLastRefresh = Date.now();
    document.documentElement.dataset.lastRefresh = String(window.__lbLastRefresh);
  });

  /* 13) تأیید خروج از لایتبکس با swipe down */
  document.addEventListener("touchstart", function (e) {
    var box = document.getElementById("lb-lightbox");
    if (!box) return;
    box._sy = e.touches[0].clientY;
  }, { passive: true });
  document.addEventListener("touchend", function (e) {
    var box = document.getElementById("lb-lightbox");
    if (!box || box._sy == null) return;
    if (e.changedTouches[0].clientY - box._sy > 80) box.remove();
    box._sy = null;
  }, { passive: true });

  /* 14) شمارش کارت‌های visible برای analytics داخلی */
  window.lbVisibleCards = function () {
    var n = 0;
    document.querySelectorAll("main .rounded-2xl.bg-surface").forEach(function (c) {
      if (c.offsetParent !== null) n++;
    });
    return n;
  };

  /* 15) همگام‌سازی prefers-reduced-motion زنده */
  try {
    var mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    function applyRm(m) {
      document.documentElement.classList.toggle("lb-reduce-motion", !!m.matches);
    }
    applyRm(mq);
    if (mq.addEventListener) mq.addEventListener("change", applyRm);
  } catch (e) {}

  /* 16) دکمه‌های اصلی: جلوگیری از فوکوس outline آبی سیستم */
  document.addEventListener("mousedown", function (e) {
    if (e.target.closest && e.target.closest("button")) {
      /* keep focus-visible for keyboard only — CSS handles */
    }
  });

  /* 17) بازیابی اسکرول افقی فیلتر بعد از برگشت */
  var filterScrollMap = {};
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("nav button")) {
      document.querySelectorAll("main .lb-chips").forEach(function (row, i) {
        filterScrollMap[i] = row.scrollLeft;
      });
    }
  }, true);
  function restoreFilterScroll() {
    document.querySelectorAll("main .lb-chips").forEach(function (row, i) {
      if (filterScrollMap[i] != null) row.scrollLeft = filterScrollMap[i];
    });
  }

  /* 18) ابزار ساده clamp */
  window.lbClamp = function (n, min, max) {
    return Math.max(min, Math.min(max, n));
  };

  /* 19) تشخیص WebView بله */
  window.lbIsBale = !!(window.Bale && Bale.WebApp);
  document.documentElement.classList.toggle("lb-in-bale", window.lbIsBale);

  /* 20) آماده بودن: حذف کلاس boot اگر باشد */
  document.documentElement.classList.remove("lb-booting");
  document.documentElement.classList.add("lb-hydrated");


  var _prevTick8 = typeof tickUi === "function" ? tickUi : function () {};
  tickUi = function () {
    if (typeof _prevTick8 === "function") _prevTick8();
    try {
      if (typeof wireOverscroll === "function") wireOverscroll();
      if (typeof restoreFilterScroll === "function") restoreFilterScroll();
      if (typeof syncHeaderBack === "function") syncHeaderBack();
      if (typeof syncGroupPanel === "function") syncGroupPanel();
    } catch (e) {}
  };



  /* —— ساخت مجموعه: انتخاب روی همان لیست کانال‌ها —— */
  window.__lbGroupSel = window.__lbGroupSel || {};
  window.__lbGroupState = window.__lbGroupState || {
    open: false,
    channels: null,
    avatarChannelId: null,
    avatarFile: null,
    avatarPreview: null,
  };


  function lbApiHeaders() {
    var headers = { "Content-Type": "application/json" };
    try {
      var init = (window.Bale && Bale.WebApp && Bale.WebApp.initData) || "";
      if (init) headers["X-Bale-Init-Data"] = init;
    } catch (e) {}
    return headers;
  }
  function lbApiBase() {
    return window.__LIVE_API || "/miniapp/api";
  }


  function placeGroupPanel(panel, main, channelRows) {
    /* زیر لیست کانال‌ها (بعد از ul)، نه fixed روی صفحه */
    var list = null;
    if (channelRows && channelRows.length) {
      var last = channelRows[channelRows.length - 1];
      list = last.closest("ul") || last.parentElement;
    }
    if (list && list.parentNode) {
      if (panel.parentNode !== list.parentNode || panel.previousSibling !== list) {
        if (list.nextSibling) list.parentNode.insertBefore(panel, list.nextSibling);
        else list.parentNode.appendChild(panel);
      }
    } else if (main) {
      main.appendChild(panel);
    }
  }

  function syncGroupPanel() {
    var h1 = document.querySelector("header h1");
    var title = h1 ? (h1.textContent || "").trim() : "";
    var main = document.querySelector("main");
    if (!main) return;

    var host = document.getElementById("lb-shell-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "lb-shell-host";
      document.body.insertBefore(host, document.body.firstChild);
    }

    var panel = document.getElementById("lb-group-panel");
    var onList = title === "کانال‌ها";
    if (!onList) {
      if (panel) {
        try { panel.remove(); } catch (e) { panel.hidden = true; }
      }
      document.documentElement.classList.remove("lb-group-picking");
      clearRowPickBindings();
      return;
    }

    var chBtns = main.querySelectorAll("button.lb-ch-row");
    /* فقط کانال‌های تکی — ردیف مجموعه را نادیده بگیر */
    var channelRows = [];
    chBtns.forEach(function (btn) {
      var mode = btn.querySelector(".lb-ch-mode");
      var modeTxt = mode ? (mode.textContent || "") : "";
      /* ردیف مجموعه معمولاً «N کانال» دارد نه حالت انتشار */
      if (modeTxt.indexOf("کانال") >= 0 && modeTxt.indexOf("تعرفه") < 0) {
        /* could be group - skip if has «کانال» as unit without publish mode */
      }
      channelRows.push(btn);
    });
    if (channelRows.length < 2) {
      if (panel) {
        panel.hidden = true;
        panel.setAttribute("aria-hidden", "true");
      }
      document.documentElement.classList.remove("lb-group-picking");
      return;
    }
    if (panel) {
      panel.hidden = false;
      panel.setAttribute("aria-hidden", "false");
      placeGroupPanel(panel, main, channelRows);
    }

    if (!panel) {
      panel = document.createElement("div");
      panel.id = "lb-group-panel";
      panel.className = "lb-group-panel";
      panel.innerHTML =
        '<button type="button" class="lb-gp-toggle" id="lb-gp-toggle">' +
        '<svg class="lb-ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>' +
        ' ساخت مجموعه</button>' +
        '<div class="lb-gp-body" id="lb-gp-body" hidden>' +
        '  <p class="lb-gp-hint">کانال‌های بالا را انتخاب کنید، بعد نام مجموعه را بنویسید.</p>' +
        '  <div class="lb-gp-footer">' +
        '    <button type="button" class="lb-gp-ava-btn" id="lb-gp-ava-btn" title="پروفایل مجموعه" aria-label="پروفایل">' +
        '      <span class="lb-gp-ava-ph" id="lb-gp-ava-ph">' +
        '        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/><path d="M19 8v0"/></svg>' +
        '      </span>' +
        '      <img class="lb-gp-ava-img" id="lb-gp-ava-img" alt="" hidden />' +
        '    </button>' +
        '    <input class="lb-gp-name" id="lb-gp-name" placeholder="نام مجموعه" />' +
        '  </div>' +
        '  <div class="lb-gp-ava-menu" id="lb-gp-ava-menu" hidden></div>' +
        '  <input type="file" id="lb-gp-file" accept="image/*" hidden />' +
        '  <button type="button" class="lb-gp-save" id="lb-gp-save">ثبت مجموعه</button>' +
        '  <p class="lb-gp-msg" id="lb-gp-msg" hidden></p>' +
        '</div>';
      panel.hidden = false;
      placeGroupPanel(panel, main, channelRows);

      panel.querySelector("#lb-gp-toggle").addEventListener("click", function () {
        var st = window.__lbGroupState;
        st.open = !st.open;
        if (st.open) {
          ensureGroupChannelsLoaded(function () {
            applyGroupOpenState();
            bindRowPickMode();
          });
        } else {
          applyGroupOpenState();
          clearRowPickBindings();
        }
      });
      panel.querySelector("#lb-gp-save").addEventListener("click", submitGroupCreate);
      panel.querySelector("#lb-gp-ava-btn").addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        toggleAvatarMenu();
      });
      panel.querySelector("#lb-gp-file").addEventListener("change", function (e) {
        var f = e.target.files && e.target.files[0];
        if (!f) return;
        var st = window.__lbGroupState;
        st.avatarFile = f;
        st.avatarChannelId = null;
        if (st.avatarPreview) URL.revokeObjectURL(st.avatarPreview);
        st.avatarPreview = URL.createObjectURL(f);
        updateAvatarButton();
        hideAvatarMenu();
      });
      document.addEventListener("click", function (e) {
        var menu = document.getElementById("lb-gp-ava-menu");
        if (!menu || menu.hidden) return;
        if (e.target.closest && (e.target.closest("#lb-gp-ava-menu") || e.target.closest("#lb-gp-ava-btn"))) return;
        hideAvatarMenu();
      }, true);
    }
    panel.hidden = false;
    if (window.__lbGroupState.open) {
      bindRowPickMode();
      applyGroupOpenState();
    } else {
      applyGroupOpenState();
    }
  }

  function applyGroupOpenState() {
    var st = window.__lbGroupState;
    var body = document.getElementById("lb-gp-body");
    var toggle = document.getElementById("lb-gp-toggle");
    if (!body || !toggle) return;
    body.hidden = !st.open;
    toggle.classList.toggle("lb-gp-toggle-open", !!st.open);
    var label = st.open ? "انصراف" : "ساخت مجموعه";
    toggle.innerHTML =
      (st.open
        ? '<svg class="lb-ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg> '
        : '<svg class="lb-ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg> ') +
      label;
    document.documentElement.classList.toggle("lb-group-picking", !!st.open);
  }

  function ensureGroupChannelsLoaded(cb) {
    var st = window.__lbGroupState;
    if (st.channels) {
      if (cb) cb();
      return;
    }
    fetch(lbApiBase() + "/channels", { headers: lbApiHeaders() })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var chans = (data && data.channels) || [];
        chans = chans.slice().sort(function (a, b) {
          return (Number(b.members_count) || 0) - (Number(a.members_count) || 0);
        });
        st.channels = chans;
        if (cb) cb();
      })
      .catch(function () { if (cb) cb(); });
  }

  function memLabel(n) {
    n = Number(n) || 0;
    if (n >= 1000) {
      var x = (n / 1000).toFixed(1).replace(/\\.0$/, "");
      return x + "k";
    }
    return String(n);
  }

  function matchRowToChannel(btn) {
    var st = window.__lbGroupState;
    if (!st.channels) return null;
    var nameEl = btn.querySelector(".lb-ch-name");
    var name = nameEl ? (nameEl.textContent || "").trim() : (btn.textContent || "").trim();
    /* skip group rows: meta has «N کانال» without publish mode labels */
    var mode = btn.querySelector(".lb-ch-mode");
    var modeTxt = mode ? (mode.textContent || "") : "";
    if (/^\d+\s*کانال$/.test(modeTxt.trim()) || modeTxt.indexOf("کانال") >= 0 && modeTxt.indexOf("دستی") < 0 && modeTxt.indexOf("لینک") < 0 && modeTxt.indexOf("بازو") < 0 && modeTxt.indexOf("تعرفه") >= 0) {
      /* group row often ends with تعرفه count - still a channel can have تعرفه */
    }
    /* groups are pushed with name group - they also use lb-ch-row. Detect: mode contains only «N تعرفه» and meta has «N کانال» */
    var metas = btn.querySelectorAll(".lb-ch-meta");
    var metaJoined = "";
    metas.forEach(function (m) { metaJoined += " " + (m.textContent || ""); });
    if (metaJoined.indexOf("کانال") >= 0 && modeTxt.indexOf("تعرفه") >= 0 && modeTxt.indexOf("دستی") < 0 && modeTxt.indexOf("لینک") < 0 && modeTxt.indexOf("بازو") < 0) {
      return null; /* group row */
    }
    for (var i = 0; i < st.channels.length; i++) {
      var c = st.channels[i];
      if ((c.name || "").trim() === name) return c;
    }
    return null;
  }

  function clearRowPickBindings() {
    document.querySelectorAll("button.lb-ch-row.lb-gp-bound").forEach(function (btn) {
      btn.classList.remove("lb-gp-bound", "lb-gp-on");
      var chk = btn.querySelector(".lb-gp-check");
      if (chk) chk.remove();
      if (btn._lbGpHandler) {
        btn.removeEventListener("click", btn._lbGpHandler, true);
        btn._lbGpHandler = null;
      }
    });
  }

  function bindRowPickMode() {
    var st = window.__lbGroupState;
    if (!st.open) return;
    var sel = window.__lbGroupSel;
    document.querySelectorAll("main button.lb-ch-row").forEach(function (btn) {
      var ch = matchRowToChannel(btn);
      if (!ch) return;
      var id = String(ch.id);
      btn.classList.add("lb-gp-bound");
      btn.classList.toggle("lb-gp-on", !!sel[id]);
      var chk = btn.querySelector(".lb-gp-check");
      if (!chk) {
        chk = document.createElement("span");
        chk.className = "lb-gp-check";
        chk.setAttribute("aria-hidden", "true");
        btn.appendChild(chk);
      }
      if (btn._lbGpHandler) return;
      btn._lbGpHandler = function (e) {
        if (!window.__lbGroupState.open) return;
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        if (sel[id]) delete sel[id];
        else sel[id] = true;
        btn.classList.toggle("lb-gp-on", !!sel[id]);
        if (!sel[id] && st.avatarChannelId === ch.id) {
          st.avatarChannelId = null;
          updateAvatarButton();
        }
      };
      btn.addEventListener("click", btn._lbGpHandler, true);
    });
  }

  function selectedChannelsSorted() {
    var st = window.__lbGroupState;
    var sel = window.__lbGroupSel;
    if (!st.channels) return [];
    return st.channels.filter(function (c) { return sel[String(c.id)]; });
  }

  function toggleAvatarMenu() {
    var menu = document.getElementById("lb-gp-ava-menu");
    if (!menu) return;
    if (!menu.hidden) {
      hideAvatarMenu();
      return;
    }
    var selected = selectedChannelsSorted();
    menu.innerHTML = "";
    var upload = document.createElement("button");
    upload.type = "button";
    upload.className = "lb-gp-menu-item";
    upload.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg> بارگذاری از گالری';
    upload.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var file = document.getElementById("lb-gp-file");
      if (file) file.click();
    });
    menu.appendChild(upload);
    selected.forEach(function (c) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "lb-gp-menu-item";
      btn.textContent = (c.name || c.id) + " · " + memLabel(c.members_count) + " عضو";
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var st = window.__lbGroupState;
        st.avatarChannelId = c.id;
        st.avatarFile = null;
        if (st.avatarPreview) {
          URL.revokeObjectURL(st.avatarPreview);
          st.avatarPreview = null;
        }
        updateAvatarButton();
        hideAvatarMenu();
      });
      menu.appendChild(btn);
    });
    if (!selected.length) {
      var hint = document.createElement("p");
      hint.className = "lb-gp-menu-hint";
      hint.textContent = "اول از لیست بالا کانال انتخاب کنید";
      menu.appendChild(hint);
    }
    menu.hidden = false;
  }

  function hideAvatarMenu() {
    var menu = document.getElementById("lb-gp-ava-menu");
    if (menu) menu.hidden = true;
  }

  function updateAvatarButton() {
    var st = window.__lbGroupState;
    var img = document.getElementById("lb-gp-ava-img");
    var ph = document.getElementById("lb-gp-ava-ph");
    if (!img || !ph) return;
    var url = st.avatarPreview;
    if (!url && st.avatarChannelId) {
      url = "/miniapp/api/channels/" + st.avatarChannelId + "/avatar";
    }
    if (url) {
      img.src = url;
      img.hidden = false;
      ph.hidden = true;
    } else {
      img.hidden = true;
      img.removeAttribute("src");
      ph.hidden = false;
    }
  }

  function submitGroupCreate() {
    var msg = document.getElementById("lb-gp-msg");
    function show(t, ok) {
      if (!msg) return;
      msg.hidden = false;
      msg.textContent = t;
      msg.className = "lb-gp-msg " + (ok ? "ok" : "err");
    }
    var ids = Object.keys(window.__lbGroupSel || {}).map(function (x) { return parseInt(x, 10); }).filter(Boolean);
    if (ids.length < 2) {
      show("حداقل ۲ کانال از لیست بالا انتخاب کنید");
      return;
    }
    var name = ((document.getElementById("lb-gp-name") || {}).value || "").trim();
    if (!name) {
      show("نام مجموعه را بنویسید");
      return;
    }
    var st = window.__lbGroupState;
    var body = { name: name, channel_ids: ids };
    if (st.avatarChannelId) body.avatar_channel_id = st.avatarChannelId;

    fetch(lbApiBase() + "/groups/add", {
      method: "POST",
      credentials: "same-origin",
      headers: lbApiHeaders(),
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.text().then(function (txt) {
          var g = null;
          try { g = txt ? JSON.parse(txt) : null; } catch (e) {
            throw new Error(r.status === 404
              ? "آدرس ثبت مجموعه پیدا نشد (404)"
              : "پاسخ سرور JSON نبود (کد " + r.status + ")");
          }
          if (!r.ok || !g || !g.ok) {
            throw new Error((g && (g.message || g.error)) || ("خطا در ساخت مجموعه (" + r.status + ")"));
          }
          return g;
        });
      })
      .then(function (g) {
        show("مجموعه ثبت شد", true);
        if (window.lbToast) window.lbToast("مجموعه «" + name + "» ساخته شد");
        window.__lbGroupSel = {};
        st.open = false;
        st.avatarChannelId = null;
        st.avatarFile = null;
        if (st.avatarPreview) {
          URL.revokeObjectURL(st.avatarPreview);
          st.avatarPreview = null;
        }
        clearRowPickBindings();
        applyGroupOpenState();
        var nameInp = document.getElementById("lb-gp-name");
        if (nameInp) nameInp.value = "";
        updateAvatarButton();
        try {
          if (window.__lbHydrate) window.__lbHydrate();
          else window.dispatchEvent(new Event("lb:hydrate"));
        } catch (e) {}

      })
      .catch(function (err) {
        show(String((err && err.message) || err || "خطا"));
      });
  }


})();
