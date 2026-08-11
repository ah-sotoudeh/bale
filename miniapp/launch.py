"""Build web_app keyboard for manager mini-app."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from django.conf import settings

from integrations import bale_client as bc


def manager_miniapp_url() -> str:
    base = (
        getattr(settings, 'MINIAPP_BASE_URL', '')
        or os.environ.get('MINIAPP_BASE_URL', '')
    ).rstrip('/')
    path = getattr(settings, 'MINIAPP_MANAGER_PATH', '/miniapp/manager/')
    if not base:
        return ''
    if not path.startswith('/'):
        path = '/' + path
    return base + path


def open_miniapp_keyboard(label: str = '🎛️ پنل مدیر (مینی‌اپ)') -> Optional[Dict[str, Any]]:
    url = manager_miniapp_url()
    if not url:
        return None
    return bc.inline_keyboard([
        [{'text': label[:64], 'web_app': {'url': url}}],
        [{'text': 'منوی متنی', 'callback_data': 'mgr:home'}],
    ])


def send_miniapp_entry(chat_id: str, text: str = 'پنل مدیریت کانال:') -> Dict[str, Any]:
    kb = open_miniapp_keyboard()
    if not kb:
        return bc.send_message(
            str(chat_id),
            text + '\n\n⚠️ MINIAPP_BASE_URL تنظیم نشده. از /panel متنی استفاده کنید.',
        )
    return bc.send_message(str(chat_id), text, reply_markup=kb)
