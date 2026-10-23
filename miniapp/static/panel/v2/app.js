/* LinkBan Mini App v2 — connected to live API */
(function () {
  'use strict';

  const API = (window.__LIVE_API || '/miniapp/api').replace(/\/$/, '');
  const MEDIA = window.__MEDIA_BASE || '/miniapp/media';

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const faDigits = '۰۱۲۳۴۵۶۷۸۹';
  const fa = (n) => String(n).replace(/\d/g, (d) => faDigits[d]);
  const faNum = (n) => fa(Number(n || 0).toLocaleString('en-US'));
  const faK = (n) => {
    n = Number(n) || 0;
    if (n >= 1000000) return fa((n / 1000000).toFixed(1)) + 'M';
    if (n >= 1000) return fa((n / 1000).toFixed(n >= 10000 ? 0 : 1)) + 'k';
    return fa(n);
  };

  const STATUS_LABEL = {
    draft: 'پیش‌نویس',
    waiting_banner: 'منتظر بنر',
    waiting_managers: 'منتظر پاسخ مدیر',
    waiting_customer_confirm: 'منتظر تأیید آگهی‌دهنده',
    waiting_payment: 'منتظر پرداخت',
    paid: 'پرداخت‌شده',
    completed: 'انجام‌شده',
    cancelled: 'لغو شده',
    rejected: 'رد شده',
  };

  const TIMELINE = [
    { key: 'waiting_banner', label: 'بنر' },
    { key: 'waiting_managers', label: 'مدیر' },
    { key: 'waiting_customer_confirm', label: 'تأیید' },
    { key: 'waiting_payment', label: 'پرداخت' },
    { key: 'paid', label: 'انتشار' },
    { key: 'completed', label: 'انجام' },
  ];

  const ST = {
    page: 'home',
    role: 'advertiser', // آگهی‌دهنده | manager | operator
    me: null,
    catalog: null,
    banners: [],
    bannerFeePolicy: { first_free_available: true, next_banner_fee_toman: 0 },
    businesses: [],
    activeBusinessId: null,
    bannerDraft: null,
    orders: [],
    wallet: null,
    filter: 'all',
    q: '',
    channelId: null,
    tariffId: null,
    selectedDay: null,
    orderTab: 'all',
    loading: false,
    // manager
    myChannels: [],
    myGroups: [],
    mgrOrders: [],
    mgrTariffs: [],
    mgrTab: 'inbox', // inbox | channels | tariffs
    selectedMgrChannel: null,
    // operator
    opBanners: [],
    opPayouts: [],
    opAssignments: [],
    opTab: 'banners', // banners|payouts|assign|settings
    opSettings: null,
    // banners | payouts | assign
    demoTickets: [],
  };

  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(t._tm);
    t._tm = setTimeout(() => t.classList.remove('on'), 2600);
  }

  function getInitData() {
    try {
      const w = window.Bale && window.Bale.WebApp;
      if (w && w.initData) return w.initData;
    } catch (e) {}
    return new URLSearchParams(location.search).get('initData') || '';
  }

  function debugId() {
    return new URLSearchParams(location.search).get('debug_bale_id') || '';
  }

  async function api(path, opts = {}) {
    const method = (opts.method || 'GET').toUpperCase();
    const headers = Object.assign({}, opts.headers || {});
    const initData = getInitData();
    const softUser = baleClientUser();
    if (initData) headers['X-Bale-Init-Data'] = initData;
    const dbg = debugId();
    if (dbg) headers['X-Bale-User-Id'] = dbg;

    let body = opts.body;
    if (body && !(body instanceof FormData) && typeof body === 'object') {
      headers['Content-Type'] = 'application/json';
      const extra = {};
      if (dbg && !body.debug_bale_id) extra.debug_bale_id = dbg;
      if (softUser && softUser.id && !body.soft_user) extra.soft_user = softUser;
      if (Object.keys(extra).length) body = Object.assign({}, extra, body);
      body = JSON.stringify(body);
    } else if (body instanceof FormData && dbg) {
      body.append('debug_bale_id', dbg);
    } else if (method !== 'GET' && softUser && softUser.id && (body == null || body === undefined)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify({ soft_user: softUser, ...(dbg ? { debug_bale_id: dbg } : {}) });
    }

    let url = path.startsWith('http') ? path : API + path;
    if (method === 'GET' && dbg && !url.includes('debug_bale_id')) {
      url += (url.includes('?') ? '&' : '?') + 'debug_bale_id=' + encodeURIComponent(dbg);
    }

    let res;
    const controller = opts.timeoutMs && typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timeout = controller ? setTimeout(() => controller.abort(), Number(opts.timeoutMs)) : null;
    try { res = await fetch(url, { method, headers, body, credentials: 'same-origin', ...(controller ? { signal: controller.signal } : {}) }); }
    catch (networkError) {
      if (networkError && networkError.name === 'AbortError') throw new Error('مهلت دریافت اطلاعات به پایان رسید.');
      throw new Error('ارتباط با سرور برقرار نشد. اتصال اینترنت را بررسی و دوباره تلاش کنید.');
    } finally { if (timeout) clearTimeout(timeout); }
    let data;
    try {
      data = await res.json();
    } catch (e) {
      data = { ok: false, error: 'bad_json', message: 'پاسخ نامعتبر از سرور' };
    }
    if (!res.ok && !data.message) {
      data.message = data.error || ('خطا ' + res.status);
    }
    return data;
  }

  /* ——— Icons ——— */
  const ICONS = {
    home: '<path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V10Z"/><path d="M9 22V12h6v10"/>',
    orders: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="m4 17 5-4 3 2 3-3 5 5"/>',
    wallet: '<path d="M4 6.5h14a2 2 0 0 1 2 2V18H5a2 2 0 0 1-2-2V6a3 3 0 0 1 3-3h11"/><path d="M15 11h6v4h-6a2 2 0 0 1 0-4Z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
    back: '<path d="m14 18-6-6 6-6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    moon: '<path d="M20 15.2A8 8 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2Z"/>',
    sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    megaphone: '<path d="m3 11 15-6v14L3 13v-2Z"/><path d="m6 14 1 6h4l-1-5"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18"/>',
    sparkles: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="m19 15 1.2 2.8L23 19l-2.8 1.2L19 23l-1.2-2.8L15 19l2.8-1.2L19 15Z"/>',
    at: '<circle cx="12" cy="12" r="9"/><path d="M16 12v2a2 2 0 0 0 4 0v-2a8 8 0 1 0-3 6.2"/><circle cx="12" cy="12" r="3"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    chart: '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-5 5"/>',
    hand: '<path d="M8 11V5a2 2 0 0 1 4 0v5-7a2 2 0 0 1 4 0v8-5a2 2 0 0 1 4 0v8a7 7 0 0 1-7 7h-1a7 7 0 0 1-6-3l-3-4a2 2 0 0 1 3-3l2 2"/>',
    'chevron-left': '<path d="m15 18-6-6 6-6"/>',
    'arrow-down-up': '<path d="m3 8 4-4 4 4M7 4v12M21 16l-4 4-4-4M17 20V8"/>',
    sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4"/>',
    'shield-check': '<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/>',
    'user-round': '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
    'badge-check': '<path d="m12 3 2.2 1.2 2.5-.1 1.3 2.1 2.1 1.3-.1 2.5L21 12l-1.2 2.2.1 2.5-2.1 1.3-1.3 2.1-2.5-.1L12 21l-2.2-1.2-2.5.1L6 17.8 3.9 16.5l.1-2.5L3 12l1.2-2.2-.1-2.5 2.1-1.3 1.3-2.1 2.5.1L12 3Z"/><path d="m9 12 2 2 4-4"/>',
    inbox: '<path d="M4 4h16v12h-4l-2 3h-4l-2-3H4V4Z"/><path d="M4 12h4l2 3h4l2-3h4"/>',
    refresh: '<path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.5 9A7 7 0 0 1 18 6l2 6M4 12l2 6a7 7 0 0 0 12.5-3"/>',
    'refresh-cw': '<path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.5 9A7 7 0 0 1 18 6l2 6M4 12l2 6a7 7 0 0 0 12.5-3"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 10v6M14 10v6"/>',
    'file-text': '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 12h7M9 16h7"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.1 0l3-3a5 5 0 0 0-7.1-7.1l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.1 0l-3 3A5 5 0 0 0 11 21.1l1.7-1.7"/>',
    copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    'building-2': '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18M3 22h18"/><path d="M10 6h1M13 6h1M10 10h1M13 10h1M10 14h1M13 14h1M10 18h1M13 18h1"/>',
    'shopping-bag': '<path d="M5 8h14l1 13H4L5 8Z"/><path d="M9 9V6a3 3 0 0 1 6 0v3"/>' ,
    'book-open': '<path d="M12 7v14"/><path d="M3 5.5A2.5 2.5 0 0 1 5.5 3H12v18H5.5A2.5 2.5 0 0 0 3 23V5.5ZM21 5.5A2.5 2.5 0 0 0 18.5 3H12v18h6.5A2.5 2.5 0 0 1 21 23V5.5Z"/>',
    headset: '<path d="M3 14v-3a9 9 0 0 1 18 0v3"/><path d="M5 14h2a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H6a3 3 0 0 1-3-3v-2a2 2 0 0 1 2-2ZM19 14h-2a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h1a3 3 0 0 0 3-3v-2a2 2 0 0 0-2-2Z"/>',
    'panels-top-left': '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'trending-up': '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    landmark: '<path d="m3 10 9-7 9 7"/><path d="M4 10h16M5 10v9M9 10v9M15 10v9M19 10v9M3 21h18"/>',
    'arrow-up-left': '<path d="M17 7 7 17M7 7v10h10"/>',    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7h.01"/>',
    'messages-square': '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/><path d="M8 10h8M8 14h5"/>',
    'trash-2': '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 10v6M14 10v6"/>',
    ticket: '<path d="M3 8V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v3a3 3 0 0 0 0 6v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3a3 3 0 0 0 0-6Z"/><path d="M13 5v2M13 11v2M13 17v2"/>',
    'calendar-check': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18m-13 5 2 2 4-4"/>',
    'coins': '<circle cx="8" cy="8" r="5"/><path d="M2 8v3a6 6 0 0 0 11 3M8 3v10M16 13c3 0 6 1.3 6 3s-3 3-6 3-6-1.3-6-3 3-3 6-3Zm-6 3v3c0 1.7 3 3 6 3s6-1.3 6-3v-3"/>',
    'circle-help': '<circle cx="12" cy="12" r="9"/><path d="M9.6 9a2.5 2.5 0 1 1 4.7 1.2c-.8 1.1-2.3 1.2-2.3 3M12 17h.01"/>',
    store: '<path d="M3 10v11h18V10M2 10l2-7h16l2 7a3 3 0 0 1-5 2 3 3 0 0 1-5 0 3 3 0 0 1-5 0 3 3 0 0 1-5-2Z"/><path d="M9 21v-6h6v6"/>',
    'shield-alert': '<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="M12 8v5M12 16h.01"/>',
    'upload-cloud': '<path d="M16 16l-4-4-4 4M12 12v9"/><path d="M20 16.5A4.5 4.5 0 0 0 18 8h-1.3A6 6 0 1 0 5 16"/>',
    'check-circle': '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',
    'calendar-clock': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18"/><circle cx="16.5" cy="16.5" r="3"/><path d="M16.5 15v2l1.2.7"/>',
    'send': '<path d="m22 2-7 20-4-9-9-4 20-7Z"/><path d="M22 2 11 13"/>',

  };
  function icon(name, size = 20) {
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`;
  }


  function baleClientUser() {
    try {
      if (window.__LB_USER) return window.__LB_USER;
      const w = window.Bale && window.Bale.WebApp;
      if (w && w.initDataUnsafe && w.initDataUnsafe.user) return w.initDataUnsafe.user;
    } catch (e) {}
    return null;
  }

  function displayName(me) {
    const u = (me && me.user) || me || {};
    const bu = baleClientUser() || {};
    const fn = (u.first_name || bu.first_name || bu.firstName || '').trim();
    const ln = (u.last_name || bu.last_name || bu.lastName || '').trim();
    const full = [fn, ln].filter(Boolean).join(' ').trim();
    if (full) return full;
    if (u.full_name) return String(u.full_name).trim();
    const handle = (u.handle || '').replace(/^@/, '') || u.username || bu.username || '';
    return handle || 'دوست لینک‌بان';
  }

  function userPhotoUrl(me) {
    const u = (me && me.user) || me || {};
    const bu = baleClientUser() || {};
    return (u.photo_url || bu.photo_url || bu.photoUrl || '').trim();
  }

  function userInitials(me) {
    const name = displayName(me);
    const parts = name.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).slice(0, 2);
    return (name[0] || 'ک').toUpperCase();
  }

  function paintHeaderProfile() {
    const btn = document.getElementById('btnProfile');
    if (!btn) return;
    const photo = userPhotoUrl(ST.me);
    const letter = userInitials(ST.me);
    if (photo) {
      btn.innerHTML = `<img src="${esc(photo)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:50%" onerror="this.remove();this.parentNode.textContent='${esc(letter)}'"/>`;
    } else {
      btn.textContent = letter;
    }
    btn.title = displayName(ST.me);
  }

  function openSheet(html) {
    $('#sheetBody').innerHTML = html;
    $('#sheet').classList.add('on');
  }
  function closeSheet() {
    $('#sheet').classList.remove('on');
  }

  function themeRays() {
    let s = '';
    for (let i = 0; i < 8; i++) {
      const a = (Math.PI / 4) * i;
      s += `<circle cx="${(12 + Math.cos(a) * 10).toFixed(2)}" cy="${(12 + Math.sin(a) * 10).toFixed(2)}" r="1.1"/>`;
    }
    return s;
  }

  function themeToggleSvg() {
    return (
      '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">' +
      '<mask id="lb-tt-m"><rect width="24" height="24" fill="#fff"/><circle class="tt-cut" cx="8" cy="8" r="7" fill="#000"/></mask>' +
      '<circle class="tt-core" cx="13" cy="13" r="8.5" fill="currentColor" mask="url(#lb-tt-m)"/>' +
      '<g class="tt-rays" fill="currentColor">' + themeRays() + '</g>' +
      '<g class="tt-stars" fill="currentColor">' +
      '<path d="M4.5 2.2l.55 1.35 1.35.55-1.35.55-.55 1.35-.55-1.35L2.6 4.1l1.35-.55z"/>' +
      '<path d="M9.2 1l.35.85.85.35-.85.35-.35.85-.35-.85-.85-.35.85-.35z"/>' +
      '</g></svg>'
    );
  }

  function paintThemeButton(btn) {
    if (!btn) return;
    const dark = document.documentElement.dataset.theme === 'dark';
    btn.setAttribute('aria-label', dark ? 'حالت روشن' : 'حالت تیره');
    btn.title = dark ? 'حالت روشن' : 'حالت تیره';
  }

  function setTheme(dark, evt) {
    const next = dark ? 'dark' : 'light';
    const root = document.documentElement;
    const apply = () => {
      root.dataset.theme = next;
      root.style.colorScheme = next;
      try { localStorage.setItem('lb.theme', next); } catch (e) {}
      paintThemeButton(document.getElementById('btnTheme'));
      const th2 = document.getElementById('btnTheme2');
      if (th2) th2.classList.toggle('on', dark);
      try {
        const w = window.Bale && Bale.WebApp;
        if (w && typeof w.setHeaderColor === 'function') {
          w.setHeaderColor('#0E4A5C');
        }
      } catch (e) {}
    };
    const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (document.startViewTransition && !reduce && evt && evt.currentTarget) {
      const box = evt.currentTarget.getBoundingClientRect();
      root.style.setProperty('--tt-x', (box.x + box.width / 2) + 'px');
      root.style.setProperty('--tt-y', (box.y + box.height / 2) + 'px');
      document.startViewTransition(apply);
    } else {
      root.classList.add('theme-anim');
      apply();
      setTimeout(() => root.classList.remove('theme-anim'), 280);
    }
  }

  /* ——— Data loaders ——— */
  async function loadMe() {
    const d = await api('/me');
    if (!d.ok) throw new Error(d.message || d.error || 'auth');
    // merge Bale client profile
    try {
      const bu = baleClientUser();
      if (bu && d.user) {
        if (!d.user.first_name && (bu.first_name || bu.firstName)) d.user.first_name = bu.first_name || bu.firstName;
        if (!d.user.last_name && (bu.last_name || bu.lastName)) d.user.last_name = bu.last_name || bu.lastName;
        if (bu.photo_url || bu.photoUrl) d.user.photo_url = bu.photo_url || bu.photoUrl;
        if (d.user.first_name || d.user.last_name) {
          d.user.full_name = [d.user.first_name, d.user.last_name].filter(Boolean).join(' ');
        }
      }
    } catch (e) {}
    ST.me = d;
    ST.wallet = d.wallet || { available: 0, pending: 0 };
    try { paintHeaderProfile(); } catch (e) {}
    // restore preferred role if valid
    try {
      const saved = localStorage.getItem('lb.role');
      if (saved === 'manager' || saved === 'advertiser' || (saved === 'operator' && d.is_operator)) {
        ST.role = saved;
      } else if (d.channel_count > 0 && ST.role === 'advertiser') {
        /* stay advertiser by default */
      }
    } catch (e) {}
    return d;
  }

  async function loadMyChannels() {
    const d = await api('/channels');
    if (!d.ok) { ST.myChannels = []; ST.myGroups = []; return; }
    ST.myChannels = d.channels || [];
    ST.myGroups = d.groups || [];
  }

  async function loadMgrOrders() {
    const d = await api('/orders');
    if (!d.ok) { ST.mgrOrders = []; return; }
    ST.mgrOrders = (d.orders || []).filter((o) => o.inbox || o.manager_status);
  }

  async function loadMgrTariffs() {
    const d = await api('/tariffs');
    if (!d.ok) throw new Error(d.message || d.error || 'دریافت تعرفه‌ها ناموفق بود');
    ST.mgrTariffs = d.tariffs || d.items || [];
    return ST.mgrTariffs;
  }

  async function loadOpTickets() {
    try {
      const d = await api('/tickets');
      if (d.ok) ST.opTickets = d.tickets || [];
    } catch (e) { ST.opTickets = []; }
  }

  async function loadOpSettings() {
    try {
      const d = await api('/operator/settings');
      if (d.ok) ST.opSettings = d.settings || {};
    } catch (e) { ST.opSettings = null; }
  }

  async function loadOpBanners() {
    const d = await api('/operator/banners');
    if (!d.ok) { ST.opBanners = []; return; }
    ST.opBanners = d.requests || d.banners || [];
  }

  async function loadOpPayouts() {
    const d = await api('/operator/payouts');
    if (!d.ok) { ST.opPayouts = []; return; }
    ST.opPayouts = d.payouts || [];
  }

  async function loadOpAssignments() {
    const d = await api('/operator/assignments');
    if (!d.ok) { ST.opAssignments = []; return; }
    ST.opAssignments = d.items || [];
  }

  function setRole(role) {
    ST.role = role;
    try { localStorage.setItem('lb.role', role); } catch (e) {}
    if (role === 'manager') ST.page = 'mgr-home';
    else if (role === 'operator') ST.page = 'op-home';
    else ST.page = 'home';
  }

  async function loadCatalog() {
    const q = ST.q ? '?q=' + encodeURIComponent(ST.q) : '';
    const d = await api('/catalog' + q);
    if (!d.ok) throw new Error(d.message || 'catalog');
    ST.catalog = d;
    return d;
  }

  async function loadBusinesses({ refreshMetadata = false } = {}) {
    try { ST.activeBusinessId = Number(localStorage.getItem('lb.activeBusinessId') || 0) || null; } catch (e) {}
    const d = await api('/businesses');
    if (!d.ok) throw new Error(d.message || 'دریافت کسب‌وکارها ناموفق بود');
    ST.businesses = d.businesses || [];
    if (ST.activeBusinessId && !ST.businesses.some((b) => b.id === ST.activeBusinessId)) ST.activeBusinessId = null;
    try { if (ST.activeBusinessId) localStorage.setItem('lb.activeBusinessId', String(ST.activeBusinessId)); else localStorage.removeItem('lb.activeBusinessId'); } catch (e) {}
    // The server enforces a 24-hour cooldown, including failed attempts. Parallel requests
    // keep opening the businesses screen responsive when a customer has many businesses.
    if (refreshMetadata) {
      const candidates = ST.businesses.filter((b) => b.kind === 'bale' && b.source_ref);
      const refreshed = await Promise.allSettled(candidates.map((b) => api('/businesses/metadata', {
        method: 'POST', timeoutMs: 15000, body: { business_id: Number(b.id) },
      })));
      refreshed.forEach((r) => {
        if (r.status !== 'fulfilled' || !r.value || !r.value.ok || !r.value.business) return;
        const fresh = r.value.business;
        ST.businesses = ST.businesses.map((old) => old.id === fresh.id ? fresh : old);
      });
    }
    return ST.businesses;
  }

  async function loadBanners() {
    const d = await api('/banners');
    if (!d.ok) { ST.banners = []; return; }
    ST.banners = d.banners || d.items || [];
    if (d.fee_policy) ST.bannerFeePolicy = d.fee_policy;
    // سناریو: فعلاً رایگان
    ST.bannerFeePolicy = Object.assign({}, ST.bannerFeePolicy || {}, { next_banner_fee_toman: 0, first_free_available: true });
    return ST.banners;
  }


  async function requestNewBanner() {
    try {
      const d = await api('/banners/request-new', { method: 'POST', body: {} });
      if (!d.ok) throw new Error(d.message || d.error || 'request-new');
      toast(d.message || 'پیام بازو ارسال شد؛ بنر را در گفتگو بفرستید.');
      try {
        if (window.Bale && Bale.WebApp && typeof Bale.WebApp.close === 'function') {
          setTimeout(function () { try { Bale.WebApp.close(); } catch (e) {} }, 400);
        }
      } catch (e) {}
    } catch (e) {
      toast(e.message || 'ارسال درخواست بنر ناموفق بود');
    }
  }

  async function loadOrders() {
    const d = await api('/my-orders');
    if (!d.ok) {
      const d2 = await api('/orders');
      ST.orders = (d2.orders || d2.items || []);
      return;
    }
    ST.orders = d.orders || d.items || [];
  }

  async function loadWallet() {
    const d = await api('/wallet');
    if (d.ok) ST.wallet = d.wallet || d;
    return ST.wallet;
  }

  async function loadCalendarDays(tariffId) {
    if (!tariffId) return [];
    const d = await api('/calendar?tariff_id=' + encodeURIComponent(tariffId) + '&for=customer&days=62');
    if (!d.ok) return [];
    ST.calDays = d.days || [];
    return ST.calDays;
  }


  /* ——— Views ——— */
  function channelMap() {
    const m = {};
    (ST.catalog?.channels || []).forEach((c) => { m[c.id] = c; });
    return m;
  }

  function filteredTariffs() {
    let list = ST.catalog?.tariffs || [];
    const ch = channelMap();
    if (ST.filter === 'pkg') list = list.filter((t) => t.is_package);
    if (ST.filter === 'cheap') {
      list = list.slice().sort((a, b) => (Number(a.price) || 0) - (Number(b.price) || 0));
    } else if (ST.filter === 'views') {
      list = list.slice().sort((a, b) => (Number(b.avg_views || ch[b.channel_id]?.avg_views) || 0) - (Number(a.avg_views || ch[a.channel_id]?.avg_views) || 0));
    } else if (ST.filter === 'members') {
      list = list.slice().sort((a, b) => (Number(b.members_count || ch[b.channel_id]?.members_count) || 0) - (Number(a.members_count || ch[a.channel_id]?.members_count) || 0));
    }
    return list;
  }

  function groupByChannel(tariffs) {
    const ch = channelMap();
    const groups = {};
    tariffs.forEach((t) => {
      const key = t.is_package ? 'g:' + t.group_id : 'c:' + t.channel_id;
      if (!groups[key]) {
        const c = t.channel_id ? ch[t.channel_id] : null;
        groups[key] = {
          key,
          channel: c,
          name: t.owner || c?.name || 'کانال',
          link: c?.link || '',
          members: t.members_count || c?.members_count || 0,
          views: t.avg_views || c?.avg_views || 0,
          ready: c?.ready_publish,
          mode: c?.publish_mode,
          isPkg: t.is_package,
          avatar: c?.avatar_url,
          tariffs: [],
        };
      }
      groups[key].tariffs.push(t);
    });
    return Object.values(groups).sort((a, b) => (b.members || 0) - (a.members || 0));
  }

  function renderHome() {
    const name = displayName(ST.me);
    const wr = ST.wallet || ST.me?.wallet || {};
    const w = wr.balance || wr;
    const balance = Number(w.credit ?? w.available ?? 0);
    const orders = ST.orders || [];
    const active = orders.filter(o => !['completed','cancelled','rejected'].includes(o.status));
    const waiting = orders.filter(o => ['waiting_managers','waiting_customer_confirm','waiting_payment'].includes(o.status));
    const published = orders.filter(o => ['published','completed','paid'].includes(o.status));
    const approvedBanners = (ST.banners || []).filter(b => (b.stage || b.status || 'ready') !== 'rejected' && b.is_active !== false).length;
    const suggestions = groupByChannel(filteredTariffs()).slice(0, 2);
    const miniCards = suggestions.map(g => {
      const minPrice = g.tariffs.length ? Math.min(...g.tariffs.map(t => Number(t.price)||0)) : 0;
      const chId = g.key;
      return `<article class="home-channel-card" data-open-ch="${esc(chId)}">
        <div class="home-channel-art"><span>${icon('megaphone',24)}</span><i></i></div>
        <div class="home-channel-info"><strong>${esc(g.name)}</strong><small>${faK(g.members)} عضو · ${faK(g.views)} بازدید</small><b>${faNum(minPrice)} <small>تومان</small></b></div>
        <span class="home-channel-arrow">${icon('chevron-left',16)}</span>
      </article>`;
    }).join('');
    return `
      <section class="home-welcome">
        <div class="home-welcome-top"><span class="home-kicker">${icon('sparkles',13)} فضای تبلیغاتی شما</span><span class="home-online-dot"><i></i> فعال</span></div>
        <h2>سلام ${esc(name)}،<br/><span>وقت دیده‌شدن کسب‌وکارت رسیده!</span></h2>
        <p>از انتخاب جایگاه تا پیگیری انتشار، همه‌چیز همین‌جاست.</p>
        <div class="home-hero-actions"><button id="btnHomeMarket" class="home-hero-primary">${icon('search',16)} کشف کانال‌ها</button><button id="btnHomeBanner" class="home-hero-secondary">${icon('plus',16)} ثبت بنر</button></div>
        <div class="home-hero-decoration" aria-hidden="true"><div class="home-orbit home-orbit-a"></div><div class="home-orbit home-orbit-b"></div><div class="home-mega-icon">${icon('megaphone',34)}</div><span class="home-spark home-spark-a">✦</span><span class="home-spark home-spark-b">✧</span></div>
      </section>
      <section class="home-wallet-card">
        <div class="home-wallet-top"><span class="home-wallet-icon">${icon('wallet',21)}</span><span>اعتبار قابل استفاده</span><button id="btnHomeWallet" aria-label="رفتن به کیف پول">${icon('chevron-left',17)}</button></div>
        <div class="home-wallet-value">${faNum(balance)} <small>تومان</small></div>
        <div class="home-wallet-bottom"><span>${icon('shield-check',13)} اعتبار امن لینک‌بان</span><button id="btnHomeTopup">${icon('plus',14)} افزایش موجودی</button></div>
      </section>
      <div class="home-section-head"><div><span class="eyebrow">نمای کلی فعالیت</span><h2>سفارش‌های شما</h2></div><button id="btnHomeOrders" class="text-action">همهٔ سفارش‌ها ${icon('chevron-left',15)}</button></div>
      <section class="home-order-overview">
        <button class="home-order-metric metric-wait" id="btnHomeWaiting"><span class="home-metric-icon">${icon('clock',17)}</span><strong>${fa(waiting.length)}</strong><small>در انتظار اقدام</small></button>
        <button class="home-order-metric metric-active" id="btnHomeActive"><span class="home-metric-icon">${icon('panels-top-left',17)}</span><strong>${fa(active.length)}</strong><small>در حال انجام</small></button>
        <button class="home-order-metric metric-done" id="btnHomeDone"><span class="home-metric-icon">${icon('check',17)}</span><strong>${fa(published.length)}</strong><small>منتشرشده / تمام‌شده</small></button>
      </section>
      <section class="home-banner-callout">
        <div class="home-banner-visual"><div class="home-banner-poster">${icon('image',28)}<span>AD</span></div><i></i><i></i></div>
        <div class="home-banner-copy"><span class="home-banner-label">کتابخانهٔ خلاقیت</span><strong>بنرت آمادهٔ انتشار است؟</strong><p>${approvedBanners ? `${fa(approvedBanners)} بنر آماده برای سفارش داری.` : 'بنرت را ثبت کن تا پس از ثبت، در سفارش‌ها از آن استفاده کنی.'}</p><button id="btnHomeManageBanners">مدیریت بنرها ${icon('chevron-left',14)}</button></div>
      </section>
      <div class="home-section-head"><div><span class="eyebrow">پیشنهادهای بازار</span><h2>کانال‌های منتخب</h2></div><button class="text-action" id="btnHomeMarketAll">مشاهدهٔ بازار ${icon('chevron-left',15)}</button></div>
      <div class="home-channel-list">${miniCards || `<div class="home-soft-empty"><span>${icon('search',21)}</span><div><strong>هنوز پیشنهادی نداریم</strong><small>بازار را باز کن تا جایگاه‌های موجود را ببینی.</small></div><button id="btnHomeMarketEmpty">${icon('chevron-left',15)}</button></div>`}</div>
      <div class="home-bottom-note">${icon('shield-check',16)} <span>پیش از ثبت نهایی، زمان، تعرفه و وضعیت هر سفارش را بررسی می‌کنی.</span></div>`;
  }

  function renderMarket() {
    const list = groupByChannel(filteredTariffs());
    const tariffCount = (ST.catalog?.tariffs || []).length;
    const cards = list.length
      ? list.map((g, index) => {
          const minPrice = g.tariffs.length ? Math.min(...g.tariffs.map((t) => Number(t.price) || 0)) : 0;
          const letter = (g.name || '?').charAt(0);
          const av = g.avatar
            ? `<img src="${esc(g.avatar)}" alt="" onerror="this.parentNode.textContent='${esc(letter)}'"/>`
            : `<span>${esc(letter)}</span>`;
          return `<article class="market-card" data-open-ch="${g.key}" style="--card-order:${Math.min(index,10)}">
            <div class="market-card-main">
              <div class="ch-ava market-avatar">${av}</div>
              <div class="market-channel-copy">
                <div class="market-title-row"><h3 class="ch-title">${esc(g.name)}</h3>${g.isPkg ? '<span class="badge package-badge">بسته</span>' : ''}</div>
                <div class="ch-sub market-handle">${g.link ? icon('at',13) + '<span>' + esc(String(g.link).replace(/^@/, '')) + '</span>' : '<span>مشخصات کانال</span>'}</div>
                <div class="market-badges">
                  <span class="badge muted">${icon('users',12)}${faK(g.members)} عضو</span>
                  ${g.views ? `<span class="badge muted">${icon('chart',12)}${faK(g.views)} بازدید</span>` : ''}
                  <span class="badge muted">${fa(g.tariffs.length)} تعرفه</span>
                </div>
              </div>
            </div>
            <div class="market-card-footer">
              <div class="market-card-note"><span class="market-status-dot is-ready"></span><span>انتشار خودکار پس از پرداخت</span></div>
              <div class="market-price"><span class="market-price-label">شروع از</span><strong>${faNum(minPrice)} <small>تومان</small></strong></div>
              <span class="market-open" aria-hidden="true">${icon('chevron-left',17)}</span>
            </div>
          </article>`;
        }).join('')
      : `<div class="empty market-empty"><div class="empty-visual">${icon('search',28)}</div><strong>چیزی پیدا نشد</strong><p>فیلترها را تغییر بده یا عبارت دیگری جستجو کن.</p></div>`;

    return `
      <section class="market-hero">
        <div class="market-hero-orbit orbit-one"></div><div class="market-hero-orbit orbit-two"></div>
        <div class="market-hero-content">
          <div class="market-kicker">${icon('sparkles',14)} بازار تبلیغات بله</div>
          <h2>جای درست برای<br><span>دیده‌شدن کسب‌وکارت</span></h2>
          <p>کانال مناسب را پیدا کن، تعرفه‌ها را مقایسه کن و با خیال راحت سفارش بده.</p>
          <div class="market-hero-stats">
            <div><strong>${fa(list.length)}</strong><span>کانال و بسته</span></div>
            <i></i>
            <div><strong>${fa(tariffCount)}</strong><span>تعرفه فعال</span></div>
          </div>
        </div>
        <div class="market-hero-art" aria-hidden="true"><div class="hero-art-disc">${icon('megaphone',36)}</div><span class="art-spark spark-a">✦</span><span class="art-spark spark-b">✧</span><span class="art-pill">تبلیغ هوشمند</span></div>
      </section>
      <div class="market-section-heading"><div><span class="eyebrow">انتخاب با شماست</span><h2>کشف کانال‌ها</h2></div><span class="market-total">${fa(list.length)} مورد</span></div>
      <div class="search market-search">${icon('search')}<input id="qInput" placeholder="نام کانال یا موضوع را جستجو کن…" value="${esc(ST.q)}"/></div>
      <div class="filters market-filters" id="homeFilters">
        ${[['all','همه'],['members','پربازدید عضو'],['views','بازدید'],['cheap','اقتصادی'],['pkg','بسته']].map(([k,l]) =>
          `<button class="chip ${ST.filter===k?'on':''}" data-f="${k}">${l}</button>`).join('')}
      </div>
      <div class="market-list-heading"><strong>کانال‌های پیشنهادی</strong><span>${icon('arrow-down-up',14)} شروع قیمت‌ها</span></div>
      <div id="catalog" class="market-list">${cards}</div>
      <div class="market-trust-note">${icon('shield-check',17)} <span>جزئیات تعرفه و زمان انتشار پیش از ثبت سفارش نمایش داده می‌شود.</span></div>`;
  }

  function renderChannel() {
    const groups = groupByChannel(ST.catalog?.tariffs || []);
    const g = groups.find(x => x.key === ST.channelId) || groups[0];
    if (!g) return `<div class="scenario-empty"><span>${icon('search',26)}</span><h3>کانال پیدا نشد</h3><p>به بازار برگرد و جایگاه دیگری را انتخاب کن.</p><button class="btn btn-primary" id="btnBackMarket">بازگشت به بازار</button></div>`;
    const c = g.channel || {};
    const tariffs = g.tariffs.map((t,index) => `<button type="button" class="tariff-row scenario-tariff-row ${ST.tariffId===t.id?'on':''}" data-tariff="${t.id}"><span class="scenario-tariff-check">${ST.tariffId===t.id?icon('check',15):''}</span><span class="grow"><strong>${esc(t.name || (t.duration_hours + ' ساعته'))}</strong><small>${fa(t.duration_hours)} ساعت نمایش · ${t.start_hour != null ? 'شروع '+fa(t.start_hour)+':۰۰' : 'زمان‌بندی با هماهنگی'}</small></span><span class="scenario-tariff-price">${faNum(t.price)} <small>تومان</small></span></button>`).join('');
    const av = g.avatar ? `<img src="${esc(g.avatar)}" alt="" onerror="this.parentNode.textContent='${esc((g.name||'ک').slice(0,1))}'"/>` : esc((g.name||'ک').slice(0,1));
    return `<section class="channel-detail-hero"><div class="channel-detail-cover"><div class="channel-detail-orbit"></div><span class="channel-detail-mode">${icon(c.ready_publish?'check':'hand',13)} ${c.ready_publish?'آمادهٔ انتشار':'انتشار دستی'}</span><div class="channel-detail-avatar">${av}</div><span class="channel-detail-cover-art">${icon('megaphone',28)}</span></div><div class="channel-detail-title"><span class="eyebrow">جایگاه تبلیغاتی</span><h2>${esc(g.name)}</h2><p>${c.link ? '@'+esc(String(c.link).replace(/^@/,'')) : 'کانال منتخب برای تبلیغ'}</p></div><div class="channel-detail-stats"><div><span>${icon('users',16)}</span><strong>${faK(g.members)}</strong><small>عضو</small></div><div><span>${icon('chart',16)}</span><strong>${faK(g.views)}</strong><small>میانگین بازدید</small></div><div><span>${icon('clock',16)}</span><strong>${g.ready?'خودکار':'هماهنگی'}</strong><small>روش انتشار</small></div></div></section>
      <div class="channel-proof-note">${icon('shield-check',16)} <span>زمان و تعرفه پیش از ثبت نهایی قابل بررسی است.</span></div>
      <div class="home-section-head channel-tariff-heading"><div><span class="eyebrow">انتخاب هوشمند</span><h2>تعرفهٔ مناسب را انتخاب کن</h2></div><span class="market-total">${fa(g.tariffs.length)} گزینه</span></div>
      <div class="channel-tariff-list">${tariffs || `<div class="scenario-empty compact-scenario-empty"><span>${icon('wallet',23)}</span><h3>تعرفه‌ای در دسترس نیست</h3><p>در حال حاضر برای این کانال تعرفهٔ فعالی ثبت نشده است.</p></div>`}</div>
      <div class="channel-sticky-note">${icon('info',15)} <span>پس از انتخاب تعرفه، روزهای آزاد و جزئیات نهایی سفارش نمایش داده می‌شوند.</span></div>
      <button class="btn btn-primary btn-block channel-continue" id="btnPickTariff" ${ST.tariffId?'':'disabled'}>انتخاب زمان انتشار ${icon('chevron-left',16)}</button>`;
  }

  function modeLabel(m) {
    return ({ bot: 'ارسال خودکار (ربات)', linkyar: 'ارسال با لینک‌یار', manual: 'انتشار دستی' })[m] || m;
  }

  function renderBanners() {
    const q = (ST.bannerQuery || '').trim();
    const kind = ST.bannerKind || 'all';
    let allBanners = (ST.banners || []).filter((b) => {
      if (kind === 'text' && b.media_kind && b.media_kind !== 'text') return false;
      if (kind === 'photo' && !(b.media_kind || '').match(/photo|image|document/)) return false;
      if (kind === 'video' && !(b.media_kind || '').match(/video|animation/)) return false;
      if (q && !(String(b.title || b.caption || '')).includes(q)) return false;
      return true;
    });
    // فقط تأییدشده‌ها در مینی‌اپ
    allBanners = allBanners.filter((b) => {
      const st = b.stage || b.status || 'ready';
      return st === 'ready' || st === 'approved' || st === 'ok' || !b.stage;
    });
    const waitingBanners = 0;
    const activeId = (ST.businesses || []).find((x) => x.active_banner_id)?.active_banner_id
      || ST.activeBannerId;
    const rows = allBanners.map((b) => {
      const st = b.stage || b.status || 'ready';
      const isActive = activeId && Number(activeId) === Number(b.id);
      const badge = isActive
        ? '<span class="badge ok">بنر فعال</span>'
        : (st === 'approved' || st === 'ok' || st === 'ready')
        ? '<span class="badge ok">آماده سفارش</span>'
        : st === 'rejected'
        ? '<span class="badge danger">رد شده</span>'
        : '<span class="badge warn">در انتظار</span>';
      const thumb = b.media_url
        ? `<img class="banner-thumb" src="${esc(b.media_url)}" alt=""/>`
        : `<div class="text-banner">متن</div>`;
      return `<article class="banner-library-card">${thumb}<div class="grow"><span class="banner-card-overline">${esc(b.business_name || 'کتابخانهٔ محتوا')}</span><div class="title">${esc(b.title || b.display_title || 'بنر')}</div><div class="sub">${esc((b.caption || '').slice(0, 80))}</div><div class="banner-card-status">${badge}</div></div><span class="banner-card-arrow">${icon('chevron-left',16)}</span></article>`;
    }).join('') || `<div class="scenario-empty"><span>${icon('image',26)}</span><h3>کتابخانه‌ات هنوز خالی است</h3><p>اولین بنر را برای یکی از کسب‌وکارهایت ثبت کن؛ وضعیت بررسی‌اش همین‌جا می‌ماند.</p><button class="btn btn-soft" id="btnEmptyBannerCreate">${icon('plus',15)} ثبت اولین بنر</button></div>`;

    return `
      <section class="banners-intro page-intro">
        <div class="page-intro-icon">${icon('image',25)}</div>
        <div class="page-intro-copy"><span class="eyebrow">محتوای تبلیغاتی شما</span><h2>کتابخانهٔ بنرها</h2><p>بنرها را ثبت کن و وضعیت بررسی هرکدام را از همین‌جا دنبال کن.</p></div>
        <div class="banner-intro-count"><strong>${fa(allBanners.length)}</strong><span>بنر ثبت‌شده</span><small>${fa(waitingBanners)} در انتظار</small></div>
      </section>
      <p class="hint page-note">بنر می‌تواند تصویر، ویدیو یا <strong>فقط متن</strong> باشد. پس از ثبت پشتیبانی تأیید می‌شود.</p>
      <div class="bot-hint">
        <strong>از ربات هم می‌توانید بنر بفرستید:</strong>
        بنر را به بازوی لینک‌بان فوروارد کنید؛ بعد از ثبت، اینجا نمایش داده می‌شود.
      </div>
      <button class="btn btn-primary btn-block btn-new-banner" id="btnNewBanner" style="margin-bottom:12px">${icon('plus',17)} ثبت بنر جدید</button>
      <div class="section-heading list-section-heading"><div><span class="eyebrow">آرشیو محتوا</span><h2>بنرهای من</h2></div><span class="market-total">${fa(allBanners.length)} مورد</span></div>
      <div id="bannersList" class="banner-list">${rows}</div>`;
  }

  function renderBusinesses() {
    const rows = (ST.businesses || []).map((b) => `
      <article class="business-workspace-card ${ST.activeBusinessId===b.id?'is-active':''}">
        <div class="business-card-top"><div class="business-card-avatar">${b.avatar_url ? `<img src="${esc(b.avatar_url)}" alt=""/>` : esc((b.name || 'ک').slice(0,1))}</div><div class="grow"><span class="business-card-kind">${b.kind === 'bale' ? icon('at',12)+' کانال یا گروه بله' : icon('building-2',12)+' کسب‌وکار مستقل'}</span><h3>${esc(b.name)}</h3><small>${esc(b.source_ref || 'شناسهٔ کسب‌وکار ثبت نشده')}</small></div>${ST.activeBusinessId===b.id?`<span class="business-current">${icon('check',13)} فعال</span>`:''}</div>
        <div class="business-card-metrics"><div><span>${icon('panels-top-left',14)} دستهٔ اصلی</span><strong>${fa((b.categories?.main || []).length)}</strong></div><div><span>${icon('image',14)} بنرهای مرتبط</span><strong>${fa(b.banner_count || 0)}</strong></div><div><span>${icon('shopping-bag',14)} سفارش‌ها</span><strong>${fa(b.order_count || 0)}</strong></div></div>
        ${(b.categories?.main || []).length?`<div class="business-tags">${(b.categories.main||[]).slice(0,4).map(cat=>`<span>${esc(cat)}</span>`).join('')}${(b.categories.main||[]).length>4?`<span>+${fa((b.categories.main||[]).length-4)}</span>`:''}</div>`:''}
        <div class="business-card-actions"><button class="btn btn-primary" data-business-select="${b.id}">${ST.activeBusinessId===b.id?'کسب‌وکار فعال':'انتخاب این کسب‌وکار'}</button><button class="btn btn-ghost" data-business-edit="${b.id}">${icon('sliders',14)} ویرایش</button><button class="icon-btn business-delete" data-business-delete="${b.id}" aria-label="حذف کسب‌وکار">${icon('trash',15)}</button></div>
      </article>`).join('') || `<div class="scenario-empty business-empty-state"><span>${icon('building-2',27)}</span><h3>فضای کاری‌ات را بساز</h3><p>برای هر کسب‌وکار، دسته‌بندی، بنر و سفارش مستقل نگه دار. می‌توانی کانال بله یا فروشگاه بیرون از بله اضافه کنی.</p><button class="btn btn-primary" id="btnEmptyBusinessCreate">${icon('plus',15)} افزودن کسب‌وکار</button></div>`;
    return `<section class="page-intro business-intro"><div class="page-intro-icon">${icon('building-2',25)}</div><div class="page-intro-copy"><span class="eyebrow">تفکیک فعالیت‌ها</span><h2>کسب‌وکارهای من</h2><p>برای هر کسب‌وکار دسته‌ها، بنرها و سفارش‌های مستقل داشته باش.</p></div><div class="banner-intro-count"><strong>${fa((ST.businesses||[]).length)}</strong><span>کسب‌وکار</span></div></section>
      <p class="hint page-note">ویرایش اطلاعات، سابقهٔ سفارش‌ها و بنرهای قبلی را پاک نمی‌کند.</p>
      <button class="btn btn-primary btn-block btn-new-banner" id="btnNewBusiness" style="margin-bottom:14px">${icon('plus',17)} افزودن کسب‌وکار جدید</button>
      ${ST.activeBusinessId ? `<div class="notice active-business-notice">${icon('check',16)} <span>کسب‌وکار فعال: <strong>${esc((ST.businesses.find(b=>b.id===ST.activeBusinessId)||{}).name || '')}</strong></span></div>` : ''}<div class="business-list">${rows}</div>`;
  }

  function renderBusinessForm(b = null) {
    const cats = (b?.categories?.main || []).join(', ');
    const subs = (b?.categories?.sub || []).join(', ');
    return `<div class="sheet-handle"></div>
      <section class="form-sheet-hero business-form-hero"><span class="form-sheet-icon">${icon('building-2',23)}</span><div><span class="eyebrow">فضای کاری مستقل</span><h3>${b?'ویرایش کسب‌وکار':'کسب‌وکار تازه'}</h3><p>اطلاعات هر فعالیت را جدا نگه دار.</p></div></section>
      <input type="hidden" id="businessId" value="${b?.id || ''}"/>
      <div class="form-section-label"><span>۱</span><div><b>اطلاعات پایه</b><small>نام و نوع فعالیت</small></div></div>
      <div class="field"><label>نوع کسب‌وکار</label><select id="businessKind"><option value="bale" ${b?.kind!=='external'?'selected':''}>کانال یا گروه بله</option><option value="external" ${b?.kind==='external'?'selected':''}>فروشگاه یا کسب‌وکار خارج از بله</option></select></div>
      <div class="field"><label>نام کسب‌وکار <em>الزامی</em></label><input id="businessName" maxlength="160" value="${esc(b?.name || '')}" placeholder="مثلاً فروشگاه گیاهان طبیعی"/></div>
      <div class="field"><label>لینک یا شناسهٔ کانال <span>برای بله</span></label><div class="input-leading-icon">${icon('link',16)}<input id="businessRef" value="${esc(b?.source_ref || '')}" placeholder="ble.ir/… یا @شناسه" dir="auto"/></div><p class="field-helper">اگر دریافت اطلاعات انجام نشود، می‌توانی نام و تصویر را دستی وارد کنی.</p></div>
      <div class="field"><label>نشانی تصویر پروفایل <span>اختیاری</span></label><div class="input-leading-icon">${icon('image',16)}<input id="businessAvatar" value="${esc(b?.avatar_url || '')}" placeholder="https://…" dir="ltr"/></div></div>
      <div class="form-section-label"><span>۲</span><div><b>دسته‌بندی فعالیت</b><small>برای تفکیک محتوای هر کسب‌وکار</small></div></div>
      <div class="field"><label>دسته‌های اصلی <em>الزامی</em></label><input id="businessCats" value="${esc(cats)}" placeholder="مثلاً پوشاک، سلامت، عطر"/><p class="field-helper">چند مورد را با ویرگول از هم جدا کن.</p></div>
      <div class="field"><label>زیردسته‌ها <span>اختیاری</span></label><input id="businessSubs" value="${esc(subs)}" placeholder="مثلاً عطر طبیعی، روغن گیاهی"/></div>
      <div class="form-preserve-note">${icon('shield-check',16)} ویرایش کسب‌وکار، سفارش‌ها و بنرهای قبلی را پاک نمی‌کند.</div>
      <button class="btn btn-primary btn-block form-submit-primary" id="btnSaveBusiness">${icon('check',16)} ${b?'ذخیرهٔ تغییرات':'ساخت کسب‌وکار'}</button>`;
  }

  function renderBannerForm() {
    const feePolicy = ST.bannerFeePolicy || {};
    const feeHint = feePolicy.first_free_available
      ? 'اولین بنر تأییدشده رایگان است؛ هزینهٔ بنرهای بعدی پس از تأیید محاسبه می‌شود.'
      : `هزینهٔ تأیید این بنر ${faNum(feePolicy.next_banner_fee_toman || 140000)} تومان است و فقط پس از تأیید پشتیبانی کسر می‌شود.`;
    const hasBusinesses = (ST.businesses || []).length > 0;
    return `<div class="sheet-handle"></div>
      <section class="form-sheet-hero banner-form-hero"><span class="form-sheet-icon">${icon('image',23)}</span><div><span class="eyebrow">کتابخانهٔ محتوای تبلیغاتی</span><h3>ثبت بنر جدید</h3><p>بنر را ثبت کن تا بلافاصله در فهرست بنرهایت باشد و برای سفارش قابل انتخاب شود.</p></div></section>
      <div class="banner-type-picker" id="bannerType"><button type="button" class="on" data-t="media"><span>${icon('image',17)}</span><b>تصویر یا ویدیو</b><small>محتوای بصری</small></button><button type="button" data-t="text"><span>${icon('file-text',17)}</span><b>بنر متنی</b><small>بدون فایل رسانه</small></button></div>
      <div id="mediaBlock"><div class="upload-zone upload-zone-modern" id="uploadZone"><span class="upload-zone-icon">${icon('upload-cloud',25)}</span><strong>فایل را انتخاب کن</strong><span>تصویر JPG/PNG یا ویدیوی MP4</span><small>حداکثر حجم ۱۵ مگابایت</small><input type="file" id="bannerFile" accept="image/*,video/*" hidden/></div><div id="fileName" class="file-save-status" aria-live="polite"></div></div>
      <div class="form-section-label"><span>۱</span><div><b>جزئیات بنر</b><small>عنوان و پیام تبلیغاتی</small></div></div>
      <div class="field"><label>کسب‌وکار مرتبط</label><select id="bannerBusiness"><option value="">${hasBusinesses?'انتخاب کسب‌وکار':'هنوز کسب‌وکاری ثبت نشده'}</option>${(ST.businesses||[]).map(b=>`<option value="${b.id}" ${ST.activeBusinessId===b.id?'selected':''}>${esc(b.name)}</option>`).join('')}</select>${!hasBusinesses?`<div class="inline-create-note">${icon('info',14)} پس از ثبت کسب‌وکار می‌توانی بنر را به آن متصل کنی.</div>`:''}</div>
      <div class="field"><label>عنوان <span>اختیاری</span></label><input id="bTitle" maxlength="120" placeholder="مثلاً تخفیف پاییزی فروشگاه"/></div>
      <div class="field"><label>متن بنر <em>الزامی</em></label><textarea id="bCaption" placeholder="محصول یا خدمتت را کوتاه و روشن معرفی کن…" rows="4"></textarea><small class="field-helper">حداقل ۱۲ کاراکتر؛ متن واضح به بررسی سریع‌تر کمک می‌کند.</small></div>
      <div class="banner-fee-note">${icon('shield-check',17)}<span>${esc(feeHint)}</span></div>
      <div class="form-submit-stack"><button class="btn btn-primary btn-block form-submit-primary" id="btnSubmitBanner">${icon('send',16)} ارسال برای بررسی</button><button class="btn btn-ghost btn-block" id="btnCancelBannerDraft">لغو ثبت بنر</button></div>`;
  }

  function renderCalendar() {
    const t = (ST.catalog?.tariffs || []).find(x => x.id === ST.tariffId);
    if (!t) return '<div class="scenario-empty"><span>!</span><h3>تعرفه‌ای انتخاب نشده</h3><p>برای دیدن تقویم، ابتدا یک تعرفه انتخاب کن.</p></div>';
    const now = new Date();
    const [jy,jm] = ST.calMonth || gregorianToJalali(now.getFullYear(),now.getMonth()+1,now.getDate()); ST.calMonth=[jy,jm];
    const dayMap={}; (ST.calDays||[]).forEach(x=>{dayMap[x.date]=x;});
    const busySet=new Set((ST.catalog?.busy||[]).filter(b=>b.tariff_id===t.id).map(b=>b.date));
    Object.keys(dayMap).forEach(iso=>{const st=dayMap[iso].status||(dayMap[iso].free?'free':'full');if(st!=='free'&&st!=='banner-hold')busySet.add(iso);});
    const firstG=jalaliToGregorian(jy,jm,1); const first=new Date(firstG[0],firstG[1]-1,firstG[2]); const startDow=(first.getDay()+1)%7; const dim=jm<=6?31:jm<=11?30:29;
    let cells=''; for(let i=0;i<startDow;i++) cells+='<div class="cal-day muted"></div>';
    for(let d=1;d<=dim;d++){const g=jalaliToGregorian(jy,jm,d);const iso=`${g[0]}-${String(g[1]).padStart(2,'0')}-${String(g[2]).padStart(2,'0')}`;const past=new Date(g[0],g[1]-1,g[2])<new Date(now.getFullYear(),now.getMonth(),now.getDate());const busy=busySet.has(iso);const sel=ST.selectedDay===iso;let cls='cal-day scenario-cal-day';if(past)cls+=' muted';else if(busy)cls+=' busy';if(sel)cls+=' sel';cells+=`<button type="button" class="${cls}" data-day="${iso}" ${past||busy?'disabled':''}>${fa(d)}${sel?'<i></i>':''}</button>`;}
    return `<section class="calendar-summary"><div class="calendar-summary-icon">${icon('calendar',22)}</div><div class="grow"><span class="eyebrow">تقویم انتشار</span><h2>${esc(t.owner||t.name)}</h2><p>${esc(t.name)} · ${fa(t.duration_hours)} ساعت نمایش</p></div><strong>${faNum(t.price)} <small>تومان</small></strong></section>
      <section class="calendar-card"><div class="calendar-topline"><div><span class="eyebrow">زمان مناسب خودت را پیدا کن</span><h3>روز انتشار</h3></div><div class="calendar-nav"><button class="icon-btn" id="calPrev" aria-label="ماه قبل">${icon('chevron-left',17)}</button><button class="icon-btn" id="calNext" aria-label="ماه بعد">${icon('chevron-left',17)}</button></div></div><div class="cal-head scenario-cal-head"><strong>${JMONTHS[jm-1]} ${fa(jy)}</strong></div><div class="cal-grid scenario-cal-grid">${['ش','ی','د','س','چ','پ','ج'].map(x=>`<div class="cal-dow">${x}</div>`).join('')}${cells}</div><div class="calendar-legend"><span><i class="legend-free"></i> آزاد</span><span><i class="legend-busy"></i> تکمیل ظرفیت</span><span><i class="legend-past"></i> گذشته</span></div></section>
      <section class="calendar-selection"><div class="calendar-selection-copy"><span>${icon('check',16)}</span><div><small>تاریخ انتخاب‌شده</small><strong>${ST.selectedDay?esc(ST.selectedDay):'هنوز روزی انتخاب نشده'}</strong></div></div><div class="calendar-selection-price"><small>مبلغ تعرفه</small><strong>${faNum(t.price)} <small>تومان</small></strong></div></section>
      <button class="btn btn-primary btn-block" id="btnAddCart" ${ST.selectedDay?'':'disabled'}>ادامه و انتخاب بنر ${icon('chevron-left',16)}</button><p class="calendar-security-note">${icon('shield-check',14)} تا پیش از ثبت نهایی می‌توانی جزئیات سفارش را بازبینی کنی.</p>`;
  }

  function orderStepIndex(status) {
    const i = TIMELINE.findIndex((s) => s.key === status);
    return i < 0 ? 0 : i;
  }

  function renderOrders() {
    // مدیر: لیست آیتم‌های سفارش از /api/orders
    if (ST.role === 'manager') {
      const list = ST.mgrOrders || [];
      const waiting = list.filter(it => ['pending','edited'].includes(it.manager_status));
      const publish = list.filter(it => it.manager_status === 'approved' && it.publish_due);
      const rows = list.length ? list.map((it,index) => `
        <article class="manager-history-card" style="--card-order:${Math.min(index,8)}">
          <div class="manager-history-top"><span class="manager-history-avatar">${icon('megaphone',18)}</span><div class="grow"><small>درخواست #${fa(it.id)}</small><h3>${esc(it.owner || 'جایگاه تبلیغاتی')}</h3><p>${esc(it.tariff_name || 'تعرفه')}${it.start_jalali || it.date ? ' · '+esc(it.start_jalali || it.date):''}</p></div><span class="badge ${it.manager_status==='pending'?'warn':it.manager_status==='rejected'?'danger':it.manager_status==='published'?'ok':'muted'}">${MGR_STATUS[it.manager_status] || it.manager_status || 'ثبت‌شده'}</span></div>
          <div class="manager-history-value"><span>سهم این انتشار</span><strong>${faNum(it.price)} <small>تومان</small></strong></div>
          ${it.proposed_date ? `<div class="manager-time-note">${icon('calendar',14)} زمان پیشنهادی: ${esc(it.proposed_date)}</div>`:''}
          ${it.published_link ? `<a href="${esc(it.published_link)}" target="_blank" rel="noopener" class="manager-published-link">مشاهدهٔ لینک انتشار ${icon('arrow-up-left',14)}</a>`:''}
          <div class="manager-history-actions">${it.manager_status==='pending' ? `<button class="btn btn-primary" data-mgr-approve="${it.id}">${icon('check',14)} تأیید</button><button class="btn btn-ghost" data-mgr-suggest="${it.id}">${icon('calendar',14)} پیشنهاد زمان</button><button class="btn btn-danger-icon" data-mgr-reject="${it.id}" aria-label="رد درخواست">${icon('close',15)}</button>`:''}${it.manager_status==='approved' && it.publish_due ? `<button class="btn btn-primary btn-block" data-mgr-published-disabled="${it.id}">${icon('check',14)} ثبت انتشار انجام‌شده</button>`:''}</div>
        </article>`).join('') : `<div class="scenario-empty"><span>${icon('inbox',27)}</span><h3>هنوز سفارشی ثبت نشده</h3><p>به‌محض ثبت سفارش برای کانال‌هایت، سابقه و وضعیت آن اینجا نمایش داده می‌شود.</p><button class="btn btn-soft" id="btnMgrOrdersGoHome">بازگشت به میزکار</button></div>`;
      return `<section class="orders-overview manager-orders-overview"><div><span class="eyebrow">سابقهٔ جایگاه‌ها</span><h2>سفارش‌های کانال</h2><p>از درخواست جدید تا اعلام انتشار، وضعیت هر جایگاه را دنبال کن.</p></div><div class="orders-overview-metrics"><div><strong>${fa(list.length)}</strong><span>همه</span></div><div><strong>${fa(waiting.length)}</strong><span>در انتظار</span></div><div><strong>${fa(publish.length)}</strong><span>آمادهٔ انتشار</span></div></div></section><div class="manager-content-heading"><div><span class="eyebrow">نمایش همهٔ موارد</span><h2>سابقهٔ درخواست‌ها</h2></div><button class="manager-refresh" id="btnRefreshOrders">${icon('refresh-cw',16)}</button></div>${rows}`;
    }
    let list = ST.orders || [];
    if (ST.orderTab === 'active') {
      list = list.filter((o) => !['completed','cancelled','rejected'].includes(o.status));
    } else if (ST.orderTab === 'done') {
      list = list.filter((o) => ['completed','cancelled','rejected'].includes(o.status));
    }
    const cards = list.length ? list.map((o) => {
      const step = orderStepIndex(o.status);
      const tl = TIMELINE.map((s, i) => {
        let cls = 'tl-step';
        if (i < step) cls += ' done';
        if (i === step) cls += ' on';
        return `<div class="${cls}"><div class="tl-dot"></div>${s.label}</div>`;
      }).join('');
      return `<div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong>سفارش ${fa(o.id || o.order_id || '')}</strong>
          <span class="badge">${STATUS_LABEL[o.status] || o.status}</span>
        </div>
        <div class="ch-sub" style="margin-top:4px">${esc(o.channel_name || o.title || '')}</div>
        ${o.banner_title ? `<div class="hint" style="margin-top:5px">بنر: ${esc(o.banner_title)}</div>` : ''}
        <div class="timeline">${tl}</div>
        <div class="price">${faNum(o.total || o.price || 0)} تومان</div>
        ${(o.items||[]).length ? `<div class="order-items" style="margin-top:10px"><div class="hint" style="font-weight:700;margin-bottom:6px">جزئیات سفارش</div>${(o.items||[]).map(it=>`
          <div class="order-item-row" style="padding:8px 0;border-top:1px solid var(--line)">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start"><strong>${esc(it.owner || 'کانال')}</strong><span class="badge">${esc(MGR_STATUS[it.manager_status] || STATUS_LABEL[it.execution_status] || it.manager_status || '')}</span></div>
            <div class="ch-sub">${esc(it.tariff_name || '')}${it.date ? ' · ' + esc(it.date) : ''}</div>
            <div class="hint">${faNum(it.price || 0)} تومان</div>
            ${it.published_link ? `<a href="${esc(it.published_link)}" target="_blank" rel="noopener noreferrer" class="hint">مشاهدهٔ انتشار</a>` : ''}
            ${it.proposed_date ? `<div class="hint" style="margin-top:6px">پیشنهاد زمان جدید: ${esc(it.proposed_date)}</div><div class="actions"><button class="btn btn-primary btn-sm" data-answer-item="${it.id}" data-accept="1">تأیید زمان</button><button class="btn btn-ghost btn-sm" data-answer-item="${it.id}" data-accept="0">رد پیشنهاد</button></div>` : ''}
          </div>`).join('')}</div>` : ''}
        ${o.pay_parts ? `<div class="hint" style="margin-top:8px">پرداخت مرحله‌ای: ${fa(o.pay_parts_paid || 0)} از ${fa(o.pay_parts)} بخش پرداخت شده</div>` : ''}
        ${o.payment_deadline ? `<div class="hint" style="margin-top:4px">مهلت پرداخت: ${esc(o.payment_deadline)}</div>` : ''}
        ${o.pay_hint ? `<div class="hint" style="margin-top:4px">${esc(o.pay_hint)}</div>` : ''}
        ${o.status === 'waiting_payment' || o.can_pay ? `<button class="btn btn-primary btn-block btn-sm" style="margin-top:10px" data-pay="${o.id||o.order_id}">پرداخت</button>` : ''}
        ${o.can_cancel ? `<button class="btn btn-danger btn-block btn-sm" style="margin-top:6px" data-cancel="${o.id}">لغو سفارش</button>` : ''}
      </div>`;
    }).join('') : '<div class="empty">سفارشی نیست.</div>';

    const activeCount = (ST.orders || []).filter((o) => !['completed','cancelled','rejected'].includes(o.status)).length;
    const doneCount = (ST.orders || []).filter((o) => ['completed','cancelled','rejected'].includes(o.status)).length;
    return `
      <section class="orders-overview">
        <div><span class="eyebrow">وضعیت سفارش‌ها</span><h2>پیگیری تبلیغات</h2><p>آخرین وضعیت رزروها و انتشارها را یک‌جا ببین.</p></div>
        <div class="orders-overview-metrics"><div><strong>${fa((ST.orders||[]).length)}</strong><span>همه</span></div><div><strong>${fa(activeCount)}</strong><span>جاری</span></div><div><strong>${fa(doneCount)}</strong><span>بسته‌شده</span></div></div>
      </section>
      <div class="tabs-line" id="orderTabs">
        <button class="${ST.orderTab==='all'?'on':''}" data-t="all">همه</button>
        <button class="${ST.orderTab==='active'?'on':''}" data-t="active">جاری</button>
        <button class="${ST.orderTab==='done'?'on':''}" data-t="done">تمام‌شده</button>
      </div>
      ${cards}
      <button class="btn btn-ghost btn-block btn-sm" id="btnRefreshOrders" style="margin-top:10px">بروزرسانی سفارش‌ها</button>`;
  }

  function renderWallet() {
    const response = ST.wallet || ST.me?.wallet || {};
    const w = response.balance || response;
    const banks = response.banks || [];
    const payouts = response.payouts || [];
    const ledger = response.ledger || [];
    const isAdvertiser = ST.role !== 'manager' && ST.role !== 'operator';
    const topupHtml = isAdvertiser ? '<div style="padding:8px 0"><button class="btn btn-primary btn-block" id="btnTopup">شارژ اعتبار (فاکتور بله)</button></div>' : '';
    const payoutAllowed = ST.role === 'manager' && response.can_payout !== false;
    const visibleBalance = isAdvertiser ? Number(w.credit || 0) : Number(w.available || 0);
    const balanceLabel = isAdvertiser ? 'اعتبار قابل استفاده برای سفارش (تومان)' : 'موجودی قابل برداشت (تومان)';
    const bankLabel = (b) => `${esc(b.holder_name || 'صاحب حساب')} ···${esc(b.iban_tail || (b.iban || '').slice(-4))}`;
    const ledgerLabels = { earn: 'درآمد انتشار', refund: 'بازگشت وجه', deposit: 'شارژ کیف پول با بله', penalty: 'جریمه', payout_lock: 'رزرو برداشت', payout_paid: 'برداشت پرداخت‌شده', payout_unlock: 'آزادسازی برداشت', spend: 'هزینه سفارش', escrow: 'وجه امانی', adjust: 'اصلاح موجودی' };
    const payoutLabels = { pending: 'در انتظار بررسی', paid: 'پرداخت‌شده', rejected: 'ردشده', cancelled: 'لغوشده' };
    return `
      <section class="wallet-hero"><div class="wallet-hero-head"><span>${isAdvertiser ? 'اعتبار قابل استفاده' : 'موجودی قابل برداشت'}</span><span class="wallet-hero-icon">${icon('wallet',22)}</span></div><div class="wallet-total">${faNum(visibleBalance)} <small>تومان</small></div>
      ${topupHtml}<div class="wallet-hero-foot"><span>${icon('shield-check',14)} موجودی حساب لینک‌بان</span><span>${isAdvertiser ? 'برای ثبت سفارش' : 'قابل تسویه طبق شرایط'}</span></div></section>
      <div class="wallet-secondary-stats"><div class="wallet-stat"><span class="wallet-stat-icon pending-icon">${icon('clock',19)}</span><div><small>در انتظار تسویه</small><strong>${faNum(w.locked_pending ?? w.pending)} <small>تومان</small></strong></div></div><div class="wallet-stat"><span class="wallet-stat-icon income-icon">${icon('trending-up',19)}</span><div><small>درآمد این ماه</small><strong>${faNum(response.report?.month_earn || 0)} <small>تومان</small></strong></div></div></div>
      <div class="wallet-quick-action"><div><strong>شارژ حساب</strong><span>فاکتور پرداخت را در بله دریافت کن.</span></div><button class="btn btn-primary" id="btnInvoice">${icon('plus',16)} افزایش موجودی</button></div>
      <div class="card wallet-paid-row"><div class="list-item"><div class="grow"><div class="title">مبلغ پرداخت‌شده</div><div class="sub">جمع برداشت‌های تسویه‌شده</div></div><b>${faNum(w.paid_out || 0)} تومان</b></div></div>
      ${ST.role === 'manager' ? '<div class="wallet-manager-actions"><button class="btn btn-ghost" id="btnAddBank">' + icon('landmark',16) + ' حساب بانکی</button><button class="btn btn-primary" id="btnPayout" ' + (payoutAllowed ? '' : 'disabled') + '>' + icon('arrow-up-left',16) + ' درخواست برداشت</button></div>' : ''}
      ${ST.role === 'manager' && !payoutAllowed && response.payout_block_reason ? `<p class="hint">${esc(response.payout_block_reason === 'minimum' ? `حداقل برداشت ${faNum(response.min_payout || 100000)} تومان است.` : 'در حال حاضر امکان ثبت درخواست برداشت وجود ندارد.')}</p>` : ''}
      <div class="section">حساب‌های بانکی</div>
      ${banks.length ? banks.map(b => `<div class="card list-item"><div class="grow"><div class="title">${bankLabel(b)}</div><div class="hint">${esc(b.iban || '')}</div></div>${b.is_default ? '<span class="badge">پیش‌فرض</span>' : ''}</div>`).join('') : '<div class="card hint">هنوز حساب بانکی ثبت نشده است.</div>'}
      <div class="section">درخواست‌های برداشت</div>
      ${payouts.length ? payouts.map(x => `<div class="card list-item"><div class="grow"><div class="title">درخواست #${fa(x.id)}</div><div class="hint">${esc(payoutLabels[x.status] || x.status)} · ${esc(x.iban_tail || '')}</div></div><b>${faNum(x.amount_toman)} تومان</b></div>`).join('') : '<div class="card hint">درخواستی ثبت نشده است.</div>'}
      <div class="section">گردش حساب</div>
      ${ledger.length ? ledger.map(x => `<div class="card list-item"><div class="grow"><div class="title">${esc(ledgerLabels[x.entry_type] || x.entry_type || 'تراکنش')}</div><div class="hint">${esc(x.note || x.ref || '')}</div></div><b>${Number(x.amount) > 0 ? '+' : ''}${faNum(x.amount)} تومان</b></div>`).join('') : '<div class="card hint">تراکنشی برای نمایش وجود ندارد.</div>'}
      <p class="hint" style="margin-top:12px">فاکتور شارژ از طریق گفت‌وگوی بله ارسال می‌شود. درخواست برداشت پس از ثبت پشتیبانی پردازش خواهد شد.</p>`;
  }

  function renderSettings() {
    const u = ST.me?.user || {};
    const pending = ST.me?.pending_orders || 0;
    const handle = displayName(ST.me);
    const identity = u.bale_user_id || '';
    const photo = userPhotoUrl(ST.me);
    const initials = userInitials(ST.me);
    const isOperator = ST.me?.is_operator || ST.me?.roles?.operator;
    const roleCard = (key, title, subtitle, glyph) => `
      <div class="role-card ${ST.role===key?'on':''}" data-r="${key}" role="button" tabindex="0" aria-pressed="${ST.role===key?'true':'false'}">
        <span class="role-card-icon">${icon(glyph,21)}</span>
        <span class="role-card-copy"><b>${title}</b><span>${subtitle}</span></span>
        <span class="role-card-status">${ST.role===key ? icon('check',15) : icon('chevron-left',16)}</span>
      </div>`;
    return `
      <section class="profile-hero">
        <div class="profile-hero-glow"></div>
        <div class="profile-identity">
          <div class="profile-avatar">${photo ? `<img src="${esc(photo)}" alt=""/>` : esc(initials)}</div>
          <div class="profile-copy"><span class="profile-overline">حساب لینک‌بان</span><h2>${esc(handle)}</h2><span class="profile-subline">${icon('shield-check',13)} ${(u.handle || u.username) ? ('@' + esc(String(u.handle || u.username).replace(/^@/,''))) : 'حساب کاربری شما'}</span></div>
          <span class="profile-member-badge">${icon('badge-check',17)}</span>
        </div>
        <div class="profile-meta"><span>شناسه کاربری</span><strong>${identity ? fa(identity) : '—'}</strong><button id="btnCopyUserId" type="button" aria-label="کپی شناسه" ${identity ? '' : 'disabled'}>${icon('copy',15)}</button></div>
      </section>
      <div class="section-heading profile-section-heading"><div><span class="eyebrow">فضای کاری شما</span><h2>نقش فعال</h2></div><span class="role-count">${isOperator ? '۳ نقش' : '۲ نقش'}</span></div>
      <p class="profile-intro">با انتخاب نقش، ابزارهای متناسب با فعالیتت در دسترس قرار می‌گیرد.</p>
      <div class="role-list">
        ${roleCard('advertiser','آگهی‌دهنده','خرید جایگاه و پیگیری سفارش‌ها','megaphone')}
        ${roleCard('manager','مدیر کانال','تعرفه‌ها، زمان‌بندی و انتشار' + (pending ? ' · ' + fa(pending) + ' درخواست باز' : ''),'panels-top-left')}
        ${isOperator ? roleCard('operator','پشتیبان','بررسی بنرها، سفارش‌ها و تسویه','headset') : ''}
      </div>
      <div class="section-heading settings-group-heading"><div><span class="eyebrow">مدیریت و راهنما</span><h2>دسترسی‌های سریع</h2></div></div>
      ${ST.role === 'advertiser' ? `<button class="setting-tile" id="btnBusinesses"><span class="setting-tile-icon business-icon">${icon('building-2',21)}</span><span class="setting-tile-copy"><strong>کسب‌وکارهای من</strong><small>مدیریت فعالیت‌ها و دسته‌بندی‌های مستقل</small></span><span class="setting-tile-arrow">${icon('chevron-left',18)}</span></button><button class="setting-tile" id="btnSettingsBanners"><span class="setting-tile-icon business-icon">${icon('image',21)}</span><span class="setting-tile-copy"><strong>کتابخانهٔ بنرها</strong><small>ثبت بنر و پیگیری نتیجهٔ بررسی</small></span><span class="setting-tile-arrow">${icon('chevron-left',18)}</span></button>` : ST.role === 'manager' ? `<button class="setting-tile" id="btnSettingsChannels"><span class="setting-tile-icon business-icon">${icon('building-2',21)}</span><span class="setting-tile-copy"><strong>کانال‌های من</strong><small>آمار، ظرفیت و روش انتشار</small></span><span class="setting-tile-arrow">${icon('chevron-left',18)}</span></button><button class="setting-tile" id="btnSettingsTariffs"><span class="setting-tile-icon theme-icon">${icon('sliders',21)}</span><span class="setting-tile-copy"><strong>مدیریت تعرفه‌ها</strong><small>قیمت و بازهٔ انتشار</small></span><span class="setting-tile-arrow">${icon('chevron-left',18)}</span></button>` : `<button class="setting-tile" id="btnSettingsQueues"><span class="setting-tile-icon business-icon">${icon('inbox',21)}</span><span class="setting-tile-copy"><strong>صف‌های بررسی</strong><small>بنرها، تسویه‌ها و تخصیص مدیران</small></span><span class="setting-tile-arrow">${icon('chevron-left',18)}</span></button>`}
      <button class="setting-tile" id="btnHelp"><span class="setting-tile-icon support-icon">${icon('messages-square',21)}</span><span class="setting-tile-copy"><strong>راهنما و پشتیبانی</strong><small>سؤالات متداول و راه ارتباطی</small></span><span class="setting-tile-arrow">${icon('chevron-left',18)}</span></button>
      <div class="section-heading settings-group-heading"><div><span class="eyebrow">شخصی‌سازی</span><h2>ظاهر برنامه</h2></div></div>
      <div class="setting-tile theme-tile"><span class="setting-tile-icon theme-icon">${icon(document.documentElement.dataset.theme === 'dark' ? 'sun' : 'moon',21)}</span><span class="setting-tile-copy"><strong>حالت ${document.documentElement.dataset.theme === 'dark' ? 'روشن' : 'تیره'}</strong><small>انتخاب ظاهر دلخواه برنامه</small></span><button class="theme-switch ${document.documentElement.dataset.theme === 'dark' ? 'on' : ''}" id="btnTheme2" type="button" aria-label="تغییر حالت"><span></span></button></div>
      <div class="profile-footer">لینک‌بان <span>•</span> بازار تبلیغات در بله</div>`;
  }

  function renderHelp() {
    return `<section class="support-hero"><div class="support-hero-art"><div class="support-orbit"></div><span>${icon('headset',32)}</span><i>?</i></div><div class="support-hero-copy"><span class="eyebrow">همراهت هستیم</span><h2>چه کمکی از دست ما برمی‌آید؟</h2><p>پاسخ پرسش‌های متداول را پیدا کن یا از تیم پشتیبانی کمک بگیر.</p></div></section>
      <div class="support-contact-grid"><button id="btnSupportTicket" class="support-contact-card"><span class="support-contact-icon ticket-icon">${icon('ticket',21)}</span><b>ثبت تیکت جدید</b><small>شرح مشکل و پیگیری</small><span class="support-contact-arrow">${icon('chevron-left',16)}</span></button><button id="btnSupportFaq" class="support-contact-card"><span class="support-contact-icon faq-icon">${icon('book-open',21)}</span><b>سؤالات متداول</b><small>راهنمای سفارش و حساب</small><span class="support-contact-arrow">${icon('chevron-left',16)}</span></button><button id="btnSupportBot" class="support-contact-card"><span class="support-contact-icon chat-icon">${icon('messages-square',21)}</span><b>گفت‌وگو با پشتیبانی</b><small>ارتباط مستقیم در بله</small><span class="support-contact-arrow">${icon('chevron-left',16)}</span></button></div>
      <div class="home-section-head support-section-title"><div><span class="eyebrow">راهنمای سریع</span><h2>موضوعت را انتخاب کن</h2></div></div>
      <div class="support-faq-list" id="supportFaqList">
        <details class="support-faq" open><summary><span class="support-faq-num">۰۱</span><span>چطور سفارش تبلیغ ثبت کنم؟</span><i>${icon('chevron-left',16)}</i></summary><p>از بازار یک کانال انتخاب کن، تعرفه را ببین، روز آزاد را انتخاب کن و بنر تأییدشدهٔ مربوط به کسب‌وکارت را به سفارش وصل کن. پیش از نهایی‌کردن، خلاصه و مبلغ سفارش نمایش داده می‌شود.</p></details>
        <details class="support-faq"><summary><span class="support-faq-num">۰۲</span><span>مدیر کانال زمان دیگری پیشنهاد داده؛ چه کنم؟</span><i>${icon('chevron-left',16)}</i></summary><p>در جزئیات سفارش، تاریخ پیشنهادی را بررسی کن. می‌توانی آن را تأیید یا رد کنی؛ زمان تازه فقط بعد از پاسخ تو وارد مرحلهٔ بعد می‌شود.</p></details>
        <details class="support-faq"><summary><span class="support-faq-num">۰۳</span><span>چطور برای چند کسب‌وکار بنر ثبت کنم؟</span><i>${icon('chevron-left',16)}</i></summary><p>در پروفایل وارد «کسب‌وکارهای من» شو و برای هر فعالیت یک کسب‌وکار جدا تعریف کن. هنگام ثبت بنر، کسب‌وکار مربوط را انتخاب کن تا بنر به همان مورد متصل بماند.</p></details>
        <details class="support-faq"><summary><span class="support-faq-num">۰۴</span><span>چرا اعتبار از کیف پول کم شده؟</span><i>${icon('chevron-left',16)}</i></summary><p>هزینه و وضعیت هر سفارش را در جزئیات سفارش و گردش کیف پول بررسی کن. اگر مغایرتی دیدی، شناسهٔ کاربری و شمارهٔ سفارش را برای پشتیبانی بفرست.</p></details>
        <details class="support-faq"><summary><span class="support-faq-num">۰۵</span><span>اطلاعات کانال دریافت نشده است</span><i>${icon('chevron-left',16)}</i></summary><p>لینک یا شناسه را بررسی کن و یک‌بار دیگر تلاش کن. اگر دریافت خودکار ممکن نبود، می‌توانی نام و تصویر را دستی ثبت کنی و بعداً اطلاعات را اصلاح کنی.</p></details>
      </div>
      <section class="support-bottom-card"><span class="support-bottom-icon">${icon('messages-square',21)}</span><div><b>جوابت را پیدا نکردی؟</b><p>تیم پشتیبانی را همراه با شناسه یا شماره سفارش در جریان بگذار.</p><button id="btnSupportBotBottom">شروع گفت‌وگو ${icon('chevron-left',14)}</button></div></section>`;
  }

  const MGR_STATUS = {
    pending: 'در انتظار تأیید',
    approved: 'تأییدشده',
    rejected: 'رد شده',
    edited: 'در انتظار تأیید مشتری',
    cart: 'سبد',
    published: 'منتشر شده',
  };

  function renderMgrHome() {
    const all = ST.mgrOrders || [];
    const inbox = all.filter(o => o.inbox && o.manager_status === 'pending');
    const waitingCustomer = all.filter(o => o.manager_status === 'edited' && o.proposed_date);
    const chs = ST.myChannels || [];
    const tariffs = ST.mgrTariffs || [];
    const publishing = all.filter(o => o.manager_status === 'approved' && o.publish_due);
    const label = displayName(ST.me);
    return `
      <section class="manager-inbox-hero">
        <div class="manager-inbox-glow"></div>
        <div class="manager-inbox-copy"><span class="manager-eyebrow">میزکار مدیر کانال</span><h2>سلام ${esc(label)} <span>👋</span></h2><p>درخواست‌ها را بررسی کن و زمان انتشار را هماهنگ نگه دار.</p><div class="manager-hero-micro"><span><i></i> حساب مدیر فعال</span><span>${icon('shield-check',13)} جایگاه‌های تو</span></div></div>
        <div class="manager-inbox-illustration"><div class="manager-inbox-ring"></div><span>${icon('inbox',32)}</span><b>${fa(inbox.length)}</b></div>
      </section>
      <section class="manager-compact-stats">
        <div class="manager-compact-stat stat-requests"><span>${icon('inbox',17)}</span><div><small>درخواست جدید</small><strong>${fa(inbox.length)}</strong></div><i>${inbox.length?'نیازمند بررسی':'به‌روز'}</i></div>
        <div class="manager-compact-stat stat-channels"><span>${icon('building-2',17)}</span><div><small>کانال‌های من</small><strong>${fa(chs.length)}</strong></div><i>تحت مدیریت</i></div>
        <div class="manager-compact-stat stat-rates"><span>${icon('sliders',17)}</span><div><small>تعرفه‌های فعال</small><strong>${fa(tariffs.filter(t=>t.is_active).length)}</strong></div><i>در بازار</i></div>
      </section>
      <div class="manager-content-heading manager-page-heading"><div><span class="eyebrow">صف پاسخ‌گویی</span><h2>درخواست‌های تبلیغاتی</h2><p>برای هر سفارش، زمان و سهم جایگاه را بررسی کن.</p></div><div class="manager-heading-actions"><button class="manager-history-link" id="btnMgrHistory">${icon('file-text',15)} سابقه</button><button class="manager-refresh" id="btnMgrRefresh" aria-label="به‌روزرسانی">${icon('refresh-cw',16)}</button></div></div>
      <div class="manager-panel" id="mgrPanelContent">${renderMgrInbox(inbox)}</div>
      ${waitingCustomer.length ? `<section class="manager-followup-section"><div class="manager-content-heading"><div><span class="eyebrow">پیگیری زمان</span><h2>منتظر پاسخ آگهی‌دهنده</h2><p>زمان جایگزین پیشنهاد شده و فعلاً به اقدام تازه‌ای از طرف تو نیاز ندارد.</p></div><span class="followup-count">${fa(waitingCustomer.length)}</span></div>${renderMgrWaitingCustomer(waitingCustomer)}</section>` : ''}
      ${publishing.length?`<section class="manager-publish-reminder"><span>${icon('check-circle',18)}</span><div><b>${fa(publishing.length)} سفارش آمادهٔ اعلام انتشار</b><small>پس از انجام تبلیغ، وضعیت آن را ثبت کن.</small></div><button id="btnMgrShowPublish">مشاهده</button></section>`:''}
      <div class="manager-footer-note">${icon('shield-check',15)} <span>زمان جایگزین پس از تأیید مشتری قطعی می‌شود.</span></div>`;
  }

  function renderMgrChannelsPage() {
    const channels = ST.myChannels || [];
    const active = channels.filter(c => c.is_listed !== false).length;
    return `<section class="manager-screen-hero channels-screen-hero"><div class="manager-screen-art">${icon('building-2',27)}<i></i></div><div class="manager-screen-copy"><span class="manager-eyebrow">فضای انتشار شما</span><h2>کانال‌های من</h2><p>اطلاعات، آمار و روش انتشار هر جایگاه را مدیریت کن.</p><div class="manager-screen-badges"><span>${fa(channels.length)} کانال ثبت‌شده</span><span>${fa(active)} فعال در بازار</span></div></div></section>
      <div class="manager-screen-toolbar"><div><span class="eyebrow">جایگاه‌های متصل</span><h3>همهٔ کانال‌ها</h3></div><button class="manager-refresh" id="btnMgrRefreshChannelsTop" aria-label="تازه‌سازی">${icon('refresh-cw',16)}</button></div>
      <div class="manager-panel">${renderMgrChannels()}</div>
      <div class="manager-connect-bottom"><span>${icon('link',18)}</span><div><b>کانال جدیدی داری؟</b><small>بازوی لینک‌بان را به کانال اضافه کن و دسترسی مدیر را تأیید کن.</small></div><button id="btnMgrConnectChannelsBottom">راهنما</button></div>`;
  }

  function renderMgrTariffsPage() {
    const rows = ST.mgrTariffs || [];
    const active = rows.filter(t=>t.is_active).length;
    const priceMin = rows.length ? Math.min(...rows.map(t=>Number(t.price)||0)) : 0;
    return `<section class="manager-screen-hero tariffs-screen-hero"><div class="manager-screen-art">${icon('sliders',27)}<i></i></div><div class="manager-screen-copy"><span class="manager-eyebrow">قیمت‌گذاری شفاف</span><h2>تعرفه و زمان‌بندی</h2><p>قیمت و مدت جایگاه‌ها را برای هر کانال جداگانه تعریف کن.</p><div class="manager-screen-badges"><span>${fa(active)} تعرفه فعال</span><span>${rows.length?`شروع از ${faNum(priceMin)} تومان`:'هنوز قیمتی ثبت نشده'}</span></div></div></section>
      <div class="manager-tariff-metrics"><div><small>همهٔ تعرفه‌ها</small><strong>${fa(rows.length)}</strong><span>در مجموعه</span></div><div><small>فعال در بازار</small><strong>${fa(active)}</strong><span>قابل سفارش</span></div><div><small>غیرفعال</small><strong>${fa(rows.length-active)}</strong><span>در حالت توقف</span></div></div>
      <div class="manager-screen-toolbar"><div><span class="eyebrow">مدیریت جایگاه</span><h3>فهرست تعرفه‌ها</h3></div><button class="manager-refresh" id="btnRefreshTariffsTop" aria-label="تازه‌سازی">${icon('refresh-cw',16)}</button></div>
      <div class="manager-panel">${renderMgrTariffs()}</div>`;
  }

  function renderMgrWaitingCustomer(rows) {
    return `<div class="manager-followup-list">${rows.map(it=>`<article class="manager-followup-card"><span class="manager-followup-icon">${icon('calendar-clock',18)}</span><div class="manager-followup-copy"><b>${esc(it.owner || 'جایگاه تبلیغاتی')}</b><span>${esc(it.tariff_name || 'تعرفه')} · سفارش #${fa(it.id)}</span><small>${it.proposed_date ? `زمان پیشنهادی: ${esc(it.proposed_date)}` : 'منتظر پاسخ آگهی‌دهنده'}</small></div><span class="badge muted">منتظر مشتری</span></article>`).join('')}</div>`;
  }

  function renderMgrInbox(inbox) {
    if (!inbox.length) {
      return `<div class="manager-empty-state"><div class="manager-empty-art"><div class="empty-orbit"></div><span>${icon('inbox',31)}</span><i></i><b></b></div><span class="manager-empty-label">صندوق درخواست‌ها</span><h3>فعلاً درخواستی در صف نیست</h3><p>وقتی سفارش جدیدی برای یکی از کانال‌هایت ثبت شود، اینجا می‌توانی زمان را تأیید کنی، زمان دیگری پیشنهاد بدهی یا درخواست را رد کنی.</p><div class="manager-empty-actions"><button class="btn btn-primary" id="btnMgrRefreshEmpty">بررسی دوباره</button><button class="btn btn-ghost" id="btnMgrToChannels">مشاهدهٔ کانال‌ها</button></div></div>`;
    }
    return `<div class="manager-request-list">${inbox.map((it, index) => `
      <article class="manager-request-card" style="--card-order:${Math.min(index,8)}">
        <div class="manager-request-top"><div class="manager-request-brand">${icon('megaphone',19)}</div><div class="manager-request-title"><span class="manager-request-label">درخواست تبلیغاتی · #${fa(it.id)}</span><h3>${esc(it.owner || 'جایگاه تبلیغاتی')}</h3><p>${esc(it.tariff_name || 'تعرفه انتخابی')} · ${esc(it.start_jalali || it.date || 'زمان ثبت‌شده')}</p></div><span class="badge ${it.manager_status==='pending'?'warn':'muted'}">${MGR_STATUS[it.manager_status] || it.manager_status}</span></div>
        <div class="manager-request-details"><div><small>مبلغ سهم کانال</small><strong>${faNum(it.price)} <small>تومان</small></strong></div><div><small>وضعیت زمان</small><strong>${it.proposed_date ? 'زمان جایگزین پیشنهاد شده' : 'در انتظار پاسخ'}</strong></div></div>
        ${it.proposed_date ? `<div class="manager-time-note">${icon('calendar',15)} زمان پیشنهادی فعلی: ${esc(it.proposed_date)}</div>` : ''}
        <div class="manager-request-actions">
          ${it.manager_status === 'pending' ? `<button class="btn btn-primary" data-mgr-approve="${it.id}">${icon('check',15)} تأیید درخواست</button><button class="btn btn-ghost" data-mgr-suggest="${it.id}">${icon('calendar',15)} پیشنهاد زمان</button><button class="btn btn-danger-icon" data-mgr-reject="${it.id}" aria-label="رد درخواست">${icon('close',17)}</button>` : ''}
          ${it.manager_status === 'approved' && it.publish_due ? `<button class="btn btn-primary btn-block" data-mgr-published-disabled="${it.id}">${icon('check',15)} اعلام انتشار</button>` : ''}
        </div>
      </article>`).join('')}</div>`;
  }

  function renderMgrChannels() {
    const chs = ST.myChannels || [];
    if (!chs.length) return `<div class="manager-empty-state"><div class="manager-empty-art channel-empty-art"><div class="empty-orbit"></div><span>${icon('building-2',31)}</span><i></i><b></b></div><span class="manager-empty-label">شبکهٔ کانال‌ها</span><h3>هنوز کانالی به میزکارت وصل نشده</h3><p>کانالی را که مدیریت می‌کنی از بازوی لینک‌بان معرفی کن. پس از اتصال، آمار، تعرفه‌ها و روزهای آزادش را از همین قسمت مدیریت می‌کنی.</p><div class="manager-empty-actions"><button class="btn btn-primary" id="btnMgrConnectChannels">اتصال کانال در بله</button><button class="btn btn-ghost" id="btnMgrRefreshChannelsEmpty">بررسی دوباره</button></div><div class="manager-connect-hint">${icon('shield-check',15)} اتصال مدیر و دسترسی ربات باید در کانال تأیید شده باشد.</div></div>`;
    return `<div class="manager-channel-list">${chs.map((c,index) => {
      const letter = esc((c.name || 'ک').slice(0,1));
      const ava = c.avatar_url || c.photo_url ? `<img src="${esc(c.avatar_url || c.photo_url)}" alt="" onerror="this.parentNode.textContent='${letter}'"/>` : letter;
      return `<article class="manager-channel-card" style="--card-order:${Math.min(index,8)}">
        <div class="manager-channel-cover"><div class="manager-channel-cover-ornament"></div><div class="manager-channel-avatar">${ava}</div><span class="manager-channel-state ${c.is_listed===false?'paused':''}"><i></i>${c.is_listed===false?'آرشیوشده':'در بازار'}</span><span class="manager-channel-cover-symbol">${icon('megaphone',25)}</span></div>
        <div class="manager-channel-body"><div class="manager-channel-name-row"><div><h3>${esc(c.name)}</h3><p>${c.link ? '@' + esc(String(c.link).replace(/^@/,'')) : 'شناسهٔ کانال ثبت نشده'}</p></div><span class="manager-method-badge">${esc(modeLabel(c.publish_mode))}</span></div>
          <div class="manager-channel-metrics"><div><span>${icon('users',15)} اعضا</span><strong>${faK(c.members_count)}</strong></div><div><span>${icon('chart',15)} میانگین بازدید</span><strong>${faK(c.avg_views)}</strong></div><div><span>${icon('wallet',15)} تعرفه‌ها</span><strong>${fa(c.tariff_count || 0)}</strong></div></div>
          <div class="manager-channel-actions"><button class="btn btn-primary" data-mgr-ch="${c.id}">مدیریت کانال ${icon('chevron-left',15)}</button><button class="btn btn-ghost" data-mgr-mode="${c.id}">${icon('sliders',15)} روش انتشار</button></div>
        </div>
      </article>`;
    }).join('')}</div><button class="btn btn-soft btn-block manager-list-refresh" id="btnMgrRefreshChannelsList">${icon('refresh-cw',15)} به‌روزرسانی آمار کانال‌ها</button>`;
  }

  function renderMgrTariffs() {
    const rows = (ST.mgrTariffs || []).map((t,index) => `<article class="manager-tariff-card" style="--card-order:${Math.min(index,8)}"><div class="manager-tariff-top"><span class="manager-tariff-symbol">${icon('wallet',20)}</span><span class="badge ${t.is_active?'ok':'muted'}"><i class="tiny-status-dot"></i>${t.is_active?'فعال در بازار':'غیرفعال'}</span></div><div class="manager-tariff-name">${esc(t.name || (t.duration_hours + ' ساعته'))}</div><div class="manager-tariff-channel">${icon('building-2',13)} ${esc(t.owner || 'کانال')} <span>·</span> شروع ${fa(t.start_hour ?? 0)}:۰۰</div><div class="manager-tariff-price">${faNum(t.price)} <small>تومان</small><span>/ ${fa(t.duration_hours || 24)} ساعت</span></div><div class="manager-tariff-divider"></div><div class="manager-tariff-actions"><button class="btn btn-soft" data-tariff-edit="${t.id}">${icon('sliders',15)} ویرایش</button><button class="btn btn-ghost" data-tariff-toggle="${t.id}" data-active="${t.is_active?'1':'0'}">${t.is_active?'توقف نمایش':'فعال‌سازی'}</button><button class="icon-btn manager-delete-tariff" data-tariff-delete="${t.id}" aria-label="حذف تعرفه">${icon('trash-2',16)}</button></div></article>`).join('');
    return `<div class="manager-tariff-toolbar"><span>${fa((ST.mgrTariffs||[]).length)} تعرفه ثبت‌شده</span><button class="btn btn-primary" id="btnAddTariff">${icon('plus',15)} تعرفهٔ جدید</button></div>${rows ? `<div class="manager-tariff-list">${rows}</div>` : `<div class="manager-empty-state compact-empty"><div class="manager-empty-art"><div class="empty-orbit"></div><span>${icon('wallet',29)}</span></div><h3>هنوز تعرفه‌ای نساخته‌ای</h3><p>برای نمایش جایگاه کانال در بازار، اولین تعرفه‌ات را تعریف کن.</p><button class="btn btn-primary" id="btnAddTariff">${icon('plus',15)} ساخت اولین تعرفه</button></div>`}<button class="btn btn-ghost btn-block manager-list-refresh" id="btnRefreshTariffs">${icon('refresh-cw',15)} تازه‌سازی تعرفه‌ها</button><p class="manager-footnote">${icon('shield-check',14)} تعرفه‌های متصل به سفارش‌های قبلی، برای حفظ سابقه غیرفعال می‌شوند.</p>`;
  }

  function renderMgrChannelDetail() {
    const c = (ST.myChannels || []).find(x => x.id === ST.selectedMgrChannel);
    if (!c) return '<div class="empty">کانال پیدا نشد</div>';
    const letter = esc((c.name||'ک').slice(0,1));
    const ava = c.avatar_url || c.photo_url ? `<img src="${esc(c.avatar_url || c.photo_url)}" alt="" onerror="this.parentNode.textContent='${letter}'"/>` : letter;
    return `<section class="manager-detail-hero"><div class="manager-detail-cover"><div class="manager-channel-cover-ornament"></div><span class="manager-detail-icon">${ava}</span><span class="manager-detail-status ${c.is_listed===false?'paused':''}"><i></i>${c.is_listed===false?'آرشیو':'فعال در بازار'}</span></div><div class="manager-detail-copy"><span class="eyebrow">کانال تحت مدیریت</span><h2>${esc(c.name)}</h2><p>${c.link ? '@'+esc(String(c.link).replace(/^@/,'')) : 'شناسهٔ کانال ثبت نشده'}</p></div><div class="manager-channel-metrics detail-metrics"><div><span>${icon('users',15)} اعضا</span><strong>${faK(c.members_count)}</strong></div><div><span>${icon('chart',15)} بازدید</span><strong>${faK(c.avg_views)}</strong></div><div><span>${icon('wallet',15)} تعرفه</span><strong>${fa(c.tariff_count||0)}</strong></div></div></section>
      <div class="manager-content-heading"><div><span class="eyebrow">تنظیمات جایگاه</span><h2>مدیریت کانال</h2></div></div>
      <div class="manager-detail-action-list"><button class="manager-detail-action" id="btnAddTariffForCh"><span class="manager-detail-action-icon tariff-icon">${icon('plus',19)}</span><span><b>افزودن تعرفه</b><small>ایجاد بستهٔ جدید برای این کانال</small></span><span>${icon('chevron-left',17)}</span></button><button class="manager-detail-action" data-mgr-mode="${c.id}"><span class="manager-detail-action-icon channel-icon">${icon('sliders',19)}</span><span><b>روش انتشار</b><small>${esc(modeLabel(c.publish_mode))}</small></span><span>${icon('chevron-left',17)}</span></button><button class="manager-detail-action" id="btnManageAvailability"><span class="manager-detail-action-icon request-icon">${icon('calendar',19)}</span><span><b>تقویم و روزهای آزاد</b><small>مدیریت ظرفیت روزانهٔ انتشار</small></span><span>${icon('chevron-left',17)}</span></button><button class="manager-detail-action" id="btnRefreshOne"><span class="manager-detail-action-icon business-icon">${icon('refresh-cw',19)}</span><span><b>به‌روزرسانی آمار</b><small>دریافت دوبارهٔ مشخصات کانال</small></span><span>${icon('chevron-left',17)}</span></button></div><p class="manager-footnote">${icon('shield-check',14)} تغییرات تعرفه و تقویم روی زمان‌های قابل رزرو در بازار اثر می‌گذارند.</p>`;
  }

  function renderOpHome() {
    const banners = ST.opBanners || [];
    const payouts = ST.opPayouts || [];
    const assigns = ST.opAssignments || [];
    return `<section class="operator-hero"><div class="operator-hero-art"><div class="operator-orbit"></div><span>${icon('headset',31)}</span></div><div class="operator-hero-copy"><span class="manager-eyebrow">میز پشتیبانی</span><h2>مرکز عملیات لینک‌بان</h2><p>صف‌های بررسی را اولویت‌بندی کن و وضعیت هر درخواست را روشن نگه دار.</p><span class="operator-security">${icon('shield-check',14)} دسترسی پشتیبان</span></div></section>
      <div class="operator-queue-grid"><button data-op-shortcut="banners" class="operator-queue-card ${ST.opTab==='banners'?'on':''}"><span class="operator-queue-icon banner-queue">${icon('image',19)}</span><small>بررسی بنر</small><strong>${fa(banners.length)}</strong><span>مورد در صف</span></button><button data-op-shortcut="payouts" class="operator-queue-card ${ST.opTab==='payouts'?'on':''}"><span class="operator-queue-icon payout-queue">${icon('wallet',19)}</span><small>تسویه‌ها</small><strong>${fa(payouts.length)}</strong><span>درخواست پرداخت</span></button><button data-op-shortcut="assign" class="operator-queue-card ${ST.opTab==='assign'?'on':''}"><span class="operator-queue-icon manager-queue">${icon('building-2',19)}</span><small>اتصال مدیران</small><strong>${fa(assigns.length)}</strong><span>تخصیص ثبت‌شده</span></button></div>
      <div class="operator-content-heading"><div><span class="eyebrow">صف کاری</span><h2>${ST.opTab==='banners'?'بررسی و تأیید بنرها':ST.opTab==='payouts'?'درخواست‌های برداشت':'مدیریت اتصال کانال‌ها'}</h2></div><button class="manager-refresh" id="btnOpRefresh" aria-label="به‌روزرسانی">${icon('refresh-cw',16)}</button></div>
      <div class="seg operator-tabs" id="opTabs"><button class="${ST.opTab==='banners'?'on':''}" data-t="banners">بنرها ${banners.length?`<em>${fa(banners.length)}</em>`:''}</button><button class="${ST.opTab==='payouts'?'on':''}" data-t="payouts">تسویه‌ها ${payouts.length?`<em>${fa(payouts.length)}</em>`:''}</button><button class="${ST.opTab==='assign'?'on':''}" data-t="assign">مدیران</button><button class="${ST.opTab==='tickets'?'on':''}" data-t="tickets">تیکت‌ها</button><button class="${ST.opTab==='settings'?'on':''}" data-t="settings">تنظیمات</button></div>
      <div class="operator-panel">${ST.opTab === 'banners' ? renderOpBanners(banners) : ST.opTab === 'payouts' ? renderOpPayouts(payouts) : ST.opTab === 'tickets' ? renderOpTickets() : ST.opTab === 'settings' ? renderOpSettings() : renderOpAssignments(assigns)}</div>`;
  }

  function renderOpSettings() {
    const s = ST.opSettings || {};
    const row = (key, label, hint, type) => {
      type = type || 'number';
      return `<div class="field"><label>${label}</label>
        <input type="${type}" data-setting="${key}" value="${esc(s[key] ?? '')}" ${type==='number'?'inputmode="numeric"':''} dir="${type==='text'?'ltr':'rtl'}"/>
        <small class="field-help">${hint}</small></div>`;
    };
    return `<div class="operator-settings">
      <section class="form-sheet-hero"><div><span class="eyebrow">پیکربندی سامانه</span><h3>اعداد و حساب‌ها</h3>
        <p>مهلت پرداخت، کارمزد، شارژ و مشخصات کارت‌به‌کارت.</p></div></section>
      ${row('payment_hold_hours', 'مهلت پرداخت (ساعت)', 'بعد از قبول مدیر تا پرداخت')}
      ${row('banner_fee_toman', 'هزینه بنر بعدی (تومان)', '۰ = رایگان')}
      ${row('service_fee_toman', 'کارمزد سفارش (تومان)', '۰ = رایگان')}
      ${row('publish_retry_minutes', 'حداکثر تلاش انتشار (دقیقه)', 'پیش‌فرض ۳۰')}
      ${row('publish_retry_interval_sec', 'فاصله تلاش انتشار (ثانیه)', 'پیش‌فرض ۶۰')}
      ${row('min_topup_toman', 'حداقل شارژ (تومان)', '')}
      ${row('max_topup_toman', 'سقف شارژ (تومان)', '')}
      <h3 style="margin:16px 0 8px">کارت‌به‌کارت</h3>
      ${row('card_holder', 'نام صاحب حساب', '', 'text')}
      ${row('card_number', 'شماره کارت', '', 'text')}
      ${row('card_iban', 'شبا', '', 'text')}
      ${row('card_bank_name', 'نام بانک', '', 'text')}
      ${row('card_note', 'توضیح برای مشتری', '', 'text')}
      <button class="btn btn-primary btn-block" id="btnSaveOpSettings">ذخیره تنظیمات</button>
    </div>`;
  }

function renderOpTickets() {
    const rows = ST.opTickets || [];
    if (!rows.length) {
      return `<div class="operator-empty"><h3>تیکتی نیست</h3><p>تیکت‌های مشتریان اینجا می‌آید.</p></div>`;
    }
    return `<div class="op-ticket-list">${rows.map((t) => `
      <article class="business-workspace-card">
        <div class="grow"><span class="badge muted">${esc(t.status||'')}</span>
          <h3>${esc(t.subject||('تیکت '+t.id))}</h3>
          <small>${esc(t.category||'')} · #${fa(t.id)}</small>
        </div>
        <button type="button" class="btn btn-soft" data-op-ticket-open="${t.id}">پاسخ</button>
      </article>`).join('')}</div>`;
  }

  function renderOpBanners(rows) {
    if (!rows.length) return `<div class="operator-empty"><span class="operator-empty-icon">${icon('image',27)}</span><h3>صف بنر خالی است</h3><p>بنرها بدون تأیید پشتیبان ثبت می‌شوند؛ این صف برای موارد خاص/اختلاف است.</p><button class="btn btn-soft" id="btnOpRefreshEmpty">${icon('refresh-cw',15)} تازه‌سازی صف</button></div>`;
    return `<div class="operator-banner-list">${rows.map((r,index)=>`<article class="operator-banner-card" style="--card-order:${Math.min(index,8)}"><div class="operator-banner-top"><span class="operator-request-id">درخواست #${fa(r.id)}</span><span class="badge warn">در انتظار بررسی</span></div><div class="operator-banner-content"><div class="operator-banner-preview">${r.media_url?`<img src="${esc(r.media_url)}" alt=""/>`:icon('image',25)}</div><div class="operator-banner-info"><h3>${esc(r.title || 'بنر تبلیغاتی')}</h3><p>${esc(r.customer || 'مشتری لینک‌بان')}</p><small>${esc(r.business_name || 'کسب‌وکار مشخص نشده')}</small></div></div><p class="operator-banner-caption">${esc(r.caption || 'برای این بنر توضیحی ثبت نشده است.')}</p>${r.fee_toman?`<div class="operator-fee-row"><span>هزینه پس از تأیید</span><strong>${faNum(r.fee_toman)} تومان</strong></div>`:''}<div class="operator-banner-actions"><button class="btn btn-primary" data-op-approve="${r.id}">${icon('check',15)} تأیید و انتشار</button><button class="btn btn-ghost operator-reject" data-op-reject="${r.id}">${icon('close',15)} رد درخواست</button></div></article>`).join('')}</div><button class="btn btn-ghost btn-block manager-list-refresh" id="btnOpRefreshEmpty">${icon('refresh-cw',15)} تازه‌سازی صف</button>`;
  }

  function renderOpAssignments(rows) {
    return `<section class="operator-assign-intro"><span>${icon('building-2',22)}</span><div><b>اتصال مدیر به کانال</b><p>کانال‌ها را به مدیر مسئول وصل کن تا درخواست‌های تبلیغاتی در صندوق درست نمایش داده شوند.</p></div></section>
      <div class="operator-assign-form card"><div class="operator-form-title"><span>تخصیص جدید</span><small>مرحلهٔ ۱ از ۱</small></div><div class="field"><label>شناسه یا نام کاربری مدیر</label><div class="operator-input-wrap">${icon('user-round',16)}<input id="opManagerRef" placeholder="مثلاً @username" autocomplete="off" /></div></div><div class="field"><label>لینک یا شناسهٔ کانال‌ها</label><div class="operator-input-wrap textarea-wrap">${icon('link',16)}<textarea id="opChannelRefs" rows="3" placeholder="@channel1، ble.ir/channel2"></textarea></div><small class="operator-field-help">برای اتصال چند کانال، شناسه‌ها را با ویرگول یا خط جدید جدا کن.</small></div><button class="btn btn-primary btn-block" id="btnAssignManager">${icon('link',16)} ثبت تخصیص کانال‌ها</button></div>
      <div class="operator-content-heading"><div><span class="eyebrow">میزان دسترسی</span><h2>تخصیص‌های فعلی</h2></div><span class="market-total">${fa(rows.length)} مورد</span></div>
      ${rows.length ? `<div class="operator-assignment-list">${rows.map(r=>`<article class="operator-assignment-card"><span class="operator-assignment-avatar">${esc((r.name||'ک').slice(0,1))}</span><div class="grow"><h3>${esc(r.name||'کانال')}</h3><p>${esc(r.link||'')}</p><small>مدیر: ${esc(r.manager_label||'تعیین نشده')}</small><div class="operator-assignment-status"><span class="badge ${r.pending?'warn':r.is_listed===false?'muted':'ok'}">${r.pending?'در انتظار اتصال مدیر':r.is_listed===false?'آرشیو':'فعال'}</span></div></div><button class="icon-btn danger-icon-btn" data-op-unassign="${r.id}" aria-label="لغو تخصیص">${icon('close',16)}</button></article>`).join('')}</div>` : `<div class="operator-empty compact-operator-empty"><span class="operator-empty-icon">${icon('users',25)}</span><h3>تخصیصی ثبت نشده</h3><p>پس از ثبت فرم بالا، کانال‌های متصل در اینجا دیده می‌شوند.</p></div>`}
      <button class="btn btn-ghost btn-block manager-list-refresh" id="btnOpRefreshList">${icon('refresh-cw',15)} تازه‌سازی اطلاعات</button>`;
  }

  function renderOpPayouts(rows) {
    if (!rows.length) return `<div class="operator-empty"><span class="operator-empty-icon payout-empty-icon">${icon('wallet',27)}</span><h3>درخواست تسویه‌ای وجود ندارد</h3><p>درخواست‌های برداشت مدیران پس از ثبت، برای بررسی اینجا قرار می‌گیرند.</p><button class="btn btn-soft" id="btnOpRefreshEmpty">${icon('refresh-cw',15)} تازه‌سازی صف</button></div>`;
    return `<div class="operator-payout-summary"><span>${icon('wallet',18)} مجموع درخواست‌های در صف</span><strong>${faNum(rows.reduce((s,p)=>s+Number(p.amount_toman||0),0))} <small>تومان</small></strong></div><div class="operator-payout-list">${rows.map(p=>`<article class="operator-payout-card"><div class="operator-payout-top"><span class="manager-request-brand">${icon('landmark',18)}</span><div><b>${esc(p.holder_name || 'صاحب حساب')}</b><small>درخواست #${fa(p.id)} · ${esc(p.status || 'در انتظار بررسی')}</small></div><strong>${faNum(p.amount_toman)} <small>تومان</small></strong></div><div class="operator-iban">شماره شبا <b dir="ltr">${esc(p.iban || '')}</b></div><div class="operator-payout-foot"><span class="badge warn">در انتظار پرداخت</span><span>${esc(p.iban_tail ? '•••• '+p.iban_tail : '')}</span></div></article>`).join('')}</div><button class="btn btn-primary btn-block operator-batch-button" id="btnOpBatch">${icon('file-text',16)} آماده‌سازی فایل واریز دسته‌ای</button><button class="btn btn-ghost btn-block manager-list-refresh" id="btnOpRefreshList">${icon('refresh-cw',15)} به‌روزرسانی</button>`;
  }

  const TITLES = {
    onboard: 'خوش آمدید',
    home: 'خانه',
    market: 'بازار تبلیغات',
    channel: 'جزئیات کانال',
    calendar: 'انتخاب روز',
    banners: 'بنرهای من',
    orders: 'سفارش‌های من',
    wallet: 'کیف پول',
    settings: 'حساب و نقش',
    businesses: 'کسب‌وکارهای من',
    help: 'راهنما و پشتیبانی',
    'mgr-home': 'درخواست‌های تبلیغاتی',
    'mgr-channels': 'کانال‌های من',
    'mgr-tariffs': 'تعرفه و زمان‌بندی',
    'mgr-channel': 'مدیریت کانال',
    'op-home': 'پنل پشتیبانی',
  };

  function navItems() {
    if (ST.role === 'manager') {
      return [
        { id: 'mgr-home', label: 'درخواست‌ها', icon: 'inbox' },
        { id: 'mgr-channels', label: 'کانال‌ها', icon: 'building-2' },
        { id: 'mgr-tariffs', label: 'تعرفه‌ها', icon: 'wallet' },
        { id: 'wallet', label: 'درآمد', icon: 'chart' },
        { id: 'settings', label: 'حساب', icon: 'user' },
      ];
    }
    if (ST.role === 'operator') {
      return [
        { id: 'op-home', label: 'صف‌ها', icon: 'orders' },
        { id: 'settings', label: 'حساب', icon: 'user' },
      ];
    }
    // آگهی‌دهنده؛ چینش همسو با نمونهٔ رابط کاربری ارسالی
    return [
      { id: 'home', label: 'خانه', icon: 'home' },
      { id: 'orders', label: 'سفارش‌ها', icon: 'orders' },
      { id: 'wallet', label: 'کیف پول', icon: 'wallet' },
      { id: 'settings', label: 'پروفایل', icon: 'user' },
    ];
  }

  function renderNav() {
    const items = navItems();
    $('#bottomNav').innerHTML = items.map((it) =>
      `<button type="button" class="${ST.page===it.id?'on':''}" data-nav="${it.id}">${icon(it.icon)}${it.label}</button>`
    ).join('');
  }

  function render() {
    const root = $('#pageContent');
    const back = !['home','market','orders','banners','wallet','settings','businesses','help','mgr-home','mgr-channels','mgr-tariffs','op-home'].includes(ST.page);
    $('#pageTitle').textContent = TITLES[ST.page] || 'لینک‌بان';
    $('#btnBack').style.display = back ? '' : 'none';
    $('#headerEl').classList.add('brand');
    $('#headerEl').classList.toggle('manager-head', ST.role === 'manager');
    $('#headerEl').classList.toggle('operator-head', ST.role === 'operator');

    let html = '';
    if (ST.loading) html = '<div class="loading">در حال بارگذاری…</div>';
    else if (ST.page === 'onboard') { try { html = renderOnboardPage(); } catch (e) { console.error(e); html = '<div class="empty"><strong>خطا در ویزارد</strong><p>'+esc(String(e.message||e))+'</p></div>'; } }
    else if (ST.page === 'home') { try { html = renderHome(); } catch (e) { console.error(e); html = '<div class="empty"><strong>خطا در خانه</strong><p>'+esc(String(e.message||e))+'</p></div>'; } }
    else if (ST.page === 'market') { try { html = renderMarket(); } catch (e) { console.error(e); html = '<div class="empty"><strong>خطا در بازار</strong><p>'+esc(String(e.message||e))+'</p></div>'; } }
    else if (ST.page === 'channel') html = renderChannel();
    else if (ST.page === 'calendar') html = renderCalendar();
    else if (ST.page === 'banners') html = renderBanners();
    else if (ST.page === 'orders') html = renderOrders();
    else if (ST.page === 'wallet') html = renderWallet();
    else if (ST.page === 'settings') html = renderSettings();
    else if (ST.page === 'businesses') html = renderBusinesses();
    else if (ST.page === 'help') html = renderHelp();
    else if (ST.page === 'mgr-home') html = renderMgrHome();
    else if (ST.page === 'mgr-channels') html = renderMgrChannelsPage();
    else if (ST.page === 'mgr-tariffs') html = renderMgrTariffsPage();
    else if (ST.page === 'mgr-channel') html = renderMgrChannelDetail();
    else if (ST.page === 'op-home') html = renderOpHome();
    else html = ST.role === 'manager' ? renderMgrHome() : ST.role === 'operator' ? renderOpHome() : renderMarket();

    try {
      root.innerHTML = html || '<div class="empty"><strong>محتوا بارگذاری نشد</strong><p>یک‌بار دیگر تلاش کنید.</p><button class="btn btn-primary" id="btnReloadPage">تلاش دوباره</button></div>';
    } catch (err) {
      console.error('render', err);
      root.innerHTML = '<div class="empty"><strong>خطا در نمایش</strong><p>' + String((err && err.message) || err) + '</p><button class="btn btn-primary" id="btnReloadPage">تلاش دوباره</button></div>';
    }
    const rel = document.getElementById('btnReloadPage');
    if (rel) rel.onclick = () => location.reload();
    try {
      const nav = document.getElementById('bottomNav');
      if (nav) nav.style.display = (ST.page === 'onboard') ? 'none' : '';
    } catch (e) {}
    try { paintHeaderProfile(); } catch (e) {}
    renderNav();
    bindPage();
  }

  function navigate(page) {
    ST.page = page;
    render();
    window.scrollTo(0, 0);
  }

  async function ensureCatalog() {
    if (!ST.catalog) {
      ST.loading = true; render();
      try { await loadCatalog(); } catch (e) { toast(e.message || 'خطا در کاتالوگ'); }
      ST.loading = false;
    }
  }

  async function saveBusinessManually(body, existingId, saveButton) {
    if (saveButton) saveButton.disabled = true;
    const d = existingId
      ? await api(`/businesses/${Number(existingId)}/update`, { method: 'POST', body })
      : await api('/businesses', { method: 'POST', body });
    if (saveButton) saveButton.disabled = false;
    if (!d.ok) return toast(d.message || d.error || 'ذخیره انجام نشد');
    if (d.business && !existingId) {
      ST.activeBusinessId = d.business.id;
      try { localStorage.setItem('lb.activeBusinessId', String(ST.activeBusinessId)); } catch (e) {}
      // Metadata fetched before creation has no business id to attach a downloaded photo to.
      // Once saved, refresh once with the new id so the server can store a public avatar URL.
      if (d.business.kind === 'bale' && body.info_source === 'auto') {
        try { await api('/businesses/metadata', { method: 'POST', body: { business_id: Number(d.business.id), force: true }, timeoutMs: 15000 }); } catch (e) { /* Keep the successful name and allow manual photo fallback. */ }
      }
    }
    closeSheet(); await loadBusinesses(); render(); toast('کسب‌وکار ذخیره شد');
  }

  function bindBusinessForm() {
    const kind = $('#businessKind');
    const id = $('#businessId');
    const save = $('#btnSaveBusiness');
    if (!save) return;
    save.onclick = async () => {
      const name = $('#businessName').value.trim();
      const categories = {
        main: $('#businessCats').value.split(/[,،]/).map(x => x.trim()).filter(Boolean),
        sub: $('#businessSubs').value.split(/[,،]/).map(x => x.trim()).filter(Boolean),
      };
      if (!name) return toast('نام کسب‌وکار را وارد کنید');
      if (!categories.main.length) return toast('حداقل یک دسته‌بندی اصلی وارد کنید');
      const sourceRef = $('#businessRef').value.trim();
      const body = { name, kind: kind.value, source_ref: sourceRef, avatar_url: $('#businessAvatar').value.trim(), categories };
      save.disabled = true;
      // Try automatic channel metadata first, but never let a failed lookup prevent manual registration.
      if (kind.value === 'bale' && sourceRef) {
        let meta;
        try { meta = await api('/businesses/metadata', { method: 'POST', timeoutMs: 15000, body: { source_ref: sourceRef, ...(id.value ? { business_id: Number(id.value) } : {}) } }); }
        catch (e) { meta = { ok: false, error: 'metadata_unavailable', message: e.message }; }
        if (!meta.ok || meta.error === 'metadata_unavailable') {
          save.disabled = false;
          openSheet(`<div class="sheet-handle"></div><h3>دریافت اطلاعات کانال ناموفق بود</h3><p class="hint">متأسفانه اطلاعات کانال دریافت نشد. ممکن است لینک یا شناسه را اشتباه وارد کرده باشید، یا دریافت اطلاعات موقتاً با مشکل مواجه شده باشد. آیا مطمئن هستید لینک یا شناسه را درست وارد کرده‌اید؟</p><button class="btn btn-primary btn-block" id="btnMetaRetry">بله، مطمئنم</button><button class="btn btn-ghost btn-block" id="btnMetaEdit" style="margin-top:8px">اصلاح لینک</button><button class="btn btn-ghost btn-block" id="btnMetaManual" style="margin-top:8px">ادامه با اطلاعات دستی</button>`);
          $('#btnMetaEdit').onclick = () => { closeSheet(); $('#businessRef')?.focus(); };
          $('#btnMetaManual').onclick = async () => { body.metadata_attempted = true; closeSheet(); await saveBusinessManually(body, id.value, save); };
          $('#btnMetaRetry').onclick = async () => {
            const retryBtn = $('#btnMetaRetry'); retryBtn.disabled = true; retryBtn.textContent = 'در حال تلاش مجدد…';
            let retry;
            try { retry = await api('/businesses/metadata', { method: 'POST', timeoutMs: 10000, body: { source_ref: sourceRef, force: true, ...(id.value ? { business_id: Number(id.value) } : {}) } }); }
            catch (e) { retry = { ok: false, error: 'metadata_unavailable', message: e.message }; }
            if (retry.ok && retry.metadata) {
              body.name = retry.metadata.name || body.name;
              body.avatar_url = retry.metadata.avatar_url || body.avatar_url;
              body.source_ref = retry.metadata.source_ref || sourceRef;
              body.info_source = 'auto';
            } else if (retry.ok && retry.business) {
              body.name = retry.business.name || body.name;
              body.avatar_url = retry.business.avatar_url || body.avatar_url;
              body.source_ref = retry.business.source_ref || sourceRef;
              body.info_source = retry.business.info_source || 'auto';
            } else {
              body.metadata_attempted = true;
            }
            closeSheet(); await saveBusinessManually(body, id.value, save);
          };
          return;
        }
        if (meta.metadata) { body.name = meta.metadata.name || body.name; body.avatar_url = meta.metadata.avatar_url || body.avatar_url; body.info_source = 'auto'; }
        if (meta.business) { body.name = meta.business.name || body.name; body.avatar_url = meta.business.avatar_url || body.avatar_url; }
      }
      await saveBusinessManually(body, id.value, save);
    };
  }

  function bindPage() {
    if (ST.page === 'onboard') { bindOnboardPage(); return; }
    $$('#homeFilters .chip').forEach((b) => b.onclick = () => {
      ST.filter = b.dataset.f; render();
    });
    const qi = $('#qInput');
    if (qi) {
      qi.onkeydown = async (e) => {
        if (e.key === 'Enter') {
          ST.q = qi.value.trim();
          ST.loading = true; render();
          try { await loadCatalog(); } catch (err) { toast(err.message); }
          ST.loading = false; render();
        }
      };
    }
    $$('[data-open-ch]').forEach((el) => el.onclick = () => {
      ST.channelId = el.dataset.openCh;
      ST.tariffId = null;
      navigate('channel');
    });
    $$('[data-tariff]').forEach((el) => el.onclick = () => {
      ST.tariffId = Number(el.dataset.tariff);
      render();
    });
    const backMarket = $('#btnBackMarket'); if (backMarket) backMarket.onclick = () => navigate('market');
    const pick = $('#btnPickTariff');
    if (pick) pick.onclick = async () => {
      if (!ST.tariffId) return;
      ST.loading = true; render();
      try {
        ST.calDays = await loadCalendarDays(ST.tariffId);
      } catch (e) { ST.calDays = []; }
      ST.loading = false;
      navigate('calendar');
    };

    $$('[data-day]').forEach((el) => el.onclick = () => {
      ST.selectedDay = el.dataset.day;
      render();
    });
    const prev = $('#calPrev');
    const next = $('#calNext');
    if (prev) prev.onclick = () => {
      let [y, m] = ST.calMonth;
      m--; if (m < 1) { m = 12; y--; }
      ST.calMonth = [y, m]; render();
    };
    if (next) next.onclick = () => {
      let [y, m] = ST.calMonth;
      m++; if (m > 12) { m = 1; y++; }
      ST.calMonth = [y, m]; render();
    };
    const addCart = $('#btnAddCart');
    if (addCart) addCart.onclick = () => addToCart();

    const nb = $('#btnNewBanner');
    if (nb) nb.onclick = () => {
      if (getBannerDraft()) {
        if (!confirm('یک پیش‌نویس ثبت بنر وجود دارد. ادامه و بازیابی همان پیش‌نویس؟')) return;
      }
      openSheet(renderBannerForm());
      bindBannerForm();
    };

    $$('#orderTabs button').forEach((b) => b.onclick = () => {
      ST.orderTab = b.dataset.t; render();
    });
    $$('[data-pay]').forEach((b) => b.onclick = () => payOrder(b.dataset.pay));
    $$('[data-answer-item]').forEach((b) => b.onclick = async () => {
      const d = await api('/orders/answer', {
        method: 'POST',
        body: { item_id: Number(b.dataset.answerItem), accept: b.dataset.accept === '1' },
      });
      toast(d.message || (d.ok ? 'ثبت شد' : (d.error || 'خطا')));
      await loadOrders(); render();
    });
    $$('[data-cancel]').forEach((b) => b.onclick = async () => {
      const d = await api('/orders/cancel', { method: 'POST', body: { order_id: Number(b.dataset.cancel) } });
      toast(d.message || (d.ok ? 'لغو شد' : (d.error || 'خطا')));
      await loadOrders(); render();
    });

    ['#btnHomeMarket','#btnHomeMarketAll','#btnHomeMarketEmpty'].forEach(sel => {
      const b = $(sel); if (b) b.onclick = async () => { try { if (!ST.catalog) await loadCatalog(); } catch(e) { toast(e.message || 'بازار بارگذاری نشد'); } navigate('market'); };
    });
    const openNewBanner = async () => {
      try { await Promise.allSettled([loadBusinesses(), loadBanners()]); } catch(e) {}
      if (!(ST.businesses || []).length) {
        ST.forceBusinessSetup = true;
        navigate('businesses');
        toast('اول یک کسب‌وکار بساز، بعد بنر را ثبت کن.');
        return;
      }
      // مسیر اصلی: بازو بنر را می‌گیرد و ثبت فوری می‌کند
      await requestNewBanner();
    };
    const homeBannerCreate = $('#btnHomeBanner'); if (homeBannerCreate) homeBannerCreate.onclick = openNewBanner;
    const topupBtn = $('#btnTopup');
    if (topupBtn) topupBtn.onclick = async () => {
      let minA = 10000, maxA = 1000000;
      try { const info = await api('/pay/info'); if (info.ok) { minA = info.min_topup_toman || minA; maxA = info.max_topup_toman || maxA; } } catch (e) {}
      openSheet(`<div class="sheet-handle"></div><h3 style="text-align:center">شارژ اعتبار</h3>` +
        `<div class="field"><label>مبلغ (تومان)</label><input id="topupAmount" type="number" value="${minA}" /></div>` +
        `<p class="hint">حداقل ${faNum(minA)} — حداکثر ${faNum(maxA)}</p>` +
        `<button class="btn btn-primary btn-block" id="btnDoTopup">ارسال فاکتور به بازو</button>`);
      const go = $('#btnDoTopup');
      if (go) go.onclick = async () => {
        const amount = Number(($('#topupAmount') || {}).value) || 0;
        const d = await api('/topup', { method: 'POST', body: { amount } });
        toast(d.message || (d.ok ? 'فاکتور ارسال شد' : 'خطا'));
        if (d.ok) { closeSheet(); try { const w = window.Bale && Bale.WebApp; if (w && w.close) setTimeout(() => w.close(), 400); } catch (e) {} }
      };
    };


    const saveOp = $('#btnSaveOpSettings');
    if (saveOp) saveOp.onclick = async () => {
      const patch = {};
      document.querySelectorAll('[data-setting]').forEach((el) => {
        patch[el.getAttribute('data-setting')] = el.value;
      });
      try {
        const d = await api('/operator/settings', { method: 'POST', body: { settings: patch } });
        if (!d.ok) throw new Error(d.message || 'settings');
        ST.opSettings = d.settings || patch;
        toast('تنظیمات ذخیره شد');
      } catch (e) { toast(e.message || 'ذخیره تنظیمات ناموفق'); }
    };

    const homeBannerList = $('#btnHomeManageBanners'); if (homeBannerList) homeBannerList.onclick = async () => { try { await loadBanners(); } catch(e) {} navigate('banners'); };
    ['#btnHomeOrders','#btnHomeWaiting','#btnHomeActive','#btnHomeDone'].forEach(sel => {
      const b = $(sel); if (b) b.onclick = async () => {
        try { await loadOrders(); } catch(e) {}
        ST.orderTab = (b.id === 'btnHomeWaiting' || b.id === 'btnHomeActive') ? 'active' : b.id === 'btnHomeDone' ? 'done' : 'all';
        navigate('orders');
      };
    });
    const goHomeWallet = async (topup) => {
      try { await loadWallet(); } catch(e) {}
      navigate('wallet');
      if (topup) { const invoice = $('#btnInvoice'); if (invoice) invoice.click(); }
    };
    const homeWalletBtn = $('#btnHomeWallet'); if (homeWalletBtn) homeWalletBtn.onclick = () => goHomeWallet(false);
    const homeTopupBtn = $('#btnHomeTopup'); if (homeTopupBtn) homeTopupBtn.onclick = () => goHomeWallet(true);

    const copyUserId = $('#btnCopyUserId');
    if (copyUserId) copyUserId.onclick = async () => {
      const id = String(ST.me?.user?.bale_user_id || '');
      if (!id) return;
      try { await navigator.clipboard.writeText(id); toast('شناسه کپی شد'); }
      catch (e) { toast('امکان کپی خودکار نیست؛ شناسه را نگه دارید و کپی کنید'); }
    };
    $$('[data-r][role="button"]').forEach((el) => el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); }
    }));

    const businessesBtn = $('#btnBusinesses');
    if (businessesBtn) businessesBtn.onclick = async () => {
      ST.loading = true; render();
      try { await loadBusinesses({ refreshMetadata: true }); } catch (e) { toast(e.message || 'خطا در دریافت کسب‌وکارها'); }
      ST.loading = false; navigate('businesses');
    };
    const helpBtn = $('#btnHelp');
    if (helpBtn) helpBtn.onclick = () => navigate('help');
    const supportTicket = $('#btnSupportTicket');
    if (supportTicket) supportTicket.onclick = () => {
      openSheet(`<div class="sheet-handle"></div><section class="form-sheet-hero ticket-form-hero"><span class="form-sheet-icon">${icon('ticket',22)}</span><div><span class="eyebrow">مرکز پشتیبانی</span><h3>ثبت تیکت جدید</h3><p>موضوع را انتخاب کن و مشکل را واضح توضیح بده.</p></div></section><div class="field"><label>موضوع تیکت</label><select id="demoTicketTopic"><option value="order">سفارش و زمان انتشار</option><option value="wallet">کیف پول و پرداخت</option><option value="banner">ثبت یا بررسی بنر</option><option value="business">کسب‌وکار و اطلاعات کانال</option><option value="other">موضوع دیگر</option></select></div><div class="field"><label>شماره سفارش <span>اختیاری</span></label><input id="demoTicketOrder" inputmode="numeric" placeholder="مثلاً ۱۲۳۴"/></div><div class="field"><label>شرح درخواست</label><textarea id="demoTicketMessage" rows="4" placeholder="چه اتفاقی افتاده و چه کمکی نیاز داری؟"></textarea></div><div class="prototype-note">${icon('info',15)} پیام شما برای پشتیبان ثبت می‌شود و پاسخ در همین بخش می‌آید.</div><button class="btn btn-primary btn-block form-submit-primary" id="btnSubmitTicket">${icon('send',16)} ثبت در نمونهٔ رابط</button>`);
      $('#btnSubmitDemoTicket').onclick = () => {
        const message = $('#demoTicketMessage').value.trim();
        if (message.length < 8) return toast('شرح درخواست را کامل‌تر بنویس.');
        const ticket = { id: Date.now(), topic: $('#demoTicketTopic').value, order: $('#demoTicketOrder').value.trim(), message, time: new Date().toLocaleString('fa-IR') };
        ST.demoTickets.unshift(ticket); closeSheet();
        toast('تیکت نمایشی ثبت شد؛ ارسال سروری هنوز متصل نیست.');
      };
    };
    const supportBot = $('#btnSupportBot');
    if (supportBot) supportBot.onclick = () => {
      const w = window.Bale && window.Bale.WebApp;
      if (w && typeof w.openLink === 'function') w.openLink('https://ble.ir/linkban');
      else window.open('https://ble.ir/linkban', '_blank');
    };
    const openSupportConversation = () => { const w=window.Bale&&window.Bale.WebApp; if(w&&typeof w.openLink==='function') w.openLink('https://ble.ir/linkban'); else window.open('https://ble.ir/linkban','_blank'); };
    const supportBotBottom = $('#btnSupportBotBottom'); if (supportBotBottom) supportBotBottom.onclick = openSupportConversation;
    const supportFaq = $('#btnSupportFaq'); if (supportFaq) supportFaq.onclick = () => { const faq=$('#supportFaqList'); if(faq) { faq.scrollIntoView({behavior:'smooth',block:'start'}); const first=faq.querySelector('details'); if(first) first.open=true; } };
    const settingBanners = $('#btnSettingsBanners'); if (settingBanners) settingBanners.onclick = async () => { try { await loadBanners(); } catch(e) {} navigate('banners'); };
    const settingChannels = $('#btnSettingsChannels'); if (settingChannels) settingChannels.onclick = async () => { ST.mgrTab='channels'; try { await loadMyChannels(); } catch(e) {} navigate('mgr-channels'); };
    const settingTariffs = $('#btnSettingsTariffs'); if (settingTariffs) settingTariffs.onclick = async () => { ST.mgrTab='tariffs'; try { await loadMgrTariffs(); } catch(e) {} navigate('mgr-tariffs'); };
    const settingQueues = $('#btnSettingsQueues'); if (settingQueues) settingQueues.onclick = async () => { try { await Promise.allSettled([loadOpBanners(),loadOpPayouts(),loadOpAssignments()]); } catch(e) {} navigate('op-home'); };

    const emptyBannerCreate = $('#btnEmptyBannerCreate'); if (emptyBannerCreate) emptyBannerCreate.onclick = openNewBanner;
    document.querySelectorAll('[data-set-active-banner]').forEach((btn) => {
      btn.onclick = async () => {
        const id = Number(btn.getAttribute('data-set-active-banner'));
        const d = await api('/banners/set-active', { method: 'POST', body: { banner_id: id, business_id: ST.selectedBusinessId || 0 } });
        toast(d.ok ? 'بنر فعال شد' : (d.message || 'خطا'));
        if (d.ok) { ST.activeBannerId = id; await loadBanners(); render(); }
      };
    });

    document.querySelectorAll('[data-op-ticket-open]').forEach((b) => {
      b.onclick = async () => {
        const id = Number(b.getAttribute('data-op-ticket-open'));
        const d = await api('/tickets/' + id);
        if (!d.ok) { toast(d.message || 'تیکت پیدا نشد'); return; }
        const t = d.ticket || {};
        const msgs = (t.messages || []).map((m) =>
          `<div class="hint"><b>${m.is_staff ? 'پشتیبان' : 'مشتری'}:</b> ${esc(m.body)}</div>`
        ).join('') || '<p class="hint">پیامی نیست</p>';
        openSheet(`<div class="sheet-handle"></div><h3>${esc(t.subject||'')}</h3>${msgs}
          <div class="field"><label>پاسخ</label><textarea id="opTicketReply" rows="3"></textarea></div>
          <button class="btn btn-primary btn-block" id="btnOpTicketReply">ارسال پاسخ</button>
          <button class="btn btn-soft btn-block" id="btnOpTicketClose" style="margin-top:8px">بستن تیکت</button>`);
        const send = $('#btnOpTicketReply');
        if (send) send.onclick = async () => {
          const body = ($('#opTicketReply').value || '').trim();
          if (!body) { toast('متن پاسخ خالی است'); return; }
          const r = await api('/tickets/' + id, { method: 'POST', body: { message: body } });
          toast(r.ok ? 'پاسخ ثبت شد' : (r.message || 'خطا'));
          if (r.ok) { closeSheet(); await loadOpTickets(); render(); }
        };
        const cls = $('#btnOpTicketClose');
        if (cls) cls.onclick = async () => {
          await api('/tickets/' + id + '/close', { method: 'POST', body: {} });
          closeSheet(); await loadOpTickets(); render();
        };
      };
    });


    const submitTicket = $('#btnSubmitTicket');
    if (submitTicket) submitTicket.onclick = async () => {
      const topic = ($('#demoTicketTopic') || {}).value || 'other';
      const orderRef = ($('#demoTicketOrder') || {}).value || '';
      const message = (($('#demoTicketMessage') || {}).value || '').trim();
      if (message.length < 5) { toast('متن تیکت را کامل‌تر بنویسید'); return; }
      const body = {
        category: topic,
        subject: ST.pendingTicket?.subject || '',
        message,
        order_id: orderRef || ST.pendingTicket?.order_id || null,
      };
      const d = await api('/tickets', { method: 'POST', body });
      if (!d.ok) { toast(d.message || d.error || 'ثبت تیکت ناموفق'); return; }
      ST.pendingTicket = null;
      toast('تیکت ثبت شد');
      closeSheet();
      try {
        const list = await api('/tickets');
        if (list.ok) ST.tickets = list.tickets || [];
      } catch (e) {}
      render();
    };

    const emptyBusinessCreate = $('#btnEmptyBusinessCreate'); if (emptyBusinessCreate) emptyBusinessCreate.onclick = () => { openSheet(renderBusinessForm()); bindBusinessForm(); };
    const newBusiness = $('#btnNewBusiness');
    if (newBusiness) newBusiness.onclick = () => { openSheet(renderBusinessForm()); bindBusinessForm(); };
    $$('[data-business-edit]').forEach((el) => el.onclick = () => {
      const b = ST.businesses.find(x => x.id === Number(el.dataset.businessEdit));
      if (b) { openSheet(renderBusinessForm(b)); bindBusinessForm(); }
    });
    $$('[data-business-select]').forEach((el) => el.onclick = () => {
      ST.activeBusinessId = Number(el.dataset.businessSelect);
      try { localStorage.setItem('lb.activeBusinessId', String(ST.activeBusinessId)); } catch (e) {}
      render(); toast('کسب‌وکار فعال انتخاب شد');
    });
    $$('[data-business-delete]').forEach((el) => el.onclick = async () => {
      const b = ST.businesses.find(x => x.id === Number(el.dataset.businessDelete));
      if (!b || !confirm(`کسب‌وکار «${b.name}» از فهرست حذف شود؟ بنرها و سفارش‌های قبلی حفظ می‌شوند.`)) return;
      const d = await api(`/businesses/${b.id}/delete`, { method: 'POST', body: {} });
      toast(d.message || (d.ok ? 'حذف شد' : 'خطا'));
      if (d.ok) { if (ST.activeBusinessId === b.id) ST.activeBusinessId = null; await loadBusinesses(); render(); }
    });

    $$('[data-r]').forEach((el) => el.onclick = async () => {
      const r = el.dataset.r;
      setRole(r);
      ST.loading = true; render();
      try {
        if (r === 'manager') { await loadMyChannels(); await loadMgrOrders(); if (ST.mgrTab === 'tariffs') await loadMgrTariffs(); }
        if (r === 'operator') { await loadOpBanners(); await loadOpPayouts(); }
        if (r === 'advertiser') { await loadCatalog(); }
      } catch (e) { toast(e.message || 'خطا'); }
      ST.loading = false;
      render();
    });
    const th2 = $('#btnTheme2');
    if (th2) th2.onclick = (e) => {
      const dark = document.documentElement.dataset.theme !== 'dark';
      setTheme(dark, e);
      render();
    };

    const inv = $('#btnInvoice');
    if (inv) inv.onclick = () => {
      openSheet(`<div class="sheet-handle"></div><h3>شارژ کیف پول</h3><p class="hint">مبلغ دلخواه را به تومان وارد کنید (حداقل ۱۰٬۰۰۰ و حداکثر ۱٬۰۰۰٬۰۰۰ تومان در هر فاکتور).</p><div class="field"><label>مبلغ (تومان)</label><input id="invoiceAmount" type="number" min="10000" max="1000000" step="1000" value="100000" inputmode="numeric" /></div><button class="btn btn-primary btn-block" id="btnSendInvoice">ساخت فاکتور پرداخت</button>`);
      $('#btnSendInvoice').onclick = async () => {
        const amount = Number($('#invoiceAmount').value);
        if (!Number.isInteger(amount) || amount < 10000 || amount > 1000000) return toast('مبلغ باید عدد صحیح بین ۱۰٬۰۰۰ تا ۱٬۰۰۰٬۰۰۰ تومان باشد.');
        const submit = $('#btnSendInvoice'); submit.disabled = true;
        try {
          const d = await api('/pay/invoice', { method: 'POST', body: { amount } });
          toast(d.message || (d.ok ? 'فاکتور ارسال شد' : (d.error || 'خطا')));
          if (d.ok) {
            closeSheet();
            if (d.bot_url) {
              openSheet(`<div class="sheet-handle"></div><h3>فاکتور به بله ارسال شد</h3><p class="hint">برای پرداخت فاکتور، گفت‌وگوی ربات را باز کنید. بعد از پرداخت، اعتبار کیف پول به‌صورت خودکار به‌روزرسانی می‌شود.</p><a class="btn btn-primary btn-block" href="${esc(d.bot_url)}" target="_blank" rel="noopener">باز کردن گفت‌وگوی بله</a><button class="btn btn-ghost btn-block" id="btnTopupDone" style="margin-top:8px">متوجه شدم</button>`);
              $('#btnTopupDone').onclick = closeSheet;
            }
          }
        } catch (e) { toast(e.message || 'ساخت فاکتور ناموفق بود'); }
        finally { submit.disabled = false; }
      };
    };
    const addBank = $('#btnAddBank');
    if (addBank) addBank.onclick = () => {
      openSheet(`<div class="sheet-handle"></div><h3>افزودن حساب بانکی</h3><p class="hint">شماره شبا باید با IR و ۲۴ رقم بعدی وارد شود.</p><div class="field"><label>نام صاحب حساب</label><input id="bankHolder" maxlength="200" autocomplete="name" placeholder="نام و نام خانوادگی" /></div><div class="field"><label>شماره شبا</label><input id="bankIban" maxlength="26" autocomplete="off" placeholder="IR000000000000000000000000" dir="ltr" /></div><button class="btn btn-primary btn-block" id="btnSaveBank">ذخیره حساب</button>`);
      $('#btnSaveBank').onclick = async () => {
        const holder_name = $('#bankHolder').value.trim();
        const iban = $('#bankIban').value.replace(/[\s-]/g, '').toUpperCase();
        if (!holder_name || !/^IR\d{24}$/.test(iban)) { toast('نام صاحب حساب و شماره شبای معتبر را وارد کنید.'); return; }
        const d = await api('/bank', { method: 'POST', body: { holder_name, iban } });
        toast(d.message || (d.ok ? 'حساب بانکی ذخیره شد.' : 'ذخیره حساب ناموفق بود.'));
        if (d.ok) { closeSheet(); await loadWallet(); render(); }
      };
    };
    const payout = $('#btnPayout');
    if (payout) payout.onclick = () => {
      const wallet = ST.wallet || {};
      const banks = wallet.banks || [];
      if (!banks.length) { toast('ابتدا یک حساب بانکی اضافه کنید.'); return; }
      if (wallet.can_payout === false) { toast('شرایط ثبت برداشت فراهم نیست. حداقل مبلغ یا وضعیت کیف پول را بررسی کنید.'); return; }
      openSheet(`<div class="sheet-handle"></div><h3>درخواست برداشت</h3><p class="hint">مبلغ برداشت مطابق موجودی قابل برداشت و حداقل تعیین‌شده توسط سامانه بررسی می‌شود.</p><div class="field"><label>حساب بانکی مقصد</label><select id="payoutBank">${banks.map(b => `<option value="${b.id}">${esc(b.holder_name || 'صاحب حساب')} ···${esc(b.iban_tail || '')}${b.is_default ? ' (پیش‌فرض)' : ''}</option>`).join('')}</select></div><button class="btn btn-primary btn-block" id="btnSubmitPayout">ثبت درخواست برداشت</button>`);
      $('#btnSubmitPayout').onclick = async () => {
        const bank_id = Number($('#payoutBank').value);
        if (!bank_id) { toast('حساب بانکی را انتخاب کنید.'); return; }
        const d = await api('/payout', { method: 'POST', body: { bank_id } });
        toast(d.message || (d.ok ? 'درخواست برداشت ثبت شد.' : (d.error || 'ثبت درخواست ناموفق بود.')));
        if (d.ok) { closeSheet(); await loadWallet(); render(); }
      };
    };

    const availabilityBtn = $('#btnManageAvailability');
    if (availabilityBtn) availabilityBtn.onclick = async () => {
      availabilityBtn.disabled = true;
      try {
        const d = await api('/tariffs');
        const tariffs = (d.tariffs || d.items || []).filter(t => !ST.selectedMgrChannel || Number(t.channel_id || t.channel) === Number(ST.selectedMgrChannel));
        if (!d.ok || !tariffs.length) { toast(d.message || 'برای این کانال تعرفهٔ فعالی پیدا نشد.'); return; }
        openSheet(`<div class="sheet-handle"></div><h3>مدیریت روزهای آزاد و مسدود</h3>
          <div class="field"><label>تعرفه</label><select id="availabilityTariff">${tariffs.map(t => `<option value="${t.id}">${esc(t.name || (t.duration_hours + ' ساعته'))} · ${faNum(t.price)} تومان</option>`).join('')}</select></div>
          <div class="field"><label>تاریخ</label><input id="availabilityDate" type="date" min="${new Date().toISOString().slice(0,10)}" /></div>
          <button class="btn btn-danger btn-block" id="btnBlockDay">مسدودکردن این روز</button>
          <button class="btn btn-primary btn-block" id="btnUnblockDay" style="margin-top:8px">آزادکردن این روز</button>
          <div id="availabilityPreview" class="hint" style="margin-top:12px">برای مشاهدهٔ وضعیت، تعرفه و تاریخ را انتخاب کنید.</div>`);
        const refreshAvailability = async () => {
          const tid = Number($('#availabilityTariff').value);
          const day = $('#availabilityDate').value;
          if (!tid || !day) return;
          const cal = await api('/calendar?tariff_id=' + encodeURIComponent(tid) + '&days=42');
          const entry = (cal.days || []).find(x => x.date === day);
          $('#availabilityPreview').textContent = entry ? `وضعیت ${entry.jalali || entry.date}: ${entry.status || (entry.free ? 'آزاد' : 'مسدود')}${entry.why ? ' — ' + entry.why : ''}` : 'وضعیت این روز در پاسخ تقویم موجود نیست.';
        };
        $('#availabilityDate').value = new Date().toISOString().slice(0,10);
        $('#availabilityTariff').onchange = refreshAvailability;
        $('#availabilityDate').onchange = refreshAvailability;
        $('#btnBlockDay').onclick = async () => {
          const tariff_id = Number($('#availabilityTariff').value), date = $('#availabilityDate').value;
          if (!date) return toast('تاریخ را انتخاب کنید');
          const r = await api('/busy-day', { method:'POST', body:{ tariff_id, date } });
          toast(r.message || (r.ok ? 'روز مسدود شد' : r.error || 'خطا'));
          if (r.ok) refreshAvailability();
        };
        $('#btnUnblockDay').onclick = async () => {
          const tariff_id = Number($('#availabilityTariff').value), date = $('#availabilityDate').value;
          if (!date) return toast('تاریخ را انتخاب کنید');
          const r = await api('/clear-busy', { method:'POST', body:{ tariff_id, date } });
          toast(r.message || (r.ok ? 'روز آزاد شد' : r.error || 'خطا'));
          if (r.ok) refreshAvailability();
        };
        refreshAvailability();
      } catch (e) { toast(e.message || 'دریافت تقویم ناموفق بود'); }
      finally { availabilityBtn.disabled = false; }
    };
    const mgrOrdersHome = $('#btnMgrOrdersGoHome'); if (mgrOrdersHome) mgrOrdersHome.onclick = () => navigate('mgr-home');
    const refreshOrders = $('#btnRefreshOrders');
    if (refreshOrders) refreshOrders.onclick = async () => {
      refreshOrders.disabled = true;
      try { if (ST.role === 'manager') await loadMgrOrders(); else await loadOrders(); render(); }
      catch (e) { toast(e.message || 'دریافت سفارش‌ها ناموفق بود'); }
      finally { refreshOrders.disabled = false; }
    };

    $$('[data-manager-tab]').forEach((b) => b.onclick = async () => {
      ST.mgrTab = b.dataset.managerTab;
      const target = ST.mgrTab === 'channels' ? 'mgr-channels' : ST.mgrTab === 'tariffs' ? 'mgr-tariffs' : 'mgr-home';
      try { if (target === 'mgr-channels') await loadMyChannels(); else if (target === 'mgr-tariffs') await loadMgrTariffs(); else await loadMgrOrders(); } catch(e) { toast(e.message || 'به‌روزرسانی انجام نشد'); }
      navigate(target);
    });
    const goChannels = $('#btnMgrToChannels');
    if (goChannels) goChannels.onclick = async () => { ST.mgrTab='channels'; try { await loadMyChannels(); } catch(e) {} navigate('mgr-channels'); };
    const showPublish = $('#btnMgrShowPublish'); if (showPublish) showPublish.onclick = () => { ST.orderTab='active'; navigate('orders'); };
    const mgrHistory = $('#btnMgrHistory'); if (mgrHistory) mgrHistory.onclick = async () => { try { await loadMgrOrders(); } catch(e) {} navigate('orders'); };
    const refreshChannelsTop = $('#btnMgrRefreshChannelsTop'); if (refreshChannelsTop) refreshChannelsTop.onclick = async () => { try { await loadMyChannels(); } catch(e) { toast(e.message||'به‌روزرسانی انجام نشد'); } render(); };
    const refreshTariffsTop = $('#btnRefreshTariffsTop'); if (refreshTariffsTop) refreshTariffsTop.onclick = async () => { try { await loadMgrTariffs(); } catch(e) { toast(e.message||'به‌روزرسانی انجام نشد'); } render(); };
    const connectChannelsBottom = $('#btnMgrConnectChannelsBottom'); if (connectChannelsBottom) connectChannelsBottom.onclick = () => { const w=window.Bale&&window.Bale.WebApp; if(w&&typeof w.openLink==='function') w.openLink('https://ble.ir/linkban'); else window.open('https://ble.ir/linkban','_blank'); };
    const refreshEmptyInbox = $('#btnMgrRefreshEmpty');
    if (refreshEmptyInbox) refreshEmptyInbox.onclick = async () => { try { await loadMgrOrders(); } catch(e) {} render(); };
    const connectChannels = $('#btnMgrConnectChannels');
    if (connectChannels) connectChannels.onclick = () => { const w=window.Bale&&window.Bale.WebApp; if(w&&typeof w.openLink==='function') w.openLink('https://ble.ir/linkban'); else window.open('https://ble.ir/linkban','_blank'); };
    ['#btnMgrRefreshChannelsEmpty','#btnMgrRefreshChannelsList'].forEach(sel => { const b=$(sel); if(b) b.onclick=async()=>{ try { await loadMyChannels(); } catch(e){} render(); }; });
    ['#btnOpRefreshEmpty','#btnOpRefreshList'].forEach(sel => { const b=$(sel); if(b) b.onclick=async()=>{ try { await Promise.allSettled([loadOpBanners(),loadOpPayouts(),loadOpAssignments()]); } catch(e){} render(); }; });
    $$('[data-op-shortcut]').forEach((b) => b.onclick = async () => { ST.opTab=b.dataset.opShortcut; if(ST.opTab==='assign') await loadOpAssignments(); if(ST.opTab==='payouts') await loadOpPayouts(); if(ST.opTab==='banners') await loadOpBanners(); render(); });

    // —— Manager ——
    $$('#mgrTabs button').forEach((b) => b.onclick = async () => { ST.mgrTab = b.dataset.t; if (ST.mgrTab === 'tariffs') { try { await loadMgrTariffs(); } catch (e) { toast(e.message || 'خطا در دریافت تعرفه‌ها'); } } render(); });
    const mgrRef = $('#btnMgrRefresh');
    if (mgrRef) mgrRef.onclick = async () => {
      ST.loading = true; render();
      try { await loadMyChannels(); await loadMgrOrders(); await api('/channels/refresh', { method: 'POST', body: { force: true } }); }
      catch (e) { toast(e.message || 'خطا'); }
      ST.loading = false; render();
    };
    $$('[data-mgr-approve]').forEach((b) => b.onclick = async () => {
      const d = await api('/orders/approve', { method: 'POST', body: { item_id: Number(b.dataset.mgrApprove) } });
      toast(d.message || (d.ok ? 'تأیید شد' : (d.error || 'خطا')));
      await loadMgrOrders(); render();
    });
    $$('[data-mgr-reject]').forEach((b) => b.onclick = async () => {
      const d = await api('/orders/reject', { method: 'POST', body: { item_id: Number(b.dataset.mgrReject) } });
      toast(d.message || (d.ok ? 'رد شد' : (d.error || 'خطا')));
      await loadMgrOrders(); render();
    });
    $$('[data-mgr-suggest]').forEach((b) => b.onclick = () => {
      const itemId = Number(b.dataset.mgrSuggest);
      openSheet(`
        <div class="sheet-handle"></div>
        <h3 style="margin:0 0 12px;text-align:center">پیشنهاد روز دیگر</h3>
        <div class="field"><label>تاریخ (YYYY-MM-DD)</label>
          <input id="suggestDate" type="date" /></div>
        <p class="hint">می‌توانید روز دیگری انتخاب کنید (نه فقط همان روز).</p>
        <button class="btn btn-primary btn-block" id="btnDoSuggest">ارسال پیشنهاد زمان</button>`);
      $('#btnDoSuggest').onclick = async () => {
        const day = $('#suggestDate').value;
        if (!day) { toast('تاریخ را وارد کنید'); return; }
        const d = await api('/orders/suggest', { method: 'POST', body: { item_id: itemId, date: day } });
        toast(d.message || (d.ok ? 'پیشنهاد ارسال شد' : (d.error || 'خطا')));
        if (d.ok) { closeSheet(); await loadMgrOrders(); render(); }
      };
    });
    /* انتشار دستی مدیر حذف شد — فقط زمان‌بندی خودکار */
    $$('[data-mgr-ch]').forEach((b) => b.onclick = () => {
      ST.selectedMgrChannel = Number(b.dataset.mgrCh);
      navigate('mgr-channel');
    });
    $$('[data-mgr-mode]').forEach((b) => b.onclick = () => {
      const chId = Number(b.dataset.mgrMode);
      openSheet(`
        <div class="sheet-handle"></div>
        <h3 style="margin:0 0 12px;text-align:center">روش انتشار</h3>
        <div class="seg" id="modeSeg">
          <button type="button" data-m="bot" class="on">ربات</button>
          <button type="button" data-m="linkyar">لینک‌یار</button>
          <button type="button" data-m="manual">دستی</button>
        </div>
        <button class="btn btn-primary btn-block" id="btnSaveMode">ذخیره</button>`);
      let mode = 'bot';
      $$('#modeSeg button').forEach((x) => x.onclick = () => {
        mode = x.dataset.m;
        $$('#modeSeg button').forEach((y) => y.classList.toggle('on', y === x));
      });
      $('#btnSaveMode').onclick = async () => {
        const d = await api('/publish-mode', { method: 'POST', body: { channel_id: chId, publish_mode: mode } });
        toast(d.message || (d.ok ? 'ذخیره شد' : (d.error || 'خطا')));
        if (d.ok) { closeSheet(); await loadMyChannels(); render(); }
      };
    });
    const addTariff = $('#btnAddTariff') || $('#btnAddTariffForCh');
    if (addTariff) addTariff.onclick = () => {
      const chs = ST.myChannels || [];
      openSheet(`
        <div class="sheet-handle"></div>
        <h3 style="margin:0 0 12px;text-align:center">تعرفه جدید</h3>
        <div class="field"><label>کانال</label>
          <select id="tChannel">${chs.map((c)=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>
        <div class="field"><label>نام تعرفه</label><input id="tName" placeholder="مثلاً ۲۴ ساعته" value="۲۴ ساعته"/></div>
        <div class="field"><label>مدت (ساعت)</label><input id="tDur" type="number" value="24"/></div>
        <div class="field"><label>قیمت (تومان)</label><input id="tPrice" type="number" placeholder="مثلاً 150000"/></div>
        <button class="btn btn-primary btn-block" id="btnSaveTariff">ثبت تعرفه</button>`);
      if (ST.selectedMgrChannel) {
        const sel = $('#tChannel');
        if (sel) sel.value = String(ST.selectedMgrChannel);
      }
      $('#btnSaveTariff').onclick = async () => {
        const body = {
          channel_id: Number($('#tChannel').value),
          name: $('#tName').value.trim(),
          duration_hours: Number($('#tDur').value) || 24,
          price: Number($('#tPrice').value) || 0,
        };
        const d = await api('/tariffs/add', { method: 'POST', body });
        toast(d.message || (d.ok ? 'تعرفه ثبت شد' : (d.error || 'خطا')));
        if (d.ok) { closeSheet(); await loadMyChannels(); render(); }
      };
    };
    const refreshTariffs = $('#btnRefreshTariffs');
    if (refreshTariffs) refreshTariffs.onclick = async () => {
      refreshTariffs.disabled = true;
      try { await loadMgrTariffs(); render(); toast('تعرفه‌ها به‌روز شد'); }
      catch (e) { toast(e.message || 'دریافت تعرفه‌ها ناموفق بود'); }
      finally { refreshTariffs.disabled = false; }
    };
    $$('[data-tariff-edit]').forEach((b) => b.onclick = () => {
      const t = (ST.mgrTariffs || []).find(x => Number(x.id) === Number(b.dataset.tariffEdit));
      if (!t) return;
      openSheet(`<div class="sheet-handle"></div><h3>ویرایش تعرفه</h3>
        <div class="field"><label>نام تعرفه</label><input id="editTName" maxlength="100" value="${esc(t.name || '')}" /></div>
        <div class="field"><label>مدت (ساعت)</label><input id="editTDur" type="number" min="1" max="720" value="${Number(t.duration_hours || 24)}" /></div>
        <div class="field"><label>قیمت (تومان)</label><input id="editTPrice" type="number" min="0" value="${Number(t.price || 0)}" /></div>
        <div class="field"><label>ساعت شروع</label><input id="editTStart" type="number" min="0" max="23" value="${Number(t.start_hour || 0)}" /></div>
        <button class="btn btn-primary btn-block" id="btnSaveTariffEdit">ذخیره تغییرات</button>`);
      $('#btnSaveTariffEdit').onclick = async () => {
        const body = { tariff_id: t.id, name: $('#editTName').value.trim(), duration_hours: Number($('#editTDur').value), price: Number($('#editTPrice').value), start_hour: Number($('#editTStart').value) };
        if (!body.name || body.duration_hours < 1 || body.price < 0 || body.start_hour < 0 || body.start_hour > 23) return toast('مقادیر تعرفه را بررسی کنید.');
        const d = await api('/tariffs/update', { method: 'POST', body });
        toast(d.message || (d.ok ? 'تعرفه ویرایش شد' : d.error || 'خطا'));
        if (d.ok) { closeSheet(); await loadMgrTariffs(); render(); }
      };
    });
    $$('[data-tariff-toggle]').forEach((b) => b.onclick = async () => {
      const id = Number(b.dataset.tariffToggle), active = b.dataset.active !== '1';
      const d = await api('/tariffs/update', { method: 'POST', body: { tariff_id: id, is_active: active } });
      toast(d.message || (d.ok ? 'وضعیت تعرفه تغییر کرد' : d.error || 'خطا'));
      if (d.ok) { await loadMgrTariffs(); render(); }
    });
    $$('[data-tariff-delete]').forEach((b) => b.onclick = async () => {
      const id = Number(b.dataset.tariffDelete);
      if (!confirm('تعرفه حذف شود؟ اگر سفارش یا رزرو داشته باشد، سامانه آن را غیرفعال می‌کند.')) return;
      const d = await api('/tariffs/delete', { method: 'POST', body: { tariff_id: id } });
      toast(d.message || (d.ok ? (d.deactivated ? 'تعرفه غیرفعال شد' : 'تعرفه حذف شد') : d.error || 'خطا'));
      if (d.ok) { await loadMgrTariffs(); render(); }
    });

    const refOne = $('#btnRefreshOne');
    if (refOne) refOne.onclick = async () => {
      const d = await api('/channels/refresh', { method: 'POST', body: { channel_id: ST.selectedMgrChannel, force: true } });
      toast(d.message || (d.ok ? 'آمار به‌روز شد' : (d.error || 'خطا')));
      await loadMyChannels(); render();
    };

    // —— Operator ——
    $$('#opTabs button').forEach((b) => b.onclick = async () => { ST.opTab = b.dataset.t; if (ST.opTab === 'assign') await loadOpAssignments(); render(); });
    const opRef = $('#btnOpRefresh');
    if (opRef) opRef.onclick = async () => {
      ST.loading = true; render();
      try { await loadOpBanners(); await loadOpPayouts(); await loadOpAssignments(); } catch (e) { toast(e.message || 'خطا'); }
      ST.loading = false; render();
    };
    $$('[data-op-approve]').forEach((b) => b.onclick = async () => {
      const d = await api('/operator/banner-decide', { method: 'POST', body: { request_id: Number(b.dataset.opApprove), approve: true } });
      toast(d.message || (d.ok ? 'تأیید شد' : (d.error || 'خطا')));
      await loadOpBanners(); render();
    });
    $$('[data-op-reject]').forEach((b) => b.onclick = async () => {
      const reason = prompt('دلیل رد بنر (اختیاری):') || '';
      const d = await api('/operator/banner-decide', { method: 'POST', body: { request_id: Number(b.dataset.opReject), approve: false, reason } });
      toast(d.message || (d.ok ? 'رد شد' : (d.error || 'خطا')));
      await loadOpBanners(); render();
    });
    const assignBtn = $('#btnAssignManager');
    if (assignBtn) assignBtn.onclick = async () => {
      const manager = $('#opManagerRef').value.trim();
      const channels = $('#opChannelRefs').value.trim();
      if (!manager || !channels) return toast('مدیر و حداقل یک کانال را وارد کنید');
      assignBtn.disabled = true;
      const d = await api('/operator/assign-manager', { method: 'POST', body: { manager, channels } });
      toast(d.message || (d.ok ? 'درخواست تخصیص ثبت شد' : (d.error || 'خطا')));
      if (d.ok) { $('#opManagerRef').value=''; $('#opChannelRefs').value=''; await loadOpAssignments(); render(); }
      assignBtn.disabled = false;
    };
    $$('[data-op-unassign]').forEach((b) => b.onclick = async () => {
      if (!confirm('تخصیص این کانال لغو شود؟')) return;
      const d = await api('/operator/unassign', { method: 'POST', body: { channel_id: Number(b.dataset.opUnassign) } });
      toast(d.message || (d.ok ? 'تخصیص لغو شد' : (d.error || 'خطا')));
      await loadOpAssignments(); render();
    });
    const batch = $('#btnOpBatch');
    if (batch) batch.onclick = async () => {
      const d = await api('/operator/mark-paid', { method: 'POST', body: {} });
      if (d.ok && d.file_text) {
        openSheet(`
          <div class="sheet-handle"></div>
          <h3 style="margin:0 0 12px;text-align:center">دسته واریز</h3>
          <p class="hint">${fa(d.count || 0)} مورد</p>
          <textarea readonly style="width:100%;min-height:120px;border-radius:12px;padding:10px;border:1px solid var(--line)">${esc(d.file_text)}</textarea>
          <button class="btn btn-primary btn-block" id="btnConfirmPaid" style="margin-top:10px">تأیید واریز انجام شد</button>`);
        $('#btnConfirmPaid').onclick = async () => {
          const r = await api('/operator/mark-paid', { method: 'POST', body: { confirm: true, batch_id: d.batch_id } });
          toast(r.message || (r.ok ? 'ثبت شد' : (r.error || 'خطا')));
          if (r.ok) { closeSheet(); await loadOpPayouts(); render(); }
        };
      } else {
        toast(d.message || d.error || 'درخواستی نیست');
      }
    };
  }

  const BANNER_DRAFT_KEY = 'lb.bannerDraft.v2';
  function getBannerDraft() {
    try { const d = JSON.parse(localStorage.getItem(BANNER_DRAFT_KEY) || 'null'); return d && typeof d === 'object' ? d : null; } catch (e) { return null; }
  }
  let bannerDraftSaveTimer = null;
  let bannerDraftMediaUploadPromise = Promise.resolve(null);
  // Serialize server draft writes so debounced text saves cannot overwrite uploads or
  // resurrect a cancelled/submitted draft.
  let bannerDraftServerQueue = Promise.resolve(null);
  function queueBannerDraftRequest(task) {
    const next = bannerDraftServerQueue.then(task, task);
    bannerDraftServerQueue = next.catch(() => null);
    return next;
  }
  function bannerDraftPayload(draft) {
    return { mode: draft.mode || 'media', title: draft.title || '', caption: draft.caption || '', business_id: draft.businessId || draft.business_id || null };
  }
  async function saveBannerDraftNow(draft) {
    if (bannerDraftSaveTimer) { clearTimeout(bannerDraftSaveTimer); bannerDraftSaveTimer = null; }
    const localDraft = Object.assign({ updated_at: Date.now() }, draft);
    try { localStorage.setItem(BANNER_DRAFT_KEY, JSON.stringify(localDraft)); } catch (e) {}
    return queueBannerDraftRequest(async () => {
      const result = await api('/banners/draft', { method: 'POST', body: { draft: bannerDraftPayload(localDraft) } });
      if (!result.ok) throw new Error(result.message || 'ذخیره پیش‌نویس در سرور انجام نشد');
      return result;
    });
  }
  function saveBannerDraft(draft) {
    const localDraft = Object.assign({ updated_at: Date.now() }, draft);
    try { localStorage.setItem(BANNER_DRAFT_KEY, JSON.stringify(localDraft)); } catch (e) {}
    if (bannerDraftSaveTimer) clearTimeout(bannerDraftSaveTimer);
    bannerDraftSaveTimer = setTimeout(() => {
      bannerDraftSaveTimer = null;
      saveBannerDraftNow(localDraft).catch(() => { /* Keep local fallback during outages. */ });
    }, 450);
  }
  async function saveBannerDraftMedia(file, draft) {
    if (!file) return null;
    const fd = new FormData();
    fd.append('mode', draft.mode || 'media');
    fd.append('title', draft.title || '');
    fd.append('caption', draft.caption || '');
    if (draft.businessId) fd.append('business_id', String(draft.businessId));
    fd.append('file', file, file.name || 'banner-media');
    return queueBannerDraftRequest(async () => {
      const result = await api('/banners/draft', { method: 'POST', body: fd, timeoutMs: 30000 });
      if (!result.ok) throw new Error(result.message || 'ذخیره فایل پیش‌نویس ناموفق بود');
      return result.draft || null;
    });
  }
  async function clearBannerDraft() {
    if (bannerDraftSaveTimer) { clearTimeout(bannerDraftSaveTimer); bannerDraftSaveTimer = null; }
    try { localStorage.removeItem(BANNER_DRAFT_KEY); } catch (e) {}
    try { await bannerDraftServerQueue; } catch (e) {}
    try { await queueBannerDraftRequest(() => api('/banners/draft', { method: 'DELETE', body: {} })); } catch (e) {}
  }

  function bindBannerForm() {
    let mode = 'media';
    let file = null;
    let draft = getBannerDraft();
    // Server draft is authoritative across devices; wait for this read before allowing
    // submit, otherwise a fast click after reopening could miss a server-stored file.
    const serverDraftLoad = api('/banners/draft').then((server) => {
      if (!server || !server.ok) return null;
      if (server.draft) {
        draft = { mode: server.draft.mode, title: server.draft.title, caption: server.draft.caption, businessId: server.draft.business_id, has_media: !!server.draft.has_media, media_file_name: server.draft.media_file_name || '', media_kind: server.draft.media_kind || '' };
        try { localStorage.setItem(BANNER_DRAFT_KEY, JSON.stringify(Object.assign({ updated_at: Date.now() }, draft))); } catch (e) {}
        applyDraft();
      } else {
        // Server is the source of truth when reachable; do not resurrect a submitted or
        // explicitly cancelled draft from stale browser storage.
        draft = null;
        try { localStorage.removeItem(BANNER_DRAFT_KEY); } catch (e) {}
      }
      return server;
    }).catch(() => null);
    function applyDraft() {
      if (!draft) return;
      if (draft.mode === 'text') { mode = 'text'; $$('#bannerType button').forEach((x) => x.classList.toggle('on', x.dataset.t === 'text')); if ($('#mediaBlock')) $('#mediaBlock').style.display = 'none'; }
      if ($('#bTitle')) $('#bTitle').value = draft.title || '';
      if ($('#bCaption')) $('#bCaption').value = draft.caption || '';
      if ($('#bannerBusiness') && (draft.businessId || draft.business_id)) $('#bannerBusiness').value = String(draft.businessId || draft.business_id);
      if ($('#fileName') && !file && draft.has_media && draft.media_file_name) $('#fileName').textContent = 'فایل ذخیره‌شده روی سرور: ' + draft.media_file_name;
    }
    applyDraft();
    const persist = () => saveBannerDraft({ mode, title: $('#bTitle')?.value || '', caption: $('#bCaption')?.value || '', businessId: Number($('#bannerBusiness')?.value || ST.activeBusinessId || 0) || null });
    ['bTitle','bCaption','bannerBusiness'].forEach((id) => { const el = $('#' + id); if (el) { el.addEventListener('input', persist); el.addEventListener('change', persist); } });
    $$('#bannerType button').forEach((b) => b.onclick = () => {
      mode = b.dataset.t;
      persist();
      $$('#bannerType button').forEach((x) => x.classList.toggle('on', x === b));
      $('#mediaBlock').style.display = mode === 'media' ? '' : 'none';
    });
    const zone = $('#uploadZone');
    const input = $('#bannerFile');
    if (zone && input) {
      zone.onclick = () => input.click();
      input.onchange = () => {
        file = input.files && input.files[0];
        $('#fileName').textContent = file ? file.name + ' · در حال ذخیرهٔ امن روی سرور…' : '';
        const snapshot = { mode, title: $('#bTitle')?.value || '', caption: $('#bCaption')?.value || '', businessId: Number($('#bannerBusiness')?.value || ST.activeBusinessId || 0) || null };
        if (file) {
          bannerDraftMediaUploadPromise = saveBannerDraftMedia(file, snapshot).then((saved) => {
            if (saved) {
              draft = Object.assign({}, draft || {}, snapshot, { has_media: !!saved.has_media, media_file_name: saved.media_file_name || file.name, media_kind: saved.media_kind || '' });
              $('#fileName').textContent = 'ذخیره شد روی سرور: ' + (saved.media_file_name || file.name);
              try { localStorage.setItem(BANNER_DRAFT_KEY, JSON.stringify(Object.assign({ updated_at: Date.now() }, draft))); } catch (e) {}
            }
            return saved;
          }).catch((e) => { toast(e.message || 'ذخیره فایل پیش‌نویس انجام نشد'); throw e; });
        } else {
          bannerDraftMediaUploadPromise = Promise.resolve(null);
        }
        persist();
      };
    }
    const cancelDraft = $('#btnCancelBannerDraft');
    if (cancelDraft) cancelDraft.onclick = () => {
      if (!confirm('ثبت بنر لغو شود و پیش‌نویس ذخیره‌شده پاک شود؟')) return;
      clearBannerDraft().then(() => { closeSheet(); toast('ثبت بنر لغو شد'); });
    };
    $('#btnSubmitBanner').onclick = async () => {
      const title = $('#bTitle').value.trim();
      const caption = $('#bCaption').value.trim();
      const businessId = Number($('#bannerBusiness')?.value || ST.activeBusinessId || 0);
      const submitDraft = { mode, title, caption, businessId: businessId || null };
      persist();
      if (caption.length < 12) { toast('متن بنر کوتاه است'); return; }
      const btn = $('#btnSubmitBanner');
      btn.disabled = true;
      try {
        await serverDraftLoad;
        let d;
        if (mode !== 'text') {
          try { await bannerDraftMediaUploadPromise; } catch (uploadError) { if (file) throw uploadError; }
        }
        // Persist latest fields before atomically consuming the server-side draft.
        await saveBannerDraftNow(submitDraft);
        if (mode === 'text') {
          d = await api('/banners/create', {
            method: 'POST',
            body: { title, caption, media_kind: 'text', text_only: true, business_id: businessId || null },
          });
        } else {
          if (!file && !(draft && draft.has_media)) { toast('تصویر یا ویدیو را انتخاب کنید'); btn.disabled = false; return; }
          if (file) {
            const fd = new FormData();
            fd.append('title', title);
            fd.append('caption', caption);
            if (businessId) fd.append('business_id', String(businessId));
            fd.append('file', file);
            d = await api('/banners/create', { method: 'POST', body: fd });
          } else {
            d = await api('/banners/create', { method: 'POST', body: { title, caption, media_kind: draft.media_kind || 'photo', business_id: businessId || null, use_draft_media: true } });
          }
        }
        if (d.ok) {
          await clearBannerDraft();
          toast('بنر ثبت شد و برای بررسی ارسال شد');
          closeSheet();
          await loadBanners();
          render();
        } else {
          toast(d.message || d.error || 'خطا');
        }
      } catch (e) {
        toast((e && e.message) || 'ارتباط با سرور برقرار نشد. دوباره تلاش کنید.');
      }
      btn.disabled = false;
    };
  }

  async function addToCart() {
    if (!ST.tariffId || !ST.selectedDay) return;
    try { await loadBanners(); } catch (e) {}
    const approvedBanners = (ST.banners || []).filter((b) => {
      if (b.is_active === false) return false;
      const s = String(b.stage || b.status || 'ready').toLowerCase();
      return s !== 'rejected';
    });
    openSheet(`
      <div class="sheet-handle"></div>
      <h3 style="margin:0 0 12px;text-align:center">ثبت در سبد</h3>
      <p class="hint">روز ${esc(ST.selectedDay)} · تعرفه #${fa(ST.tariffId)}</p>
      <div class="field"><label>بنر این جایگاه <span style="color:var(--danger,#c00)">*</span></label>
        <select id="cartBanner">
          ${approvedBanners.map((b)=>`<option value="${b.id}">${esc(b.title||('بنر '+b.id))}</option>`).join('') || '<option value="">بنری ندارید — اول بنر بسازید</option>'}
        </select>
      </div>
      ${approvedBanners.length
        ? '<button class="btn btn-primary btn-block" id="btnConfirmCart">افزودن به سبد و ارسال به مدیر</button><button class="btn btn-soft btn-block" id="btnAddOnly" style="margin-top:8px">فقط افزودن به سبد (ادامه خرید)</button>'
        : '<button class="btn btn-soft btn-block" id="btnGoBanners">ثبت بنر جدید</button>'}
    `);
    const goBanners = $('#btnGoBanners');
    if (goBanners) {
      goBanners.onclick = async () => {
        closeSheet();
        await requestNewBanner();
      };
      return;
    }
    const doAdd = async (andCheckout) => {
      const bannerId = Number($('#cartBanner').value) || 0;
      if (!bannerId) { toast('بنر را انتخاب کنید'); return; }
      const body = { tariff_id: ST.tariffId, date: ST.selectedDay, day: ST.selectedDay, banner_id: bannerId };
      const d = await api('/cart/add', { method: 'POST', body });
      if (!d.ok) {
        toast(d.message || d.error || 'خطا در سبد');
        return;
      }
      if (andCheckout) {
        const chk = await api('/checkout', { method: 'POST', body: {} });
        toast(chk.ok ? 'درخواست برای مدیر ارسال شد' : (chk.message || 'به سبد اضافه شد — برای ارسال، پرداخت/تأیید را کامل کنید'));
        closeSheet();
        await loadOrders();
        navigate('orders');
      } else {
        toast('به سبد اضافه شد — می‌توانید کانال دیگری هم انتخاب کنید');
        closeSheet();
        navigate('market');
      }
    };
    const btn = $('#btnConfirmCart');
    if (btn) btn.onclick = () => doAdd(true);
    const only = $('#btnAddOnly');
    if (only) only.onclick = () => doAdd(false);
  }

  async function payOrder(id) {
    try { await loadWallet(); } catch (e) {}
    const order = (ST.orders || []).find((o) => Number(o.id) === Number(id));
    const total = Number(order?.total || order?.total_amount || 0);
    const credit = Number((ST.wallet?.balance || ST.wallet || {}).credit || (ST.me?.wallet || {}).credit || 0);
    openSheet(`
      <div class="sheet-handle"></div>
      <h3 style="margin:0 0 8px;text-align:center">پرداخت سفارش #${fa(id)}</h3>
      <p class="hint">مبلغ: <b>${faNum(total)}</b> تومان · اعتبار شما: <b>${faNum(credit)}</b></p>
      <button class="btn btn-primary btn-block" id="payWallet" ${credit < total ? 'disabled' : ''}>پرداخت از اعتبار</button>
      <button class="btn btn-soft btn-block" id="payBot" style="margin-top:8px">فاکتور در گفتگوی بازو (کیف پول بله)</button>
      <button class="btn btn-soft btn-block" id="payCard" style="margin-top:8px">کارت‌به‌کارت / رسید</button>
      <p class="hint" style="margin-top:12px">درگاه داخل مینی‌اپ نیست؛ فاکتور بله در چت بازو باز می‌شود. کارت‌به‌کارت پس از ارسال رسید توسط پشتیبان تأیید می‌شود.</p>
    `);
    const run = async (via) => {
      const d = await api('/pay/invoice', { method: 'POST', body: { order_id: Number(id), via } });
      if (!d.ok) {
        toast(d.message || d.error || 'پرداخت ناموفق');
        return;
      }
      if (via === 'wallet' || d.via === 'wallet') {
        toast(d.message || 'از اعتبار پرداخت شد');
        closeSheet();
        await Promise.allSettled([loadOrders(), loadWallet()]);
        render();
        return;
      }
      const link = d.invoice_link || d.link || d.bot_url || '';
      try {
        const w = window.Bale && Bale.WebApp;
        if (d.open_bot && w && typeof w.close === 'function') {
          toast(d.message || 'به گفتگوی بازو بروید و فاکتور را پرداخت کنید');
          setTimeout(() => { try { w.close(); } catch (e) {} }, 500);
          return;
        }
        if (link && w && typeof w.openInvoice === 'function') {
          w.openInvoice(link, function (status) {
            toast(status === 'paid' ? 'پرداخت ثبت شد' : (status || 'فاکتور بسته شد'));
            loadOrders().then(render);
            loadWallet().then(render);
          });
          return;
        }
        if (link && w && typeof w.openLink === 'function') {
          w.openLink(link);
        }
      } catch (e) {}
      toast(d.message || 'فاکتور ارسال شد');
      closeSheet();
    };
    const wBtn = $('#payWallet');
    if (wBtn) wBtn.onclick = () => run('wallet');
    const bBtn = $('#payBot');
    if (bBtn) bBtn.onclick = () => run('bot');
    const cBtn = $('#payCard');
    if (cBtn) cBtn.onclick = async () => {
      let card = {};
      try {
        const info = await api('/pay/info');
        if (info.ok) card = info.card || {};
      } catch (e) {}
      openSheet(`
        <div class="sheet-handle"></div>
        <h3 style="text-align:center">کارت‌به‌کارت</h3>
        <p class="hint">مبلغ <b>${faNum(total)}</b> تومان · سفارش <b>#${fa(id)}</b></p>
        ${card.holder ? `<p class="hint">به‌نام: <b>${esc(card.holder)}</b></p>` : ''}
        ${card.card_number ? `<p class="hint" dir="ltr">کارت: <b>${esc(card.card_number)}</b></p>` : ''}
        ${card.iban ? `<p class="hint" dir="ltr">شبا: <b>${esc(card.iban)}</b></p>` : ''}
        ${card.bank_name ? `<p class="hint">بانک: ${esc(card.bank_name)}</p>` : ''}
        <p class="hint">${esc(card.note || 'پس از واریز، رسید را در تیکت بفرستید.')}</p>
        ${!(card.card_number || card.iban) ? '<p class="hint">حساب هنوز در تنظیمات پشتیبان ثبت نشده است.</p>' : ''}
        <button class="btn btn-primary btn-block" id="payCardTicket">ثبت تیکت + رسید</button>
      `);
      const t = $('#payCardTicket');
      if (t) t.onclick = () => {
        closeSheet();
        ST.pendingTicket = { category: 'wallet', subject: 'رسید کارت‌به‌کارت سفارش ' + id, order_id: id };
        navigate('help');
        setTimeout(() => {
          const openBtn = $('#btnNewTicket') || $('#btnOpenTicket');
          if (openBtn) openBtn.click();
        }, 300);
      };
    };
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function bindGlobal() {
    const btnBack = $('#btnBack');
    if (btnBack) btnBack.onclick = () => {
      if (ST.page === 'calendar') navigate('channel');
      else if (ST.page === 'channel') navigate('market');
      else if (ST.page === 'mgr-channel') navigate('mgr-channels');
      else if (ST.page === 'help' || ST.page === 'businesses' || ST.page === 'onboard') navigate('settings');
      else if (ST.role === 'manager') navigate('mgr-home');
      else if (ST.role === 'operator') navigate('op-home');
      else navigate('market');
    };
    const themeBtn = $('#btnTheme');
    if (themeBtn) {
      themeBtn.classList.add('tt');
      try {
        if (!themeBtn.querySelector('.tt-core')) themeBtn.innerHTML = themeToggleSvg();
        paintThemeButton(themeBtn);
      } catch (e) {}
      themeBtn.onclick = (e) => {
        try { setTheme(document.documentElement.dataset.theme !== 'dark', e); } catch (err) {}
      };
    }
    const btnProfile = $('#btnProfile');
    if (btnProfile) btnProfile.onclick = () => navigate('settings');
    const sheet = $('#sheet');
    if (sheet) sheet.onclick = (e) => { if (e.target.id === 'sheet') closeSheet(); };
    const bottomNav = $('#bottomNav');
    if (bottomNav) bottomNav.onclick = async (e) => {
      const btn = e.target.closest('[data-nav]');
      if (!btn) return;
      let id = btn.dataset.nav;
      if (id === 'mgr-channels') ST.mgrTab = 'channels';
      if (id === 'mgr-tariffs') ST.mgrTab = 'tariffs';
      if (id === 'mgr-home') ST.mgrTab = 'inbox';
      ST.loading = true; render();
      try {
        if (id === 'home') { await Promise.allSettled([loadOrders(), loadWallet(), loadBanners()]); }
        if (id === 'market') await ensureCatalog();
        if (id === 'banners') await loadBanners();
        if (id === 'orders') {
          if (ST.role === 'manager') await loadMgrOrders();
          else await loadOrders();
        }
        if (id === 'wallet') await loadWallet();
        if (id === 'help') { try { const t = await api('/tickets'); if (t.ok) ST.tickets = t.tickets || []; } catch(e) {} }
        if (id === 'mgr-home') { await Promise.allSettled([loadMyChannels(), loadMgrOrders(), loadMgrTariffs()]); }
        if (id === 'mgr-channels') await loadMyChannels();
        if (id === 'mgr-tariffs') { await Promise.allSettled([loadMyChannels(), loadMgrTariffs()]); }
        if (id === 'op-home') { await loadOpBanners(); await loadOpPayouts(); await loadOpAssignments(); }
      } catch (err) { toast(err.message || 'خطا'); }
      ST.loading = false;
      navigate(id);
    };
  }



  /* ——— Onboarding (اولین ورود) ——— */
  const OB_CATS = [
    'خبری', 'سرگرمی', 'بانوان', 'آموزش', 'فروشگاهی', 'سلامت و زیبایی',
    'املاک', 'خودرو', 'فناوری', 'غذا و رستوران', 'پوشاک', 'مسافرت', 'کسب‌وکار', 'سایر'
  ];
  const OB = {
    open: false,
    step: 'role',
    role: '',
    biz: { name: '', kind: 'bale', source_ref: '', categories: ['سایر'] },
    ch: { link: '', error: '', loading: false, id: 0, name: '' },
    pmode: 'manual',
    tariff: { name: '۲۴ ساعته', duration_hours: 24, price: '' },
    error: '',
    loading: false,
  };

  function obUid() {
    try {
      const id = (ST.me && (ST.me.bale_user_id || ST.me.id)) || debugId() || '';
      return String(id || '').trim();
    } catch (e) { return ''; }
  }
  function obKey(k) {
    const u = obUid();
    return u ? ('lb.' + u + '.' + k) : ('lb.' + k);
  }
  function obMarkDone(role) {
    try {
      localStorage.setItem(obKey('onboard_done'), '1');
      localStorage.setItem(obKey('role_chosen'), '1');
      if (role === 'manager') localStorage.setItem(obKey('manager_onboarded'), '1');
      if (role === 'advertiser' || role === 'customer') localStorage.setItem(obKey('customer_onboarded'), '1');
      if (role) {
        const r = role === 'customer' ? 'advertiser' : role;
        localStorage.setItem(obKey('role'), r);
        localStorage.setItem('lb.role', r);
      }
    } catch (e) {}
  }
  function obNeedShow() {
    try {
      if (new URLSearchParams(location.search).get('onboard') === '1') return true;
    } catch (e) {}
    const hasMgr = ((ST.myChannels || []).length + (ST.myGroups || []).length) > 0;
    const hasBiz = (ST.businesses || []).length > 0;
    if (hasMgr) { obMarkDone('manager'); return false; }
    if (hasBiz) { obMarkDone('advertiser'); return false; }
    try {
      if (localStorage.getItem(obKey('onboard_done')) === '1') return false;
    } catch (e) {}
    return true;
  }
  function obProgress() {
    const map = {
      role: 10, biz_name: 30, biz_kind: 50, biz_cat: 70, biz_done: 100,
      ch_link: 30, pmode: 50, tariff: 75, mgr_done: 100,
    };
    return map[OB.step] || 20;
  }

  function buildObHtml() {
    const step = OB.step;
    const logo = `<div class="lb-ob-logo"><img src="/miniapp/assets/logo-linkban.jpg" alt="لینک‌بان" onerror="this.style.display='none';this.parentNode.innerHTML='<span>ل</span>'"/></div>`;
    let body = '';
    if (step === 'role') {
      body = `${logo}
        <div class="lb-ob-title">خوش آمدید 👋</div>
        <p class="lb-ob-sub">بگویید برای چه کاری آمده‌اید تا فضای مناسب شما باز شود.</p>
        <div class="lb-ob-cards">
          <button type="button" class="lb-ob-card" data-ob="role-advertiser">
            <span class="lb-ob-card-ico">${icon('megaphone',22)}</span>
            <span><b>آگهی‌دهنده هستم</b><small>می‌خواهم در کانال‌های بله تبلیغ بخرم</small></span>
          </button>
          <button type="button" class="lb-ob-card" data-ob="role-manager">
            <span class="lb-ob-card-ico">${icon('building-2',22)}</span>
            <span><b>مدیر کانال هستم</b><small>می‌خواهم جایگاه تبلیغاتی بفروشم</small></span>
          </button>
        </div>`;
    } else if (step === 'biz_name') {
      body = `${logo}
        <div class="lb-ob-title">نام کسب‌وکارتان چیست؟</div>
        <p class="lb-ob-sub">همین نام در سفارش‌ها و بنرها نمایش داده می‌شود.</p>
        <div class="lb-ob-field"><label>نام کسب‌وکار</label>
          <input id="ob-biz-name" maxlength="160" placeholder="مثلاً فروشگاه گیاهان طبیعی" value="${esc(OB.biz.name)}"/>
        </div>
        ${OB.error ? `<div class="lb-ob-err">${esc(OB.error)}</div>` : ''}`;
    } else if (step === 'biz_kind') {
      body = `${logo}
        <div class="lb-ob-title">کسب‌وکارتان کجاست؟</div>
        <p class="lb-ob-sub">اگر کانال بله دارید همان را انتخاب کنید؛ وگرنه فروشگاه یا صفحه خارجی.</p>
        <div class="lb-ob-opts">
          <button type="button" class="lb-ob-opt ${OB.biz.kind==='bale'?'on':''}" data-ob="kind-bale"><span class="radio"></span><div><b>کانال یا گروه بله</b><span>با شناسه یا لینک ble.ir</span></div></button>
          <button type="button" class="lb-ob-opt ${OB.biz.kind==='external'?'on':''}" data-ob="kind-external"><span class="radio"></span><div><b>فروشگاه خارج از بله</b><span>سایت، اینستاگرام و …</span></div></button>
        </div>
        <div class="lb-ob-field" style="margin-top:14px"><label>${OB.biz.kind==='bale'?'شناسه یا لینک کانال':'آدرس (اختیاری)'}</label>
          <input id="ob-biz-ref" maxlength="200" placeholder="${OB.biz.kind==='bale'?'@mychannel یا ble.ir/…':'https://…'}" value="${esc(OB.biz.source_ref)}"/>
        </div>
        ${OB.error ? `<div class="lb-ob-err">${esc(OB.error)}</div>` : ''}`;
    } else if (step === 'biz_cat') {
      body = `${logo}
        <div class="lb-ob-title">فعالیت شما درباره چیست؟</div>
        <p class="lb-ob-sub">یک یا چند موضوع نزدیک به کارتان را انتخاب کنید.</p>
        <div class="lb-ob-chips">
          ${OB_CATS.map((c) => `<button type="button" class="lb-ob-chip ${(OB.biz.categories||[]).includes(c)?'on':''}" data-ob="cat-${esc(c)}">${esc(c)}</button>`).join('')}
        </div>
        ${OB.error ? `<div class="lb-ob-err">${esc(OB.error)}</div>` : ''}`;
    } else if (step === 'biz_done') {
      body = `<div class="lb-ob-done">
        <div class="ok-ico">${icon('check',28)}</div>
        <div class="lb-ob-title">آماده‌اید</div>
        <p class="lb-ob-sub">«${esc(OB.biz.name)}» آماده است. در مرحله بعد می‌توانید بنر بسازید و کانال انتخاب کنید.</p>
      </div>`;
    } else if (step === 'ch_link') {
      body = `${logo}
        <div class="lb-ob-title">کانال خود را اضافه کنید</div>
        <p class="lb-ob-sub">آدرس کانال بله‌تان را بنویسید تا بتوانید برایش تعرفه بگذارید.</p>
        <div class="lb-ob-field"><label>آدرس کانال</label>
          <input id="ob-ch-link" maxlength="120" placeholder="مثلاً @mychannel یا ble.ir/mychannel" value="${esc(OB.ch.link)}"/>
        </div>
        ${OB.ch.error || OB.error ? `<div class="lb-ob-err">${esc(OB.ch.error || OB.error)}</div>` : ''}`;
    } else if (step === 'pmode') {
      body = `${logo}
        <div class="lb-ob-title">تبلیغ‌ها چطور منتشر شوند؟</div>
        <p class="lb-ob-sub">برای کانال «${esc(OB.ch.name || 'شما')}» یکی را انتخاب کنید.</p>
        <div class="lb-ob-opts">
          <button type="button" class="lb-ob-opt ${OB.pmode==='manual'?'on':''}" data-ob="pmode-manual"><span class="radio"></span><div><b>خودم می‌فرستم</b><span>در زمان توافق‌شده خودتان در کانال پست می‌گذارید</span></div></button>
          <button type="button" class="lb-ob-opt ${OB.pmode==='bot'?'on':''}" data-ob="pmode-bot"><span class="radio"></span><div><b>خودکار با بازو</b><span>بازو را ادمین کانال کنید تا خودش بفرستد</span></div></button>
          <button type="button" class="lb-ob-opt ${OB.pmode==='linkyar'?'on':''}" data-ob="pmode-linkyar"><span class="radio"></span><div><b>خودکار با حساب دستیار</b><span>حساب دستیار لینک‌بان را ادمین کانال کنید</span></div></button>
        </div>`;
    } else if (step === 'tariff') {
      body = `${logo}
        <div class="lb-ob-title">اولین قیمت‌گذاری</div>
        <p class="lb-ob-sub">مدت ماندن تبلیغ و مبلغ را مشخص کنید. بعداً می‌توانید تغییر دهید.</p>
        <div class="lb-ob-field"><label>نام تعرفه</label>
          <input id="ob-tar-name" maxlength="80" value="${esc(OB.tariff.name)}" placeholder="مثلاً ۲۴ ساعته"/>
        </div>
        <div class="lb-ob-chips">
          ${[[12,'۱۲ ساعت'],[24,'۲۴ ساعت'],[48,'۴۸ ساعت'],[72,'۷۲ ساعت']].map(([h,l]) =>
            `<button type="button" class="lb-ob-chip ${Number(OB.tariff.duration_hours)===h?'on':''}" data-ob="dur-${h}">${l}</button>`
          ).join('')}
        </div>
        <div class="lb-ob-field"><label>قیمت (تومان)</label>
          <input id="ob-tar-price" type="number" inputmode="numeric" min="0" step="1000" placeholder="مثلاً ۱۵۰۰۰۰" value="${esc(OB.tariff.price)}"/>
        </div>
        ${OB.error ? `<div class="lb-ob-err">${esc(OB.error)}</div>` : ''}`;
    } else if (step === 'mgr_done') {
      body = `<div class="lb-ob-done">
        <div class="ok-ico">${icon('check',28)}</div>
        <div class="lb-ob-title">همه‌چیز آماده است</div>
        <p class="lb-ob-sub">کانال «${esc(OB.ch.name || OB.ch.link)}» ثبت شد. از این به بعد درخواست‌های تبلیغ اینجا می‌آید.</p>
      </div>`;
    } else {
      body = `${logo}<div class="lb-ob-title">ادامهٔ ثبت‌نام</div>`;
    }

    let foot = '';
    if (step === 'biz_done' || step === 'mgr_done') {
      foot = `<button type="button" class="btn btn-primary" data-ob="finish">ورود به لینک‌بان</button>`;
    } else if (step !== 'role') {
      const backStep = {
        biz_name: 'role', biz_kind: 'biz_name', biz_cat: 'biz_kind',
        ch_link: 'role', pmode: 'ch_link', tariff: 'pmode',
      }[step];
      foot = `${backStep ? `<button type="button" class="btn btn-soft" data-ob="back">بازگشت</button>` : ''}
        <button type="button" class="btn btn-primary" data-ob="next" ${OB.loading || OB.ch.loading ? 'disabled' : ''}>${OB.loading || OB.ch.loading ? '…' : 'ادامه'}</button>`;
    }

    return `
      <div class="lb-ob-inline">
        <div class="lb-ob-progress"><i style="width:${obProgress()}%"></i></div>
        <div class="lb-ob-body">${body}</div>
        ${foot ? `<div class="lb-ob-foot">${foot}</div>` : ''}
      </div>`;
  }

  function renderOnboardPage() {
    document.documentElement.classList.remove('lb-ob-lock');
    const old = document.getElementById('lb-ob-root');
    if (old) old.remove();
    return buildObHtml();
  }

  async function handleObAction(act) {
    OB.error = '';
    OB.ch.error = '';
    if (act === 'role-advertiser') {
      OB.role = 'advertiser'; OB.step = 'biz_name'; ST.role = 'advertiser';
      try { localStorage.setItem(obKey('role'), 'advertiser'); localStorage.setItem(obKey('role_chosen'), '1'); localStorage.setItem('lb.role', 'advertiser'); } catch (e) {}
      return render();
    }
    if (act === 'role-manager') {
      OB.role = 'manager'; OB.step = 'ch_link'; ST.role = 'manager';
      try { localStorage.setItem(obKey('role'), 'manager'); localStorage.setItem(obKey('role_chosen'), '1'); localStorage.setItem('lb.role', 'manager'); } catch (e) {}
      return render();
    }
    if (act === 'kind-bale' || act === 'kind-external') {
      OB.biz.kind = act === 'kind-bale' ? 'bale' : 'external';
      return render();
    }
    if (act.startsWith('pmode-')) {
      OB.pmode = act.slice(6);
      return render();
    }
    if (act.startsWith('dur-')) {
      OB.tariff.duration_hours = parseInt(act.slice(4), 10) || 24;
      return render();
    }
    if (act.startsWith('cat-')) {
      const c = act.slice(4);
      const arr = OB.biz.categories || [];
      if (arr.includes(c)) OB.biz.categories = arr.filter((x) => x !== c);
      else OB.biz.categories = arr.concat([c]);
      if (!OB.biz.categories.length) OB.biz.categories = ['سایر'];
      return render();
    }
    if (act === 'back') {
      const backStep = {
        biz_name: 'role', biz_kind: 'biz_name', biz_cat: 'biz_kind',
        ch_link: 'role', pmode: 'ch_link', tariff: 'pmode',
      }[OB.step];
      if (backStep) OB.step = backStep;
      return render();
    }
    if (act === 'finish') {
      OB.open = false;
      ST.loading = true; render();
      try {
        if (ST.role === 'manager') {
          await Promise.allSettled([loadMyChannels(), loadMgrOrders(), loadMgrTariffs()]);
          ST.page = 'mgr-home';
        } else {
          await Promise.allSettled([loadBusinesses(), loadBanners(), loadOrders()]);
          ST.page = 'home';
        }
      } catch (e) {}
      ST.loading = false;
      return render();
    }
    if (act === 'next') {
      if (OB.step === 'biz_name') {
        const n = document.getElementById('ob-biz-name');
        OB.biz.name = (n && n.value || '').trim();
        if (!OB.biz.name) { OB.error = 'نام کسب‌وکار را وارد کنید.'; return render(); }
        OB.step = 'biz_kind';
        return render();
      }
      if (OB.step === 'biz_kind') {
        const r = document.getElementById('ob-biz-ref');
        OB.biz.source_ref = (r && r.value || '').trim();
        OB.step = 'biz_cat';
        return render();
      }
      if (OB.step === 'biz_cat') {
        if (!(OB.biz.categories || []).length) {
          OB.error = 'دست‌کم یک موضوع انتخاب کنید.';
          return render();
        }
        OB.loading = true; render();
        try {
          const d = await api('/businesses', {
            method: 'POST',
            body: JSON.stringify({
              name: OB.biz.name,
              kind: OB.biz.kind,
              source_ref: OB.biz.source_ref,
              categories: { main: OB.biz.categories, sub: [] },
            }),
          });
          if (!d.ok) throw new Error(d.message || d.error || 'ثبت نشد');
          obMarkDone('advertiser');
          OB.step = 'biz_done';
          await loadBusinesses().catch(() => {});
        } catch (err) {
          OB.error = err.message || 'ثبت انجام نشد. دوباره تلاش کنید.';
        }
        OB.loading = false;
        return render();
      }
      if (OB.step === 'ch_link') {
        const el = document.getElementById('ob-ch-link');
        OB.ch.link = (el && el.value || '').trim();
        if (!OB.ch.link) { OB.ch.error = 'آدرس کانال را بنویسید.'; return render(); }
        OB.ch.loading = true; render();
        try {
          const d = await api('/channels/add', {
            method: 'POST',
            body: JSON.stringify({ link: OB.ch.link, name: '' }),
          });
          if (!d.ok) throw new Error(d.message || d.error || 'ثبت کانال انجام نشد.');
          OB.ch.id = (d.channel && d.channel.id) || d.id || 0;
          OB.ch.name = (d.channel && (d.channel.name || d.channel.title)) || OB.ch.link;
          OB.step = 'pmode';
        } catch (err) {
          OB.ch.error = err.message || 'ثبت کانال انجام نشد. آدرس را بررسی کنید و دوباره تلاش کنید.';
        }
        OB.ch.loading = false;
        return render();
      }
      if (OB.step === 'pmode') {
        if (OB.ch.id) {
          try {
            await api('/publish-mode', {
              method: 'POST',
              body: JSON.stringify({ channel_id: OB.ch.id, publish_mode: OB.pmode }),
            });
          } catch (e) {}
        }
        OB.step = 'tariff';
        return render();
      }
      if (OB.step === 'tariff') {
        const tn = document.getElementById('ob-tar-name');
        const pr = document.getElementById('ob-tar-price');
        OB.tariff.name = (tn && tn.value || '').trim() || (OB.tariff.duration_hours + ' ساعته');
        OB.tariff.price = (pr && pr.value || '').toString().trim();
        const priceNum = parseInt(String(OB.tariff.price).replace(/[^0-9]/g, ''), 10) || 0;
        if (priceNum <= 0) { OB.error = 'مبلغ را به تومان وارد کنید.'; return render(); }
        OB.loading = true; render();
        try {
          const d = await api('/tariffs/add', {
            method: 'POST',
            body: JSON.stringify({
              channel_id: OB.ch.id,
              name: OB.tariff.name,
              duration_hours: OB.tariff.duration_hours,
              price: priceNum,
            }),
          });
          if (!d.ok) throw new Error(d.message || d.error || 'ثبت تعرفه ناموفق');
          obMarkDone('manager');
          OB.step = 'mgr_done';
        } catch (err) {
          OB.error = err.message || 'تعرفه ثبت نشد. دوباره تلاش کنید.';
        }
        OB.loading = false;
        return render();
      }
    }
  }

  function bindOnboardPage() {
    const root = $('#pageContent');
    if (!root) return;
    root.querySelectorAll('[data-ob]').forEach((btn) => {
      btn.onclick = (e) => {
        e.preventDefault();
        const act = btn.getAttribute('data-ob');
        if (act) handleObAction(act);
      };
    });
  }

  function startOnboardingIfNeeded() {
    if (!obNeedShow()) return false;
    OB.open = true;
    OB.step = 'role';
    OB.role = '';
    OB.error = '';
    OB.loading = false;
    OB.ch = { link: '', error: '', loading: false, id: 0, name: '' };
    OB.biz = { name: '', kind: 'bale', source_ref: '', categories: ['سایر'] };
    OB.pmode = 'manual';
    OB.tariff = { name: '۲۴ ساعته', duration_hours: 24, price: '' };
    // فقط اگر کاربر قبلاً در همین حساب نقش را انتخاب کرده و ثبت‌نامش ناتمام است، ادامه بده
    try {
      const chosen = localStorage.getItem(obKey('role_chosen')) === '1';
      const r = localStorage.getItem(obKey('role')) || '';
      if (chosen && r === 'manager' && localStorage.getItem(obKey('manager_onboarded')) !== '1') {
        OB.role = 'manager'; OB.step = 'ch_link'; ST.role = 'manager';
      } else if (chosen && (r === 'advertiser' || r === 'customer') && localStorage.getItem(obKey('customer_onboarded')) !== '1') {
        OB.role = 'advertiser'; OB.step = 'biz_name'; ST.role = 'advertiser';
      }
      // در غیر این صورت همیشه از کارت‌های انتخاب نقش شروع کن
    } catch (e) {}
    ST.page = 'onboard';
    ST.loading = false;
    ST.forceBusinessSetup = false;
    try { render(); } catch (e) { console.error(e); }
    return true;
  }


  async function boot() {
    try {
    const launchView = new URLSearchParams(location.search).get('view');
    if (launchView === 'businesses') ST.page = 'businesses';
    try {
      const saved = localStorage.getItem('lb.theme');
      if (saved) setTheme(saved === 'dark');
    } catch (e) {}
    try { bindGlobal(); } catch (e) { console.error('bindGlobal', e); }
    ST.loading = true;
    try { render(); } catch (e) { console.error('render1', e); }
    try {
      await loadMe();
      if (ST.role === 'manager') { ST.page = 'mgr-home'; await Promise.allSettled([loadMyChannels(), loadMgrOrders(), loadMgrTariffs(), loadWallet()]); }
      else if (ST.role === 'operator') { ST.page = 'op-home'; await Promise.allSettled([loadOpBanners(), loadOpPayouts(), loadOpAssignments(), loadOpSettings(), loadOpTickets()]); }
      else ST.page = launchView === 'businesses' ? 'businesses' : 'home';
      await Promise.allSettled([loadCatalog(), loadBanners(), loadBusinesses({ refreshMetadata: launchView === 'businesses' }), loadOrders(), loadWallet()]);
      // ثبت‌نام اولیه فقط از ویزارد نقش (startOnboardingIfNeeded)
    } catch (e) {
      toast(e.message || 'ورود ناموفق — با ?debug_bale_id=… یا داخل بله باز کنید');
    }
    ST.loading = false;
    try { render(); } catch (e) { console.error('render2', e); }
    try { startOnboardingIfNeeded(); } catch (e) { console.error('onboard', e); }
    } catch (fatal) {
      console.error('boot fatal', fatal);
      try {
        const root = document.getElementById('pageContent');
        if (root) root.innerHTML = '<div class="empty"><strong>خطای بارگذاری</strong><p>' + String(fatal && fatal.message || fatal) + '</p><button class="btn btn-primary" onclick="location.reload()">تلاش دوباره</button></div>';
      } catch (e) {}
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      try { if (typeof loadAll === 'function') loadAll(true); } catch (e) {}
    }
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
