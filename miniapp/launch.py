"""Build web_app keyboard for mini-app (all roles)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from django.conf import settings

from integrations import bale_client as bc


def miniapp_url(path: str | None = None) -> str:
    base = (
        getattr(settings, 'MINIAPP_BASE_URL', '')
        or os.environ.get('MINIAPP_BASE_URL', '')
    ).rstrip('/')
    if not base:
        return ''
    path = path or getattr(settings, 'MINIAPP_PATH', '/miniapp/')
    if not path.startswith('/'):
        path = '/' + path
    return base + path


def manager_miniapp_url() -> str:
    return miniapp_url(getattr(settings, 'MINIAPP_MANAGER_PATH', '/miniapp/'))


def open_miniapp_keyboard(label: str = 'دفتر کار لینک‌بانک') -> Optional[Dict[str, Any]]:
    url = manager_miniapp_url()
    if not url:
        return None
    return bc.inline_keyboard([
        [{'text': label[:64], 'web_app': {'url': url}}],
        [{'text': 'منوی متنی', 'callback_data': 'home'}],
    ])


def send_miniapp_entry(chat_id: str, text: str = 'دفتر کار لینک‌بانک:') -> Dict[str, Any]:
    kb = open_miniapp_keyboard()
    if not kb:
        return bc.send_message(
            str(chat_id),
            text + '\n\nاز منوی متنی استفاده کنید.',
        )
    return bc.send_message(str(chat_id), text, reply_markup=kb)
