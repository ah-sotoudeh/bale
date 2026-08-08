"""Extract and normalize Bale channel identifiers from free text."""
from __future__ import annotations

import re
from typing import List

# ble.ir/name  bale.ai/name  @name  https://ble.ir/name
_LINK_RE = re.compile(
    r'(?:https?://)?(?:ble\.ir|bale\.ai)/(?:join/)?([A-Za-z0-9_]+)'
    r'|@([A-Za-z0-9_]+)'
    r'|(?<![\w/])([A-Za-z][A-Za-z0-9_]{3,})(?![\w])',
    re.IGNORECASE,
)


def normalize_channel_ref(raw: str) -> str:
    """Return API-friendly chat id: @username when possible."""
    s = (raw or '').strip()
    if not s:
        return s
    m = _LINK_RE.search(s)
    if m:
        name = next(g for g in m.groups() if g)
        return f'@{name.lstrip("@")}'
    if s.startswith('@'):
        return s
    if s.lstrip('-').isdigit():
        return s  # numeric chat id
    return f'@{s}'


def extract_channel_refs(text: str) -> List[str]:
    """Find unique channel refs in a message (order preserved)."""
    seen = set()
    out: List[str] = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        # whole-line numeric id
        if line.lstrip('-').isdigit():
            ref = line
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
            continue
        for m in _LINK_RE.finditer(line):
            name = next(g for g in m.groups() if g)
            ref = f'@{name.lstrip("@")}'
            key = ref.lower()
            if key not in seen:
                seen.add(key)
                out.append(ref)
    # also scan full text if nothing line-based
    if not out:
        for m in _LINK_RE.finditer(text or ''):
            name = next(g for g in m.groups() if g)
            ref = f'@{name.lstrip("@")}'
            key = ref.lower()
            if key not in seen:
                seen.add(key)
                out.append(ref)
    return out
