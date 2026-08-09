"""Banned-word filter for ad banners (caption/text only)."""
from __future__ import annotations

import os
import re
from typing import List, Tuple

# Default list — override with BANNED_WORDS env (comma-separated)
_DEFAULT = [
    'قمار',
    'شرط بندی',
    'شرط‌بندی',
    'کازینو',
    'پورن',
    'porn',
    'سکس',
    'مواد مخدر',
    'کوکائین',
    'هروئین',
    'شیشه',
    'کریپتو کلاهبرداری',
    'پامپ',
    'اسکم',
    'scam',
]


def banned_list() -> List[str]:
    env = os.environ.get('BANNED_WORDS', '').strip()
    if env:
        return [w.strip() for w in env.split(',') if w.strip()]
    return list(_DEFAULT)


def find_banned(text: str) -> List[str]:
    if not text:
        return []
    found = []
    lower = text.lower()
    for w in banned_list():
        if w.lower() in lower:
            found.append(w)
    return found


def is_allowed(text: str) -> Tuple[bool, List[str]]:
    hits = find_banned(text)
    return (len(hits) == 0, hits)
