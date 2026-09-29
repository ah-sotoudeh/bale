"""حساب دیباگ و تطبیق شناسهٔ عددی داخل متن کانال."""
from __future__ import annotations

import os
import re


def debug_bale_ids() -> set[str]:
    raw = os.environ.get('DEBUG_BALE_ID', '') or ''
    return {part.strip() for part in raw.split(',') if part.strip()}


def is_debug_user(bale_user_id: str) -> bool:
    uid = str(bale_user_id or '').strip()
    return bool(uid) and uid in debug_bale_ids()


def id_in_text(bale_user_id: str, text: str) -> bool:
    """شناسه باید یک عدد کامل باشد، نه تکه‌ای از عدد بلندتر."""
    uid = str(bale_user_id or '').strip()
    if not uid or not text:
        return False
    return re.search(r'(?<!\d)' + re.escape(uid) + r'(?!\d)', str(text)) is not None
