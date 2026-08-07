"""Bale API client implemented against the official Bale Bot API (tapi.bale.ai).

This client uses endpoints documented at https://docs.bale.ai/ (tapi.bale.ai).

Implemented operations:
- send_message(chat_id, text, reply_markup=None, reply_to_message_id=None)
- forward_message(to_chat_id, from_chat_id, message_id)
- get_chat_info(chat_id)
- send_invoice(...)
- set_webhook(url) / delete_webhook() / get_webhook_info()
- get_updates(offset, limit, timeout)  # long-polling
- get_me()

Notes on scheduling:
- The official Bale Bot API does not document a schedule-message endpoint.
- schedule_message() tries a best-effort call and returns error for fallback.

Authentication:
- Token from settings.BALE_BOT_TOKEN (Django) or env BALE_BOT_TOKEN (standalone scripts).
"""
import os
import logging
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)

# Prefer Django settings when available; fall back to environment variables
try:
    from django.conf import settings
    BALE_API_BASE = getattr(settings, 'BALE_API_URL', None) or os.environ.get('BALE_API_URL', 'https://tapi.bale.ai')
    TOKEN = getattr(settings, 'BALE_BOT_TOKEN', None) or os.environ.get('BALE_BOT_TOKEN', '')
except Exception:
    BALE_API_BASE = os.environ.get('BALE_API_URL', 'https://tapi.bale.ai')
    TOKEN = os.environ.get('BALE_BOT_TOKEN', '')

if not TOKEN:
    logger.warning('BALE_BOT_TOKEN is empty; Bale API calls will fail until a token is configured.')


def _bot_url(path: str) -> str:
    """Construct a full bot URL: {base}/bot{token}/{method}"""
    token_segment = f"/bot{TOKEN}" if TOKEN else "/bot"
    return f"{BALE_API_BASE.rstrip('/')}{token_segment}/{path.lstrip('/')}"


def get_me() -> Dict[str, Any]:
    """Verify the bot token and return bot info."""
    url = _bot_url('getMe')
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_me failed')
        return {'error': str(e)}


def get_updates(offset: Optional[int] = None, limit: int = 100, timeout: int = 30) -> Dict[str, Any]:
    """Long-polling getUpdates. Returns the raw API response dict.

    Important: webhook must be deleted first, otherwise getUpdates returns an error.
    """
    url = _bot_url('getUpdates')
    params: Dict[str, Any] = {'timeout': timeout, 'limit': limit}
    if offset is not None:
        params['offset'] = offset
    try:
        # timeout on the HTTP request should be slightly larger than the long-poll timeout
        r = requests.get(url, params=params, timeout=timeout + 10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_updates failed')
        return {'error': str(e), 'ok': False}


def get_webhook_info() -> Dict[str, Any]:
    url = _bot_url('getWebhookInfo')
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_webhook_info failed')
        return {'error': str(e)}


def set_webhook(url: str) -> Dict[str, Any]:
    endpoint = _bot_url('setWebhook')
    try:
        r = requests.post(endpoint, json={'url': url}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('set_webhook failed')
        return {'error': str(e)}


def delete_webhook() -> Dict[str, Any]:
    """Remove webhook so getUpdates (polling) can be used."""
    endpoint = _bot_url('deleteWebhook')
    try:
        r = requests.post(endpoint, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('delete_webhook failed')
        return {'error': str(e)}


def send_message(chat_id: str, text: str, reply_markup: Optional[Dict] = None, reply_to_message_id: Optional[int] = None) -> Dict[str, Any]:
    url = _bot_url('sendMessage')
    payload: Dict[str, Any] = {
        'chat_id': chat_id,
        'text': text,
    }
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup
    if reply_to_message_id is not None:
        payload['reply_to_message_id'] = reply_to_message_id
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('send_message failed')
        return {'error': str(e)}


def forward_message(to_chat_id: str, from_chat_id: str, message_id: int) -> Dict[str, Any]:
    url = _bot_url('forwardMessage')
    payload = {
        'chat_id': to_chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('forward_message failed')
        return {'error': str(e)}


def get_chat_info(chat_id: str) -> Dict[str, Any]:
    url = _bot_url('getChat')
    try:
        r = requests.get(url, params={'chat_id': chat_id}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_chat_info failed')
        return {'error': str(e)}


def send_invoice(
    chat_id: str,
    title: str,
    description: str,
    payload: str,
    provider_token: str,
    prices: List[Dict[str, Any]],
    currency: str = 'IRR',
    start_parameter: str = 'pay',
) -> Dict[str, Any]:
    """Create/send an invoice via Bale Bot API (sendInvoice)."""
    url = _bot_url('sendInvoice')
    body = {
        'chat_id': chat_id,
        'title': title,
        'description': description,
        'payload': payload,
        'provider_token': provider_token,
        'start_parameter': start_parameter,
        'currency': currency,
        'prices': prices,
    }
    try:
        r = requests.post(url, json=body, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('send_invoice failed')
        return {'error': str(e)}


def schedule_message(target_chat_id: str, message_payload: Dict[str, Any], send_at_iso: str) -> Dict[str, Any]:
    """Best-effort schedule; falls back with error if not supported."""
    url = _bot_url('scheduleMessage')
    body = {
        'chat_id': target_chat_id,
        'payload': message_payload,
        'send_at': send_at_iso,
    }
    try:
        r = requests.post(url, json=body, timeout=10)
        if r.status_code == 404:
            return {'error': 'scheduling_not_supported'}
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.info('schedule_message failed or unsupported, returning error for fallback')
        return {'error': str(e)}
