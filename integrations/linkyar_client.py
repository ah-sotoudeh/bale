"""Bale Bot API client for Link Yar (channel post / delete / admin check).

Uses LINKYAR_BOT_TOKEN if set, otherwise falls back to BALE_BOT_TOKEN.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ROOT / '.env', override=False)
    load_dotenv(_ROOT / 'config' / '.env', override=False)


_load_dotenv()


def _django_setting(name: str, default: str = '') -> str:
    try:
        from django.conf import settings

        if settings.configured:
            val = getattr(settings, name, None)
            if val:
                return str(val)
    except Exception:
        pass
    return default


def linkyar_token() -> str:
    return (
        _django_setting('LINKYAR_BOT_TOKEN')
        or os.environ.get('LINKYAR_BOT_TOKEN', '')
        or _django_setting('BALE_BOT_TOKEN')
        or os.environ.get('BALE_BOT_TOKEN', '')
    )


def linkyar_username() -> str:
    u = (
        _django_setting('LINKYAR_USERNAME')
        or os.environ.get('LINKYAR_USERNAME', '@linkyar')
    )
    u = u.strip()
    if u and not u.startswith('@'):
        u = '@' + u
    return u or '@linkyar'


def _api_base() -> str:
    return (
        _django_setting('BALE_API_URL')
        or os.environ.get('BALE_API_URL', '')
        or 'https://tapi.bale.ai'
    )


def _url(method: str) -> str:
    token = linkyar_token()
    return f"{_api_base().rstrip('/')}/bot{token}/{method.lstrip('/')}"


def get_me() -> Dict[str, Any]:
    try:
        r = requests.get(_url('getMe'), timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('linkyar get_me failed')
        return {'error': str(e)}


def bot_user_id() -> Optional[str]:
    me = get_me()
    if me.get('error'):
        return None
    result = me.get('result') or me
    bid = result.get('id')
    return str(bid) if bid else None


def get_chat_member(chat_id: str, user_id: str) -> Dict[str, Any]:
    try:
        r = requests.get(
            _url('getChatMember'),
            params={'chat_id': chat_id, 'user_id': user_id},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {'error': str(e)}


def is_admin_of_channel(channel_ref: str) -> bool:
    """channel_ref: @username or numeric id."""
    bid = bot_user_id()
    if not bid:
        return False
    member = get_chat_member(str(channel_ref), bid)
    if member.get('error') or not member.get('ok', True):
        logger.info('is_admin_of_channel failed %s: %s', channel_ref, member)
        return False
    status = (member.get('result') or {}).get('status') or ''
    return status in ('administrator', 'creator')


def send_message(chat_id: str, text: str, **kwargs) -> Dict[str, Any]:
    payload: Dict[str, Any] = {'chat_id': chat_id, 'text': text}
    payload.update({k: v for k, v in kwargs.items() if v is not None})
    try:
        r = requests.post(_url('sendMessage'), json=payload, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('linkyar send_message failed')
        return {'error': str(e)}


def forward_message(to_chat_id: str, from_chat_id: str, message_id: int) -> Dict[str, Any]:
    payload = {
        'chat_id': to_chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id,
    }
    try:
        r = requests.post(_url('forwardMessage'), json=payload, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('linkyar forward_message failed')
        return {'error': str(e)}


def copy_message(
    to_chat_id: str,
    from_chat_id: str,
    message_id: int,
    caption: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        'chat_id': to_chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id,
    }
    if caption is not None:
        payload['caption'] = caption
    try:
        r = requests.post(_url('copyMessage'), json=payload, timeout=20)
        if r.status_code == 404:
            # fallback: forward
            return forward_message(to_chat_id, from_chat_id, message_id)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.info('copy_message failed, try forward: %s', e)
        return forward_message(to_chat_id, from_chat_id, message_id)


def delete_message(chat_id: str, message_id: int) -> Dict[str, Any]:
    try:
        r = requests.post(
            _url('deleteMessage'),
            json={'chat_id': chat_id, 'message_id': message_id},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('linkyar delete_message failed')
        return {'error': str(e)}


def send_photo(
    chat_id: str,
    photo: str,
    caption: str = '',
) -> Dict[str, Any]:
    """photo: file_id or URL if supported."""
    payload: Dict[str, Any] = {'chat_id': chat_id, 'photo': photo}
    if caption:
        payload['caption'] = caption[:1024]
    try:
        r = requests.post(_url('sendPhoto'), json=payload, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {'error': str(e)}
