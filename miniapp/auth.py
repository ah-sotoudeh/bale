"""اعتبارسنجی initData مینی‌اپ بله (مشابه Telegram WebApp)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl

from integrations.bale_client import _token


def validate_init_data(
    init_data: str,
    *,
    max_age_sec: int = 86400,
    bot_token: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Return (ok, payload). payload includes 'user' dict when valid."""
    if not init_data or not isinstance(init_data, str):
        return False, {'error': 'empty_init_data'}

    token = bot_token or _token() or os.environ.get('BALE_BOT_TOKEN', '')
    if not token:
        return False, {'error': 'bot_token_missing'}

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', None)
    if not received_hash:
        return False, {'error': 'missing_hash'}

    data_check = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return False, {'error': 'bad_hash'}

    auth_date = pairs.get('auth_date')
    try:
        if auth_date and abs(time.time() - int(auth_date)) > max_age_sec:
            return False, {'error': 'expired'}
    except ValueError:
        return False, {'error': 'bad_auth_date'}

    user: Dict[str, Any] = {}
    if pairs.get('user'):
        try:
            user = json.loads(pairs['user'])
        except json.JSONDecodeError:
            return False, {'error': 'bad_user_json'}

    return True, {
        'user': user,
        'auth_date': auth_date,
        'query_id': pairs.get('query_id'),
        'start_param': pairs.get('start_param'),
        'raw': pairs,
    }


def bale_user_id_from_init(init_data: str) -> Optional[str]:
    ok, payload = validate_init_data(init_data)
    if not ok:
        return None
    uid = (payload.get('user') or {}).get('id')
    return str(uid) if uid is not None else None
