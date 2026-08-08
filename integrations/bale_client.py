"""Bale API client implemented against the official Bale Bot API (tapi.bale.ai).

This client uses endpoints documented at https://docs.bale.ai/ (tapi.bale.ai).

Implemented operations:
- send_message / forward_message / get_chat_info / get_channel_info
- get_chat_member / bot_is_channel_admin
- send_invoice / create_payment_request
- set_webhook / delete_webhook / get_webhook_info
- get_updates (long-polling) / get_me
- schedule_message (best-effort)

Authentication:
- Token from settings.BALE_BOT_TOKEN (Django) or env BALE_BOT_TOKEN (standalone scripts).
- Card/provider token from settings.BALE_CARD_NUMBER or env BALE_CARD_NUMBER.
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
    CARD_NUMBER = getattr(settings, 'BALE_CARD_NUMBER', None) or os.environ.get('BALE_CARD_NUMBER', '')
except Exception:
    BALE_API_BASE = os.environ.get('BALE_API_URL', 'https://tapi.bale.ai')
    TOKEN = os.environ.get('BALE_BOT_TOKEN', '')
    CARD_NUMBER = os.environ.get('BALE_CARD_NUMBER', '')

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
    """Long-polling getUpdates. Webhook must be deleted first."""
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
    """Remove webhook so getUpdates (polling) can be used."""
    endpoint = _bot_url('deleteWebhook')
    try:
        r = requests.post(endpoint, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('delete_webhook failed')
        return {'error': str(e)}


def send_message(
    chat_id: str,
    text: str,
    reply_markup: Optional[Dict] = None,
    reply_to_message_id: Optional[int] = None,
) -> Dict[str, Any]:
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
    """Call getChat. Returns full API response (ok/result/error)."""
    url = _bot_url('getChat')
    try:
        r = requests.get(url, params={'chat_id': chat_id}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_chat_info failed')
        return {'error': str(e)}


def get_channel_info(channel_link: str) -> Dict[str, Any]:
    """Fetch channel/chat info and normalize to a flat dict for callers.

    Accepts @username, numeric id, or invite-style link fragments.
    Returns keys like: title, bio/description, id, username, type — or {'error': ...}.
    """
    raw = get_chat_info(channel_link)
    if raw.get('error'):
        return raw
    if not raw.get('ok', True):
        return {'error': raw.get('description') or 'getChat failed', 'raw': raw}

    result = raw.get('result') or raw
    # Normalize common field names used by RegisterChannelView
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
    """getChatMember — status of a user (or the bot) in a chat/channel."""
    url = _bot_url('getChatMember')
    try:
        r = requests.get(url, params={'chat_id': chat_id, 'user_id': user_id}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_chat_member failed')
        return {'error': str(e)}


def bot_is_channel_admin(channel_id: str) -> bool:
    """Return True if this bot is administrator/creator in the given channel.

    Requires the bot to be a member of the channel. On any API error returns False.
    """
    me = get_me()
    bot_id = None
    if me.get('ok') or 'result' in me:
        bot_id = (me.get('result') or {}).get('id')
    if not bot_id:
        # try nested / alternate shapes
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


def create_payment_request(
    chat_id: str,
    amount: int,
    callback_url: Optional[str] = None,
    title: str = 'پرداخت سفارش تبلیغ',
    description: str = 'پرداخت هزینه انتشار تبلیغ در کانال',
    payload: Optional[str] = None,
) -> Dict[str, Any]:
    """High-level helper used by order flow.

    Tries sendInvoice with BALE_CARD_NUMBER as provider_token.
    If card/token is missing or invoice fails, falls back to a plain text
    payment instruction message so the flow does not crash.

    Returns dict with optional keys: ok, payment_url, error, invoice, fallback_message.
    callback_url is currently unused by Bale sendInvoice but kept for future webhooks.
    """
    provider = CARD_NUMBER or os.environ.get('BALE_CARD_NUMBER', '')
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
            return {
                'ok': True,
                'invoice': inv,
                # Bale may not return a separate URL; invoice message itself is the pay UI
                'payment_url': None,
            }
        logger.warning('create_payment_request: sendInvoice failed, falling back to text: %s', inv)
        inv_error = inv.get('error') or inv.get('description') or str(inv)
    else:
        inv_error = 'BALE_CARD_NUMBER not configured'
        logger.warning(inv_error)

    # Fallback: notify user with amount (manual / later invoice)
    text = (
        f"{title}\n"
        f"مبلغ قابل پرداخت: {amount} ریال\n"
        f"لطفاً برای تکمیل پرداخت با پشتیبانی هماهنگ کنید."
    )
    msg = send_message(str(chat_id), text)
    return {
        'ok': False,
        'error': inv_error,
        'fallback_message': msg,
        'payment_url': None,
    }


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
