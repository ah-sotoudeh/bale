"""Bale API client implemented against the official Bale Bot API (tapi.bale.ai).

This client uses endpoints documented at https://docs.bale.ai/ (tapi.bale.ai).

Implemented operations:
- send_message(chat_id, text, reply_markup=None, reply_to_message_id=None)
- forward_message(to_chat_id, from_chat_id, message_id)
- get_chat_info(chat_id)
- send_invoice(chat_id, title, description, payload, provider_token, prices, currency)
- set_webhook(url)

Notes on scheduling:
- The official Bale Bot API does not document a schedule-message endpoint. If Bale adds a scheduling endpoint in the future, the schedule_message function can be updated to call it.
- Current schedule_message() tries a best-effort: it attempts to call /scheduleMessage if available; if not, it returns an error and the caller should fallback to server-side scheduling (cron/Celery).

Authentication:
- The Bale bot token must be provided in settings.BALE_BOT_TOKEN and is included in the URL path (/bot{token}/...).

"""
from django.conf import settings
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

BALE_API_BASE = getattr(settings, 'BALE_API_URL', 'https://tapi.bale.ai')
TOKEN = getattr(settings, 'BALE_BOT_TOKEN', '')

if not TOKEN:
    logger.warning('BALE_BOT_TOKEN is empty; Bale API calls will fail until a token is configured.')

def _bot_url(path: str) -> str:
    """Construct a full bot URL for a given method path, inserting token into /bot{token}/{method}"""
    token_segment = f"/bot{TOKEN}" if TOKEN else "/bot"
    return f"{BALE_API_BASE}{token_segment}/{path.lstrip('/')}"


def send_message(chat_id: str, text: str, reply_markup: Optional[Dict]=None, reply_to_message_id: Optional[int]=None) -> Dict[str, Any]:
    url = _bot_url('sendMessage')
    payload = {
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
    # getChat is a GET endpoint with query param chat_id
    url = _bot_url('getChat')
    try:
        r = requests.get(url, params={'chat_id': chat_id}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('get_chat_info failed')
        return {'error': str(e)}


def send_invoice(chat_id: str, title: str, description: str, payload: str, provider_token: str, prices: List[Dict[str, Any]], currency: str = 'IRR', start_parameter: str = 'pay') -> Dict[str, Any]:
    """Create/send an invoice to a user via Bale Bot API (sendInvoice).

    prices: list of {"label": "...", "amount": integer}
    amount units: Bale expects amount in smallest currency unit (e.g., IRR rials) depending on provider.
    """
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


def set_webhook(url: str) -> Dict[str, Any]:
    endpoint = _bot_url('setWebhook')
    try:
        r = requests.post(endpoint, json={'url': url}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.exception('set_webhook failed')
        return {'error': str(e)}


def schedule_message(target_chat_id: str, message_payload: Dict[str, Any], send_at_iso: str) -> Dict[str, Any]:
    """Attempt to schedule a message via Bale API if a scheduling endpoint exists.

    Current public Bale Bot API docs do not list a scheduling endpoint. This function will attempt a best-effort
    call to a hypothetical /scheduleMessage endpoint and will return an error dict if scheduling is not supported.

    Caller should implement server-side scheduling fallback (cron/Celery) when the return contains 'error'.
    """
    url = _bot_url('scheduleMessage')
    body = {
        'chat_id': target_chat_id,
        'payload': message_payload,
        'send_at': send_at_iso,
    }
    try:
        r = requests.post(url, json=body, timeout=10)
        # if 404 or other not-implemented response, treat as not supported
        if r.status_code == 404:
            return {'error': 'scheduling_not_supported'}
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.info('schedule_message failed or unsupported, returning error for fallback')
        return {'error': str(e)}
