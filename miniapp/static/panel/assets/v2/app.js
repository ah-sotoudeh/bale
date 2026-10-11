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
    waiting_customer_confirm: 'منتظر تأیید شما',
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
    page: 'market',
    role: 'customer',
    me: null,
    catalog: null,
    banners: [],
    orders: [],
    wallet: null,
    filter: 'all',
    q: '',
    channelId: null,
    tariffId: null,
    selectedDay: null,
    orderTab: 'all',
    loading: false,
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
    if (initData) headers['X-Bale-Init-Data'] = initData;
    const dbg = debugId();
    if (dbg) headers['X-Bale-User-Id'] = dbg;

    let body = opts.body;
    if (body && !(body instanceof FormData) && typeof body === 'object') {
      headers['Content-Type'] = 'application/json';
      if (dbg && !body.debug_bale_id) body = Object.assign({ debug_bale_id: dbg }, body);
      body = JSON.stringify(body);
    } else if (body instanceof FormData && dbg) {
      body.append('debug_bale_id', dbg);
    }

    let url = path.startsWith('http') ? path : API + path;
    if (method === 'GET' && dbg && !url.includes('debug_bale_id')) {
      url += (url.includes('?') ? '&' : '?') + 'debug_bale_id=' + encodeURIComponent(dbg);
    }

    const res = await fetch(url, { method, headers, body, credentials: 'same-origin' });
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
  };
  function icon(name, size = 20) {
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`;
  }

  function openSheet(html) {
    $('#sheetBody').innerHTML = html;
    $('#sheet').classList.add('on');
  }
  function closeSheet() {
    $('#sheet').classList.remove('on');
  }

  function setTheme(dark) {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    try { localStorage.setItem('lb.theme', dark ? 'dark' : 'light'); } catch (e) {}
  }

  /* ——— Data loaders ——— */
  async function loadMe() {
    const d = await api('/me');
    if (!d.ok) throw new Error(d.message || d.error || 'auth');
    ST.me = d;
    ST.wallet = d.wallet || { available: 0, pending: 0 };
    if (d.is_operator) {
      /* keep role if already set */
    }
    return d;
  }

  async function loadCatalog() {
    const q = ST.q ? '?q=' + encodeURIComponent(ST.q) : '';
    const d = await api('/catalog' + q);
    if (!d.ok) throw new Error(d.message || 'catalog');
    ST.catalog = d;
    return d;
  }

  async function loadBanners() {
    const d = await api('/banners');
    if (!d.ok) { ST.banners = []; return; }
    ST.banners = d.banners || d.items || [];
    return ST.banners;
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
    const d = await api('/calendar?tariff_id=' + encodeURIComponent(tariffId) + '&for=customer');
    if (!d.ok) return [];
    return d.days || [];
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
    if (ST.filter === 'ready') list = list.filter((t) => {
      if (t.channel_id) return ch[t.channel_id]?.ready_publish;
      return true;
    });
    if (ST.filter === 'auto') list = list.filter((t) => {
      const c = ch[t.channel_id];
      return c && (c.publish_mode === 'bot' || c.publish_mode === 'linkyar');
    });
    if (ST.filter === 'manual') list = list.filter((t) => ch[t.channel_id]?.publish_mode === 'manual');
    if (ST.filter === 'pkg') list = list.filter((t) => t.is_package);
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

  function renderMarket() {
    const list = groupByChannel(filteredTariffs());
    const cards = list.length
      ? list.map((g) => {
          const minPrice = Math.min(...g.tariffs.map((t) => t.price));
          const letter = (g.name || '?').charAt(0);
          const av = g.avatar
            ? `<img src="${g.avatar}" alt="" onerror="this.parentNode.textContent='${letter}'"/>`
            : letter;
          return `<article class="card" data-open-ch="${g.key}">
            <div class="card-row">
              <div class="ch-ava">${av}</div>
              <div class="grow">
                <div class="ch-title">${esc(g.name)}</div>
                <div class="ch-sub">${g.link ? '@' + esc(String(g.link).replace(/^@/, '')) : ''}${g.isPkg ? ' · بسته' : ''}</div>
                <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
                  ${g.ready ? '<span class="badge ok">آماده انتشار</span>' : '<span class="badge muted">دستی</span>'}
                  <span class="badge muted">${faK(g.members)} عضو</span>
                </div>
              </div>
              <div style="text-align:left">
                <div class="price">از ${faNum(minPrice)}</div>
                <div class="ch-sub">تومان</div>
              </div>
            </div>
          </article>`;
        }).join('')
      : '<div class="empty">کانالی با این فیلتر پیدا نشد.</div>';

    return `
      <div class="search">${icon('search')}<input id="qInput" placeholder="جستجوی کانال یا موضوع…" value="${esc(ST.q)}"/></div>
      <div class="filters" id="homeFilters">
        ${[['all','همه'],['ready','آماده انتشار'],['auto','خودکار'],['manual','دستی'],['pkg','بسته']].map(([k,l]) =>
          `<button class="chip ${ST.filter===k?'on':''}" data-f="${k}">${l}</button>`).join('')}
      </div>
      <div id="catalog">${cards}</div>`;
  }

  function renderChannel() {
    const groups = groupByChannel(ST.catalog?.tariffs || []);
    const g = groups.find((x) => x.key === ST.channelId) || groups[0];
    if (!g) return '<div class="empty">کانال پیدا نشد</div>';
    const c = g.channel || {};
    const tariffs = g.tariffs.map((t) => `
      <div class="tariff-row ${ST.tariffId===t.id?'on':''}" data-tariff="${t.id}">
        <div class="radio"></div>
        <div class="grow">
          <strong>${esc(t.name || (t.duration_hours + ' ساعته'))}</strong>
          <div class="ch-sub">${fa(t.duration_hours)} ساعت نمایش</div>
        </div>
        <div class="price">${faNum(t.price)} <small>تومان</small></div>
      </div>`).join('');

    return `
      <div class="card" style="text-align:center">
        <div class="ch-ava" style="width:72px;height:72px;margin:0 auto 10px;font-size:1.4rem">${(g.name||'?').charAt(0)}</div>
        <div class="ch-title">${esc(g.name)}</div>
        <div class="ch-sub">${c.link ? '@' + esc(String(c.link).replace(/^@/,'')) : ''}</div>
        <div class="stats">
          <div class="stat"><b>${faK(g.members)}</b><span>عضو</span></div>
          <div class="stat"><b>${faK(g.views)}</b><span>میانگین بازدید</span></div>
          <div class="stat"><b>${c.ready_publish ? '✓' : '—'}</b><span>آماده</span></div>
        </div>
        ${c.publish_mode ? `<div style="margin-top:10px"><span class="badge">${modeLabel(c.publish_mode)}</span></div>` : ''}
      </div>
      <div class="section">تعرفه‌ها</div>
      ${tariffs}
      <button class="btn btn-primary btn-block" id="btnPickTariff" ${ST.tariffId?'':'disabled'}>انتخاب تعرفه و ادامه</button>`;
  }

  function modeLabel(m) {
    return ({ bot: 'ارسال خودکار (ربات)', linkyar: 'ارسال با لینک‌یار', manual: 'انتشار دستی' })[m] || m;
  }

  function renderBanners() {
    const rows = (ST.banners || []).map((b) => {
      const st = b.stage || b.status || (b.approved ? 'approved' : 'pending');
      const badge = st === 'approved' || st === 'ok'
        ? '<span class="badge ok">تأییدشده</span>'
        : st === 'rejected'
        ? '<span class="badge danger">رد شده</span>'
        : '<span class="badge warn">در انتظار</span>';
      const thumb = b.media_url
        ? `<img class="banner-thumb" src="${esc(b.media_url)}" alt=""/>`
        : `<div class="text-banner">متن</div>`;
      return `<div class="card card-row">
        ${thumb}
        <div class="grow">
          <div class="title">${esc(b.title || b.display_title || 'بنر')}</div>
          <div class="sub">${esc((b.caption || '').slice(0, 80))}</div>
          <div style="margin-top:6px">${badge}</div>
        </div>
      </div>`;
    }).join('') || '<div class="empty">هنوز بنری ندارید.</div>';

    return `
      <p class="hint">بنر می‌تواند تصویر، ویدیو یا <strong>فقط متن</strong> باشد. پس از بررسی پشتیبانی تأیید می‌شود.</p>
      <div class="bot-hint">
        <strong>از ربات هم می‌توانید بنر بفرستید:</strong>
        بنر را به بازوی لینک‌بان فوروارد کنید؛ بعد از ثبت، اینجا نمایش داده می‌شود.
      </div>
      <button class="btn btn-primary btn-block" id="btnNewBanner" style="margin-bottom:12px">${icon('plus',16)} بنر جدید</button>
      <div id="bannersList">${rows}</div>`;
  }

  function renderBannerForm() {
    return `
      <div class="sheet-handle"></div>
      <h3 style="margin:0 0 12px;text-align:center">بنر جدید</h3>
      <div class="seg" id="bannerType">
        <button type="button" class="on" data-t="media">تصویر / ویدیو</button>
        <button type="button" data-t="text">فقط متن</button>
      </div>
      <div id="mediaBlock">
        <div class="upload-zone" id="uploadZone">
          <strong>آپلود تصویر یا ویدیو</strong>
          <span>JPG, PNG, MP4 — حداکثر ۱۵ مگابایت</span>
          <input type="file" id="bannerFile" accept="image/*,video/*" hidden/>
        </div>
        <div id="fileName" class="hint"></div>
      </div>
      <div class="field"><label>عنوان (اختیاری)</label><input id="bTitle" maxlength="120" placeholder="مثلاً بنر عطر"/></div>
      <div class="field"><label>متن بنر *</label><textarea id="bCaption" placeholder="حداقل چند خط درباره کالا یا خدمات…"></textarea></div>
      <button class="btn btn-primary btn-block" id="btnSubmitBanner">ثبت بنر</button>
      <p class="hint" style="margin-top:10px">یا بنر را از چت به بازو فوروارد کنید تا خودکار اضافه شود.</p>`;
  }

  /* Jalali helpers (compact) */
  function gregorianToJalali(gy, gm, gd) {
    const g_d_m = [0,31,59,90,120,151,181,212,243,273,304,334];
    let jy = gy <= 1600 ? 0 : 979;
    gy -= gy <= 1600 ? 621 : 1600;
    const gy2 = gm > 2 ? gy + 1 : gy;
    let days = 365 * gy + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100) + Math.floor((gy2 + 399) / 400) - 80 + gd + g_d_m[gm - 1];
    jy += 33 * Math.floor(days / 12053);
    days %= 12053;
    jy += 4 * Math.floor(days / 1461);
    days %= 1461;
    if (days > 365) { jy += Math.floor((days - 1) / 365); days = (days - 1) % 365; }
    const jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
    const jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
    return [jy, jm, jd];
  }
  function jalaliToGregorian(jy, jm, jd) {
    let gy = jy <= 979 ? 621 : 1600;
    jy -= jy <= 979 ? 0 : 979;
    const days = 365 * jy + Math.floor(jy / 33) * 8 + Math.floor(((jy % 33) + 3) / 4) + 78 + jd + (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
    gy += 400 * Math.floor(days / 146097);
    let d = days % 146097;
    if (d > 36524) { gy += 100 * Math.floor(--d / 36524); d %= 36524; if (d >= 365) d++; }
    gy += 4 * Math.floor(d / 1461);
    d %= 1461;
    if (d > 365) { gy += Math.floor((d - 1) / 365); d = (d - 1) % 365; }
    const gd = d + 1;
    const sal_a = [0,31,(gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0 ? 29 : 28,31,30,31,30,31,31,30,31,30,31];
    let gm = 0, v = gd;
    while (gm < 13 && v > sal_a[gm]) { v -= sal_a[gm]; gm++; }
    return [gy, gm, v];
  }
  const JMONTHS = ['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند'];

  function renderCalendar() {
    const t = (ST.catalog?.tariffs || []).find((x) => x.id === ST.tariffId);
    if (!t) return '<div class="empty">تعرفه انتخاب نشده</div>';
    const now = new Date();
    const [jy, jm] = ST.calMonth || gregorianToJalali(now.getFullYear(), now.getMonth() + 1, now.getDate());
    ST.calMonth = [jy, jm];

    const dayMap = {};
    (ST.calDays || []).forEach((x) => { dayMap[x.date] = x; });
    const busySet = new Set(
      (ST.catalog?.busy || []).filter((b) => b.tariff_id === t.id).map((b) => b.date)
    );
    Object.keys(dayMap).forEach((iso) => {
      const st = dayMap[iso].status || (dayMap[iso].free ? 'free' : 'full');
      if (st !== 'free') busySet.add(iso);
    });

    const firstG = jalaliToGregorian(jy, jm, 1);
    const first = new Date(firstG[0], firstG[1] - 1, firstG[2]);
    let startDow = first.getDay(); // 0 Sun
    // convert to Sat=0
    startDow = (startDow + 1) % 7;
    const dim = jm <= 6 ? 31 : jm <= 11 ? 30 : 29;

    let cells = '';
    for (let i = 0; i < startDow; i++) cells += '<div class="cal-day muted"></div>';
    for (let d = 1; d <= dim; d++) {
      const g = jalaliToGregorian(jy, jm, d);
      const iso = `${g[0]}-${String(g[1]).padStart(2,'0')}-${String(g[2]).padStart(2,'0')}`;
      const past = new Date(g[0], g[1]-1, g[2]) < new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const busy = busySet.has(iso);
      const sel = ST.selectedDay === iso;
      let cls = 'cal-day';
      if (past) cls += ' muted';
      else if (busy) cls += ' busy';
      if (sel) cls += ' sel';
      cells += `<button type="button" class="${cls}" data-day="${iso}" ${past||busy?'disabled':''}>${fa(d)}</button>`;
    }

    return `
      <div class="card">
        <div class="ch-title">${esc(t.owner || t.name)}</div>
        <div class="ch-sub">${esc(t.name)} · ${faNum(t.price)} تومان · ${fa(t.duration_hours)} ساعت</div>
      </div>
      <div class="cal-head">
        <button class="icon-btn" id="calPrev">${icon('back')}</button>
        <strong>${JMONTHS[jm-1]} ${fa(jy)}</strong>
        <button class="icon-btn" id="calNext" style="transform:scaleX(-1)">${icon('back')}</button>
      </div>
      <div class="cal-grid">
        ${['ش','ی','د','س','چ','پ','ج'].map((x)=>`<div class="cal-dow">${x}</div>`).join('')}
        ${cells}
      </div>
      <button class="btn btn-primary btn-block" id="btnAddCart" style="margin-top:14px" ${ST.selectedDay?'':'disabled'}>افزودن به سبد و ادامه</button>`;
  }

  function orderStepIndex(status) {
    const i = TIMELINE.findIndex((s) => s.key === status);
    return i < 0 ? 0 : i;
  }

  function renderOrders() {
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
        <div class="timeline">${tl}</div>
        <div class="price">${faNum(o.total || o.price || 0)} تومان</div>
        ${o.status === 'waiting_payment' ? `<button class="btn btn-primary btn-block btn-sm" style="margin-top:10px" data-pay="${o.id||o.order_id}">پرداخت</button>` : ''}
        ${o.status === 'waiting_customer_confirm' ? `<div class="actions"><button class="btn btn-primary btn-sm" data-confirm="${o.id}">قبول زمان</button></div>` : ''}
      </div>`;
    }).join('') : '<div class="empty">سفارشی نیست.</div>';

    return `
      <div class="tabs-line" id="orderTabs">
        <button class="${ST.orderTab==='all'?'on':''}" data-t="all">همه</button>
        <button class="${ST.orderTab==='active'?'on':''}" data-t="active">جاری</button>
        <button class="${ST.orderTab==='done'?'on':''}" data-t="done">تمام‌شده</button>
      </div>
      ${cards}`;
  }

  function renderWallet() {
    const w = ST.wallet || ST.me?.wallet || { available: 0, pending: 0 };
    return `
      <div class="kpi">
        <div class="card"><div class="n">${faNum(w.available)}</div><div class="l">موجودی قابل برداشت</div></div>
        <div class="card"><div class="n">${faNum(w.pending)}</div><div class="l">در انتظار تسویه</div></div>
      </div>
      <button class="btn btn-primary btn-block" id="btnInvoice">دریافت فاکتور شارژ (بله)</button>
      <button class="btn btn-ghost btn-block" id="btnPayout" style="margin-top:8px">درخواست برداشت</button>
      <p class="hint" style="margin-top:12px">پرداخت سفارش‌ها از کیف پول یا فاکتور بله انجام می‌شود.</p>`;
  }

  function renderSettings() {
    const u = ST.me?.user || {};
    return `
      <div class="card card-row" style="align-items:center">
        <div class="avatar" style="width:56px;height:56px">${(u.handle||u.username||'ل').charAt(0)}</div>
        <div>
          <div class="ch-title">${esc(u.handle || u.username || 'کاربر')}</div>
          <div class="ch-sub">شناسه ${fa(u.bale_user_id || '')}</div>
        </div>
      </div>
      <div class="section">نقش</div>
      <div class="role-grid">
        <div class="role-card ${ST.role==='customer'?'on':''}" data-r="customer"><b>مشتری</b><span>سفارش تبلیغ</span></div>
        <div class="role-card ${ST.role==='manager'?'on':''}" data-r="manager"><b>مدیر کانال</b><span>تعرفه و انتشار</span></div>
        ${ST.me?.is_operator ? `<div class="role-card ${ST.role==='operator'?'on':''}" data-r="operator"><b>پشتیبان</b><span>تأیید و تسویه</span></div>` : ''}
      </div>
      <div class="section">تنظیمات</div>
      <div class="card">
        <div class="list-item"><div class="grow"><div class="title">تم تیره / روشن</div></div>
          <button class="btn btn-sm btn-ghost" id="btnTheme2">تغییر</button></div>
      </div>`;
  }

  function renderManager() {
    return `<div class="empty">
      <div class="illu">📢</div>
      <p>پنل مدیر از API کانال‌ها و درخواست‌ها تغذیه می‌شود.</p>
      <button class="btn btn-primary" id="btnMgrRefresh">بارگذاری کانال‌های من</button>
      <div id="mgrBody" style="margin-top:16px;text-align:right"></div>
    </div>`;
  }

  const TITLES = {
    market: 'بازار تبلیغات',
    channel: 'جزئیات کانال',
    calendar: 'انتخاب روز',
    banners: 'بنرهای من',
    orders: 'سفارش‌ها',
    wallet: 'کیف پول',
    settings: 'حساب',
    manager: 'پنل مدیر',
    operator: 'پشتیبانی',
  };

  function navItems() {
    if (ST.role === 'manager') {
      return [
        { id: 'manager', label: 'کانال‌ها', icon: 'megaphone' },
        { id: 'orders', label: 'سفارش‌ها', icon: 'orders' },
        { id: 'wallet', label: 'کیف پول', icon: 'wallet' },
        { id: 'settings', label: 'حساب', icon: 'user' },
      ];
    }
    if (ST.role === 'operator') {
      return [
        { id: 'operator', label: 'صف‌ها', icon: 'orders' },
        { id: 'settings', label: 'حساب', icon: 'user' },
      ];
    }
    return [
      { id: 'market', label: 'بازار', icon: 'home' },
      { id: 'orders', label: 'سفارش‌ها', icon: 'orders' },
      { id: 'banners', label: 'بنرها', icon: 'image' },
      { id: 'wallet', label: 'کیف پول', icon: 'wallet' },
      { id: 'settings', label: 'حساب', icon: 'user' },
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
    const back = !['market','orders','banners','wallet','settings','manager','operator'].includes(ST.page);
    $('#pageTitle').textContent = TITLES[ST.page] || 'لینک‌بان';
    $('#btnBack').style.display = back ? '' : 'none';
    $('#headerEl').classList.toggle('brand', ST.page === 'market' && ST.role === 'customer');

    let html = '';
    if (ST.loading) html = '<div class="loading">در حال بارگذاری…</div>';
    else if (ST.page === 'market') html = renderMarket();
    else if (ST.page === 'channel') html = renderChannel();
    else if (ST.page === 'calendar') html = renderCalendar();
    else if (ST.page === 'banners') html = renderBanners();
    else if (ST.page === 'orders') html = renderOrders();
    else if (ST.page === 'wallet') html = renderWallet();
    else if (ST.page === 'settings') html = renderSettings();
    else if (ST.page === 'manager') html = renderManager();
    else if (ST.page === 'operator') html = '<div class="empty">صف تأیید بنر و برداشت از API اپراتور</div>';
    else html = renderMarket();

    root.innerHTML = html;
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

  function bindPage() {
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
      openSheet(renderBannerForm());
      bindBannerForm();
    };

    $$('#orderTabs button').forEach((b) => b.onclick = () => {
      ST.orderTab = b.dataset.t; render();
    });
    $$('[data-pay]').forEach((b) => b.onclick = () => payOrder(b.dataset.pay));

    $$('[data-r]').forEach((el) => el.onclick = () => {
      ST.role = el.dataset.r;
      ST.page = el.dataset.r === 'manager' ? 'manager' : el.dataset.r === 'operator' ? 'operator' : 'market';
      render();
    });
    const th2 = $('#btnTheme2');
    if (th2) th2.onclick = () => {
      const dark = document.documentElement.dataset.theme !== 'dark';
      setTheme(dark);
    };

    const inv = $('#btnInvoice');
    if (inv) inv.onclick = async () => {
      const d = await api('/pay/invoice', { method: 'POST', body: { amount: 100000 } });
      toast(d.message || (d.ok ? 'فاکتور ارسال شد' : (d.error || 'خطا')));
    };

    const mgr = $('#btnMgrRefresh');
    if (mgr) mgr.onclick = async () => {
      const d = await api('/channels');
      const el = $('#mgrBody');
      if (!el) return;
      if (!d.ok) { el.innerHTML = '<p class="hint">' + esc(d.message || d.error) + '</p>'; return; }
      const chs = d.channels || d.items || [];
      el.innerHTML = chs.length
        ? chs.map((c) => `<div class="card"><strong>${esc(c.name)}</strong><div class="ch-sub">${faK(c.members_count)} عضو</div></div>`).join('')
        : '<p class="hint">کانالی ثبت نشده. از بازو کانال اضافه کنید.</p>';
    };
  }

  function bindBannerForm() {
    let mode = 'media';
    let file = null;
    $$('#bannerType button').forEach((b) => b.onclick = () => {
      mode = b.dataset.t;
      $$('#bannerType button').forEach((x) => x.classList.toggle('on', x === b));
      $('#mediaBlock').style.display = mode === 'media' ? '' : 'none';
    });
    const zone = $('#uploadZone');
    const input = $('#bannerFile');
    if (zone && input) {
      zone.onclick = () => input.click();
      input.onchange = () => {
        file = input.files && input.files[0];
        $('#fileName').textContent = file ? file.name : '';
      };
    }
    $('#btnSubmitBanner').onclick = async () => {
      const title = $('#bTitle').value.trim();
      const caption = $('#bCaption').value.trim();
      if (caption.length < 12) { toast('متن بنر کوتاه است'); return; }
      const btn = $('#btnSubmitBanner');
      btn.disabled = true;
      try {
        let d;
        if (mode === 'text') {
          d = await api('/banners/create', {
            method: 'POST',
            body: { title, caption, media_kind: 'text', text_only: true },
          });
        } else {
          if (!file) { toast('تصویر یا ویدیو را انتخاب کنید'); btn.disabled = false; return; }
          const fd = new FormData();
          fd.append('title', title);
          fd.append('caption', caption);
          fd.append('file', file);
          d = await api('/banners/create', { method: 'POST', body: fd });
        }
        if (d.ok) {
          toast('بنر ثبت شد و برای بررسی ارسال شد');
          closeSheet();
          await loadBanners();
          render();
        } else {
          toast(d.message || d.error || 'خطا');
        }
      } catch (e) {
        toast('خطای شبکه');
      }
      btn.disabled = false;
    };
  }

  async function addToCart() {
    if (!ST.tariffId || !ST.selectedDay) return;
    const approved = (ST.banners || []).find((b) => {
      const s = b.stage || b.status;
      return s === 'approved' || s === 'ok' || b.approved;
    });
    openSheet(`
      <div class="sheet-handle"></div>
      <h3 style="margin:0 0 12px;text-align:center">تأیید سبد</h3>
      <p class="hint">روز ${esc(ST.selectedDay)} · تعرفه #${fa(ST.tariffId)}</p>
      <div class="field"><label>بنر تأییدشده</label>
        <select id="cartBanner">
          ${(ST.banners||[]).map((b)=>`<option value="${b.id}">${esc(b.title||('بنر '+b.id))}</option>`).join('') || '<option value="">— بنر ثبت کنید —</option>'}
        </select>
      </div>
      <button class="btn btn-primary btn-block" id="btnConfirmCart">ثبت در سبد و ارسال</button>
    `);
    $('#btnConfirmCart').onclick = async () => {
      const bannerId = Number($('#cartBanner').value) || 0;
      const body = { tariff_id: ST.tariffId, date: ST.selectedDay };
      if (bannerId) body.banner_id = bannerId;
      let d = await api('/cart/add', { method: 'POST', body });
      if (!d.ok) {
        d = await api('/cart/add', { method: 'POST', body: Object.assign({}, body, { day: ST.selectedDay }) });
      }
      if (d.ok) {
        if (bannerId) await api('/cart/banner', { method: 'POST', body: { banner_id: bannerId } });
        const chk = await api('/checkout', { method: 'POST', body: {} });
        toast(chk.ok ? 'درخواست برای مدیر ارسال شد' : (d.message || 'به سبد اضافه شد'));
        closeSheet();
        await loadOrders();
        navigate('orders');
      } else {
        toast(d.message || d.error || 'خطا در سبد');
      }
    };
  }

  async function payOrder(id) {
    const d = await api('/pay/invoice', { method: 'POST', body: { order_id: Number(id) } });
    toast(d.message || (d.ok ? 'فاکتور ارسال شد' : (d.error || 'خطا')));
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function bindGlobal() {
    $('#btnBack').onclick = () => {
      if (ST.page === 'calendar') navigate('channel');
      else if (ST.page === 'channel') navigate('market');
      else navigate('market');
    };
    $('#btnTheme').onclick = () => {
      setTheme(document.documentElement.dataset.theme !== 'dark');
    };
    $('#btnProfile').onclick = () => navigate('settings');
    $('#sheet').onclick = (e) => { if (e.target.id === 'sheet') closeSheet(); };
    $('#bottomNav').onclick = async (e) => {
      const btn = e.target.closest('[data-nav]');
      if (!btn) return;
      const id = btn.dataset.nav;
      ST.loading = true; render();
      try {
        if (id === 'market') await ensureCatalog();
        if (id === 'banners') await loadBanners();
        if (id === 'orders') await loadOrders();
        if (id === 'wallet') await loadWallet();
      } catch (err) { toast(err.message || 'خطا'); }
      ST.loading = false;
      navigate(id);
    };
  }

  async function boot() {
    try {
      const saved = localStorage.getItem('lb.theme');
      if (saved) setTheme(saved === 'dark');
    } catch (e) {}
    bindGlobal();
    ST.loading = true; render();
    try {
      await loadMe();
      await loadCatalog();
      await loadBanners();
    } catch (e) {
      toast(e.message || 'ورود ناموفق — با ?debug_bale_id=… یا داخل بله باز کنید');
    }
    ST.loading = false;
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
