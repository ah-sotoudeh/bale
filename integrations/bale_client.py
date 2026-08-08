"""Bale API client implemented against the official Bale Bot API (tapi.bale.ai).

Supports InlineKeyboardMarkup via reply_markup on sendMessage, and answerCallbackQuery.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_warned_empty_token = False


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


def _token() -> str:
    return _django_setting('BALE_BOT_TOKEN') or os.environ.get('BALE_BOT_TOKEN', '')


def _card_number() -> str:
    return _django_setting('BALE_CARD_NUMBER') or os.environ.get('BALE_CARD_NUMBER', '')


def _api_base() -> str:
    return (
        _django_setting('BALE_API_URL')
        or os.environ.get('BALE_API_URL', '')
        or 'https://tapi.bale.ai'
    )


TOKEN = _token()
CARD_NUMBER = _card_number()
BALE_API_BASE = _api_base()


def _bot_url(path: str) -> str:
    token = _token()
    global _warned_empty_token
    if not token and not _warned_empty_token:
        logger.warning(
            'BALE_BOT_TOKEN is empty. Set it in .env or the environment. '
            '(GitHub Secrets only work inside Actions.)'
        )
        _warned_empty_token = True
    token_segment = f'/bot{token}' if token else '/bot'
    return f"{_api_base().rstrip('/')}{token_segment}/{path.lstrip('/')}"


def inline_keyboard(rows: Sequence[Sequence[Dict[str, str]]]) -> Dict[str, Any]:
    """Build Telegram/Bale-style InlineKeyboardMarkup.

    Each button dict needs 'text' and either 'callback_data' or 'url'.
    callback_data should stay under 64 bytes.
    """
    return {'inline_keyboard': [list(row) for row in rows]}


def manager_decision_keyboard(item_id: int) -> Dict[str, Any]:
    return inline_keyboard([
        [
            {'text': '✅ تأیید', 'callback_data': f'approve:{item_id}'},
            {'text': '❌ رد', 'callback_data': f'reject:{item_id}'},
        ]
    ])


def payment_done_keyboard(order_id: int) -> Dict[str, Any]:
    return inline_keyboard([
        [{'text': '💳 پرداخت انجام شد (تست)', 'callback_data': f'paid:{order_id}'}]
    ])


def get_me() -> Dict[str, Any]:
    url = _bot_url('getMe')
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_me failed')
        return {'error': str(e)}


def get_updates(offset: Optional[int] = None, limit: int = 100, timeout: int = 30) -> Dict[str, Any]:
    url = _bot_url('getUpdates')
    params: Dict[str, Any] = {'timeout': timeout, 'limit': limit}
    if offset is not None:
        params['offset'] = offset
    try:
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
    endpoint = _bot_url('deleteWebhook')
    try:
        r = requests.post(endpoint, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('delete_webhook failed')
        return {'error': str(e)}


def answer_callback_query(
    callback_query_id: str,
    text: Optional[str] = None,
    show_alert: bool = False,
) -> Dict[str, Any]:
    """Stop the loading spinner on an inline button; optional toast/alert."""
    url = _bot_url('answerCallbackQuery')
    body: Dict[str, Any] = {'callback_query_id': callback_query_id}
    if text is not None:
        body['text'] = text[:200]
    if show_alert:
        body['show_alert'] = True
    try:
        r = requests.post(url, json=body, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('answer_callback_query failed')
        return {'error': str(e)}


def send_message(
    chat_id: str,
    text: str,
    reply_markup: Optional[Dict] = None,
    reply_to_message_id: Optional[int] = None,
) -> Dict[str, Any]:
    url = _bot_url('sendMessage')
    payload: Dict[str, Any] = {'chat_id': chat_id, 'text': text}
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


def get_channel_info(channel_link: str) -> Dict[str, Any]:
    raw = get_chat_info(channel_link)
    if raw.get('error'):
        return raw
    if not raw.get('ok', True):
        return {'error': raw.get('description') or 'getChat failed', 'raw': raw}

    result = raw.get('result') or raw
    return {
        'id': result.get('id'),
        'title': result.get('title') or result.get('first_name') or '(no title)',
        'username': result.get('username'),
        'type': result.get('type'),
        'bio': result.get('bio') or result.get('description') or '',
        'description': result.get('description') or result.get('bio') or '',
        'invite_link': result.get('invite_link'),
        'raw': result,
    }


def get_chat_member(chat_id: str, user_id: str) -> Dict[str, Any]:
    url = _bot_url('getChatMember')
    try:
        r = requests.get(url, params={'chat_id': chat_id, 'user_id': user_id}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_chat_member failed')
        return {'error': str(e)}


def bot_is_channel_admin(channel_id: str) -> bool:
    me = get_me()
    bot_id = None
    if me.get('ok') or 'result' in me:
        bot_id = (me.get('result') or {}).get('id')
    if not bot_id:
        bot_id = me.get('id')
    if not bot_id:
        logger.warning('bot_is_channel_admin: cannot resolve bot id from getMe: %s', me)
        return False

    member = get_chat_member(str(channel_id), str(bot_id))
    if member.get('error') or not member.get('ok', True):
        logger.info('bot_is_channel_admin: getChatMember failed for %s: %s', channel_id, member)
        return False

    status_name = (member.get('result') or {}).get('status') or ''
    return status_name in ('administrator', 'creator')


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


def create_payment_request(
    chat_id: str,
    amount: int,
    callback_url: Optional[str] = None,
    title: str = 'پرداخت سفارش تبلیغ',
    description: str = 'پرداخت هزینه انتشار تبلیغ در کانال',
    payload: Optional[str] = None,
) -> Dict[str, Any]:
    provider = _card_number()
    inv_payload = payload or f'order-pay-{chat_id}-{amount}'

    if provider:
        inv = send_invoice(
            chat_id=str(chat_id),
            title=title[:32],
            description=description[:255],
            payload=inv_payload[:128],
            provider_token=provider,
            prices=[{'label': 'مبلغ سفارش', 'amount': int(amount)}],
            currency='IRR',
        )
        if not inv.get('error') and inv.get('ok', True):
            return {'ok': True, 'invoice': inv, 'payment_url': None}
        logger.warning('create_payment_request: sendInvoice failed, fallback: %s', inv)
        inv_error = inv.get('error') or inv.get('description') or str(inv)
    else:
        inv_error = 'BALE_CARD_NUMBER not configured'
        logger.warning(inv_error)

    text = (
        f'{title}\n'
        f'مبلغ قابل پرداخت: {amount} ریال\n'
        f'لطفاً برای تکمیل پرداخت با پشتیبانی هماهنگ کنید.'
    )
    msg = send_message(str(chat_id), text)
    return {
        'ok': False,
        'error': inv_error,
        'fallback_message': msg,
        'payment_url': None,
    }


def schedule_message(
    target_chat_id: str,
    message_payload: Dict[str, Any],
    send_at_iso: str,
) -> Dict[str, Any]:
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
        logger.info('schedule_message failed or unsupported: %s', e)
        return {'error': str(e)}
