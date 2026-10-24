#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""عیب‌یابی هوشمند برگه‌های مینی‌اپ لینک‌بان (بدون Node).

اجرا:
  python scripts/miniapp_page_qa.py
  python scripts/miniapp_page_qa.py --page=mgr-channel
  python scripts/miniapp_page_qa.py --out=qa-report.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "miniapp/static/panel/v2/app.js"
APP_CSS = ROOT / "miniapp/static/panel/v2/app.css"


class Issue:
    def __init__(self, page, severity, code, message, hint=""):
        self.page = page
        self.severity = severity
        self.code = code
        self.message = message
        self.hint = hint


def discover_pages(src):
    pages = set()
    m = re.search(r"const TITLES\s*=\s*\{([\s\S]*?)\n\s*\}", src)
    if m:
        for x in re.finditer(r"['\"]?([a-z0-9-]+)['\"]?\s*:", m.group(1)):
            pages.add(x.group(1))
    for x in re.finditer(r"ST\.page\s*===\s*['\"]([a-z0-9-]+)['\"]", src):
        pages.add(x.group(1))
    for x in re.finditer(r"navigate\(['\"]([a-z0-9-]+)['\"]\)", src):
        pages.add(x.group(1))
    return sorted(pages)


def static_checks(src, issues):
    page = "_static"
    for fn in (
        "render",
        "navigate",
        "renderMgrChannelDetail",
        "renderLineChartSvg",
        "buildChannelChartSeries",
        "formatChartAxis",
        "gregorianToJalali",
    ):
        if f"function {fn}" not in src:
            issues.append(Issue(page, "high", "missing_fn", "تابع %s پیدا نشد" % fn))
    if "const fa =" not in src and "function fa(" not in src and "const fa=" not in src:
        issues.append(Issue(page, "high", "missing_fn", "تابع fa پیدا نشد"))
    for phrase in ("نیازی به بیو نیست", "فقط روزهایی که آمار واقعی"):
        if phrase in src:
            issues.append(Issue(page, "high", "dev_copy", "متن توسعه‌دهنده در UI: «%s»" % phrase))
    if src.count("console.log(") > 40:
        issues.append(Issue(page, "low", "noisy_logs", "%d مورد console.log" % src.count("console.log(")))
    if APP_CSS.exists():
        css = APP_CSS.read_text(encoding="utf-8", errors="ignore")
        if css.count("!important") > 80:
            issues.append(Issue(page, "low", "css_important", "تعداد زیاد !important در CSS"))


def analyze_page(src, page, issues):
    has_branch = ("ST.page === '%s'" % page) in src or ('ST.page === "%s"' % page) in src
    titles_blob = re.search(r"const TITLES[\s\S]{0,1500}", src)
    has_title = bool(titles_blob and re.search(r"['\"]%s['\"]\s*:" % re.escape(page), titles_blob.group(0)))
    if not has_branch and not has_title and page != "onboard":
        issues.append(Issue(page, "medium", "no_render_branch", "شاخهٔ render برای «%s» پیدا نشد" % page))

    if page == "mgr-channel":
        if "mgr-banner-row" not in src and "manager-detail-banner" not in src:
            issues.append(Issue(page, "high", "hero_missing", "هدر کانال در جزئیات مدیر پیدا نشد"))
        if "mgr-stats-card" not in src and "renderLineChartSvg" not in src:
            issues.append(Issue(page, "high", "chart_missing", "نمودار آمار در صفحه کانال نیست"))
        if "mgr-ch-tariff" not in src:
            issues.append(Issue(page, "medium", "tariff_list_missing", "فهرست تعرفه در جزئیات کانال نیست"))
        if "topR" not in src and "yR" not in src:
            issues.append(Issue(page, "high", "no_dual_axis", "محور دوگانه برای نرخ تعامل پیاده نشده"))
    if page == "mgr-calendar":
        if "gregorianToJalali" not in src or "JMONTHS" not in src:
            issues.append(Issue(page, "high", "no_jalali", "تقویم بدون تبدیل شمسی"))
        if "mgrCalPrev" not in src:
            issues.append(Issue(page, "medium", "no_month_nav", "ناوبری ماه در تقویم مدیر نیست"))
    if page == "mgr-channels" and "data-mgr-cal-ch" not in src:
        issues.append(Issue(page, "medium", "no_cal_btn", "دکمه تقویم روی کارت کانال نیست"))
    if page == "calendar" and "JMONTHS" not in src:
        issues.append(Issue(page, "high", "customer_cal_jalali", "تقویم مشتری شمسی نیست"))


def format_chart_axis_py(n):
    n = float(n or 0)
    absn = abs(n)
    if absn >= 1000000:
        return str(int(round(n / 1000000))) + "M"
    if absn >= 1000:
        return str(int(round(n / 1000))) + "k"
    return str(int(round(n)))


def test_axis_formatter(src, issues):
    if "function formatChartAxis" not in src:
        issues.append(Issue("chart", "high", "axis_missing", "formatChartAxis وجود ندارد"))
        return []
    samples = [0, 1, 16.7, 33.3, 50, 999, 1000, 1700, 33300, 50000, 143308]
    out = [format_chart_axis_py(s) for s in samples]
    # اگر در سورس هنوز toFixed برای اعداد کوچک باشد هشدار
    start = src.find("function formatChartAxis")
    chunk = src[start : start + 500]
    if "toFixed" in chunk or "* 10) / 10" in chunk:
        issues.append(Issue("chart", "medium", "axis_may_decimal", "احتمال عدد اعشاری در formatChartAxis"))
    for i, s in enumerate(out):
        core = re.sub(r"[kM]$", "", str(s))
        if re.search(r"\.\d", core):
            issues.append(Issue("chart", "high", "axis_not_int", "مقدار محور اعشاری: %s → %s" % (samples[i], s)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    lines = []

    def log(s=""):
        lines.append(s)
        print(s)

    log("── عیب‌یابی هوشمند مینی‌اپ لینک‌بان ──")
    log()
    if not APP_JS.exists():
        log("خطا: app.js پیدا نشد: %s" % APP_JS)
        return 2
    src = APP_JS.read_text(encoding="utf-8", errors="ignore")
    issues = []
    static_checks(src, issues)
    axis_out = test_axis_formatter(src, issues)
    if axis_out:
        log("  axis samples: " + " | ".join(axis_out))

    pages = discover_pages(src)
    if args.page:
        pages = [p for p in pages if p == args.page]
    log("برگه‌های کشف‌شده (%d): %s" % (len(pages), ", ".join(pages)))
    log()
    for page in pages:
        analyze_page(src, page, issues)

    log()
    log("── گزارش ──")
    if not issues:
        log("مشکل خودکاری پیدا نشد.")
    else:
        order = {"high": 0, "medium": 1, "low": 2}
        issues.sort(key=lambda i: (order.get(i.severity, 9), i.page, i.code))
        by = {"high": 0, "medium": 0, "low": 0}
        for i in issues:
            by[i.severity] = by.get(i.severity, 0) + 1
            tag = "!!" if i.severity == "high" else ("!" if i.severity == "medium" else "·")
            log("%s [%s] %s · %s: %s" % (tag, i.severity, i.page, i.code, i.message))
        log()
        log("جمع: %d مورد (جدی: %d | متوسط: %d | کم: %d)" % (
            len(issues), by.get("high", 0), by.get("medium", 0), by.get("low", 0)))

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        log()
        log("گزارش ذخیره شد: %s" % args.out)

    return 1 if any(i.severity == "high" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
