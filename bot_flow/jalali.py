"""Gregorian → Jalali (Shamsi) without external deps."""
from __future__ import annotations

from datetime import date
from typing import Tuple

WEEKDAY_FA = [
    'دوشنبه',
    'سه‌شنبه',
    'چهارشنبه',
    'پنجشنبه',
    'جمعه',
    'شنبه',
    'یکشنبه',
]


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def to_jalali(d: date) -> Tuple[int, int, int]:
    return gregorian_to_jalali(d.year, d.month, d.day)


def format_jalali(d: date) -> str:
    """e.g. شنبه ۱۴۰۵/۰۵/۱۷"""
    jy, jm, jd = to_jalali(d)
    weekday = WEEKDAY_FA[d.weekday()]
    # Arabic-Indic digits optional; keep Western digits for readability in bots
    return f'{weekday} {jy}/{jm:02d}/{jd:02d}'
