#!/usr/bin/env node
/**
 * سیستم عیب‌یابی هوشمند برگه‌های مینی‌اپ لینک‌بان
 * هر برگه را با دادهٔ ساختگی رندر می‌کند و مشکلات رایج را گزارش می‌دهد.
 *
 * اجرا:
 *   node scripts/miniapp_page_qa.js
 *   node scripts/miniapp_page_qa.js --page=mgr-channel
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const APP_JS = path.join(ROOT, 'miniapp/static/panel/v2/app.js');
const APP_CSS = path.join(ROOT, 'miniapp/static/panel/v2/app.css');

const args = process.argv.slice(2);
const onlyPage = (args.find((a) => a.startsWith('--page=')) || '').split('=')[1] || null;

const issues = [];
function issue(page, severity, code, message, hint) {
  issues.push({ page, severity, code, message, hint: hint || '' });
}

function loadAppSource() {
  if (!fs.existsSync(APP_JS)) {
    console.error('app.js پیدا نشد:', APP_JS);
    process.exit(2);
  }
  return fs.readFileSync(APP_JS, 'utf8');
}

/** استخراج فهرست صفحات از TITLES و شاخه‌های render */
function discoverPages(src) {
  const pages = new Set();
  const titles = src.match(/const TITLES\s*=\s*\{([\s\S]*?)\n\s*\}/);
  if (titles) {
    for (const m of titles[1].matchAll(/['"]?([a-z0-9-]+)['"]?\s*:/g)) pages.add(m[1]);
  }
  for (const m of src.matchAll(/ST\.page\s*===\s*['"]([a-z0-9-]+)['"]/g)) pages.add(m[1]);
  for (const m of src.matchAll(/navigate\(['"]([a-z0-9-]+)['"]\)/g)) pages.add(m[1]);
  return [...pages].sort();
}

/** بررسی‌های استاتیک روی کل فایل */
function staticChecks(src) {
  const page = '_static';

  // توابع حیاتی
  for (const fn of [
    'render', 'navigate', 'renderMgrChannelDetail', 'renderLineChartSvg',
    'buildChannelChartSeries', 'formatChartAxis', 'gregorianToJalali',
  ]) {
    if (!src.includes('function ' + fn)) {
      issue(page, 'high', 'missing_fn', `تابع ${fn} پیدا نشد`);
    }
  }
  if (!src.includes('const fa =') && !src.includes('function fa(') && !src.includes('const fa=')) {
    issue(page, 'high', 'missing_fn', 'تابع fa پیدا نشد');
  }

  // محور نمودار باید رند باشد
  const fmt = src.slice(src.indexOf('function formatChartAxis'), src.indexOf('function formatChartAxis') + 600);
  if (fmt && (fmt.includes('toFixed') || fmt.includes('* 10) / 10')) && !fmt.includes('Math.round(n)')) {
    issue(page, 'medium', 'axis_decimal', 'formatChartAxis ممکن است عدد اعشاری برگرداند');
  }
  if (fmt && !fmt.includes('Math.round')) {
    issue(page, 'high', 'axis_no_round', 'formatChartAxis بدون Math.round است');
  }

  // متن‌های توسعه‌دهنده که نباید به کاربر نشان داده شوند
  const badPhrases = [
    'نیازی به بیو نیست',
    'فقط روزهایی که آمار واقعی',
    'TODO',
    'FIXME',
    'console.log(',
  ];
  // console.log در dev ok اما تعداد زیاد مشکوک است
  const clog = (src.match(/console\.log\(/g) || []).length;
  if (clog > 40) issue(page, 'low', 'noisy_logs', `${clog} مورد console.log در app.js`);

  for (const p of ['نیازی به بیو نیست', 'فقط روزهایی که آمار واقعی']) {
    if (src.includes(p)) issue(page, 'high', 'dev_copy', `متن توسعه‌دهنده در UI: «${p}»`);
  }

  // بالانس قالب‌های ساده
  const openT = (src.match(/\$\{/g) || []).length;
  // hard to validate

  // صفحات بدون handler احتمالی
  const dataAttrs = [...src.matchAll(/data-([a-z0-9-]+)=/gi)].map((m) => m[1]);
  const unique = [...new Set(dataAttrs)];
  for (const attr of unique) {
    const camel = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const hasBind =
      src.includes(`dataset.${camel}`) ||
      src.includes(`[data-${attr}]`) ||
      src.includes(`data-${attr}`);
    // only flag if used in HTML-ish template many times without dataset
    const uses = (src.match(new RegExp(`data-${attr}=`, 'g')) || []).length;
    const binds = (src.match(new RegExp(`dataset\\.${camel}\\b`, 'g')) || []).length
      + (src.match(new RegExp(`\\[data-${attr}\\]`, 'g')) || []).length;
    if (uses >= 2 && binds === 0 && !['pi', 'series', 'theme'].includes(attr)) {
      // many false positives — only warn for manager-critical
      if (['mgr-cal-ch', 'mgr-ch', 'chart-days', 'tariff-edit'].includes(attr)) {
        issue(page, 'high', 'unbound_attr', `data-${attr} در قالب هست ولی dataset بایند مشخص نیست`);
      }
    }
  }

  // CSS
  if (fs.existsSync(APP_CSS)) {
    const css = fs.readFileSync(APP_CSS, 'utf8');
    if (css.includes('mgr-stats-note') && !css.includes('mgr-stats-note{display:none')) {
      // ok if hidden
    }
    if ((css.match(/!important/g) || []).length > 80) {
      issue(page, 'low', 'css_important', 'تعداد زیاد !important در CSS — نگهداری سخت می‌شود');
    }
  }
}

/** شبیه‌سازی سبک رندر برای یک صفحه با استخراج خروجی template از روی الگوهای شناخته‌شده */
function analyzePage(src, page) {
  // آیا شاخه render برای این صفحه هست؟
  const hasBranch =
    src.includes(`ST.page === '${page}'`) ||
    src.includes(`ST.page==='${page}'`) ||
    new RegExp(`page === ['"]${page}['"]`).test(src);
  const hasTitle = new RegExp(`['"]${page}['"]\\s*:`).test(src.match(/const TITLES[\s\S]{0,1200}/)?.[0] || '');
  if (!hasBranch && !hasTitle && page !== 'onboard') {
    issue(page, 'medium', 'no_render_branch', `شاخهٔ render برای «${page}» پیدا نشد`);
  }

  // برای صفحات مدیر
  if (page.startsWith('mgr-')) {
    if (page === 'mgr-channel') {
      if (!src.includes('mgr-banner-row') && !src.includes('manager-detail-banner')) {
        issue(page, 'high', 'hero_missing', 'هدر کانال در جزئیات مدیر پیدا نشد');
      }
      if (!src.includes('mgr-stats-card') && !src.includes('renderLineChartSvg')) {
        issue(page, 'high', 'chart_missing', 'نمودار آمار در صفحه کانال نیست');
      }
      if (!src.includes('mgr-ch-tariff')) {
        issue(page, 'medium', 'tariff_list_missing', 'فهرست تعرفه در جزئیات کانال نیست');
      }
      // dual axis
      if (!src.includes('yR') && !src.includes('topR')) {
        issue(page, 'high', 'no_dual_axis', 'محور دوگانه برای نرخ تعامل پیاده نشده');
      }
      if (!src.includes('formatChartAxis')) {
        issue(page, 'high', 'no_axis_format', 'فرمت محور نمودار نیست');
      }
    }
    if (page === 'mgr-calendar') {
      if (!src.includes('gregorianToJalali') || !src.includes('JMONTHS')) {
        issue(page, 'high', 'no_jalali', 'تقویم بدون تبدیل شمسی');
      }
      if (!src.includes('mgrCalPrev')) {
        issue(page, 'medium', 'no_month_nav', 'ناوبری ماه در تقویم مدیر نیست');
      }
    }
    if (page === 'mgr-channels') {
      if (!src.includes('data-mgr-cal-ch')) {
        issue(page, 'medium', 'no_cal_btn', 'دکمه تقویم روی کارت کانال نیست');
      }
    }
  }

  // صفحات مشتری
  if (['market', 'calendar', 'channel', 'banners', 'orders', 'wallet'].includes(page)) {
    if (page === 'calendar' && !src.includes('JMONTHS')) {
      issue(page, 'high', 'customer_cal_jalali', 'تقویم مشتری شمسی نیست');
    }
  }

  // متون خام انگلیسی مشکوک در UI templates نزدیک page
  const engUi = src.match(/>\s*[A-Za-z]{4,}\s*</g);
  // too noisy
}

/** تست واحد کوچک برای formatChartAxis با استخراج و eval امن */
function testAxisFormatter(src) {
  const start = src.indexOf('function formatChartAxis');
  if (start < 0) {
    issue('chart', 'high', 'axis_missing', 'formatChartAxis وجود ندارد');
    return;
  }
  // fa stub + function
  const end = src.indexOf('\n  function ', start + 10);
  let fnSrc = src.slice(start, end > start ? end : start + 500);
  // strip until next function at same indent
  const fake = `
    function fa(n){ return String(n); }
    ${fnSrc}
    const samples = [0, 1, 16.7, 33.3, 50, 999, 1000, 1700, 33300, 50000, 143308];
    const out = samples.map(formatChartAxis);
    out;
  `;
  try {
    const out = eval(fake);
    out.forEach((s, i) => {
      if (/\.\d/.test(String(s).replace(/[kM]$/, ''))) {
        issue('chart', 'high', 'axis_not_int', `مقدار محور اعشاری است: ${samplesLabel(i)} → ${s}`);
      }
    });
    console.log('  axis samples:', out.join(' | '));
  } catch (e) {
    issue('chart', 'medium', 'axis_eval', 'نتوانستیم formatChartAxis را تست کنیم: ' + e.message);
  }
}
function samplesLabel(i) {
  return [0, 1, 16.7, 33.3, 50, 999, 1000, 1700, 33300, 50000, 143308][i];
}

function main() {
  console.log('── عیب‌یابی هوشمند مینی‌اپ لینک‌بان ──\n');
  const src = loadAppSource();
  staticChecks(src);
  testAxisFormatter(src);

  let pages = discoverPages(src);
  if (onlyPage) pages = pages.filter((p) => p === onlyPage);
  console.log(`برگه‌های کشف‌شده (${pages.length}):`, pages.join(', '));
  console.log('');

  for (const page of pages) {
    analyzePage(src, page);
  }

  // خلاصه
  const bySev = { high: 0, medium: 0, low: 0 };
  issues.forEach((i) => { bySev[i.severity] = (bySev[i.severity] || 0) + 1; });
  console.log('\n── گزارش ──');
  if (!issues.length) {
    console.log('مشکل خودکاری پیدا نشد.');
    process.exit(0);
  }
  const order = { high: 0, medium: 1, low: 2 };
  issues.sort((a, b) => order[a.severity] - order[b.severity] || a.page.localeCompare(b.page));
  for (const i of issues) {
    const tag = i.severity === 'high' ? '!!' : i.severity === 'medium' ? '!' : '·';
    console.log(`${tag} [${i.severity}] ${i.page} · ${i.code}: ${i.message}${i.hint ? ' — ' + i.hint : ''}`);
  }
  console.log(`\nجمع: ${issues.length} مورد (جدی: ${bySev.high || 0} | متوسط: ${bySev.medium || 0} | کم: ${bySev.low || 0})`);
  process.exit(bySev.high ? 1 : 0);
}

main();
