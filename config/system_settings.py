"""تنظیمات قابل‌ویرایش سامانه — پیش‌فرض‌ها؛ پنل پشتیبان می‌تواند override کند."""
from __future__ import annotations

import json
import os
from pathlib import Path

from django.conf import settings

_CACHE: dict | None = None
_PATH = Path(getattr(settings, 'BASE_DIR', Path('.'))) / 'config' / 'runtime_settings.json'

_INT_KEYS = {
    'payment_hold_hours',
    'banner_fee_toman',
    'service_fee_toman',
    'publish_retry_minutes',
    'publish_retry_interval_sec',
    'min_topup_toman',
    'max_topup_toman',
}
_STR_KEYS = {
    'card_holder',
    'card_number',
    'card_iban',
    'card_bank_name',
    'card_note',
}


def _defaults() -> dict:
    return {
        'payment_hold_hours': int(os.environ.get('PAYMENT_HOLD_HOURS', '3')),
        'banner_fee_toman': int(os.environ.get('BANNER_FEE_TOMAN', '0')),
        'service_fee_toman': int(os.environ.get('SERVICE_FEE_TOMAN', '0')),
        'publish_retry_minutes': int(os.environ.get('PUBLISH_RETRY_MINUTES', '30')),
        'publish_retry_interval_sec': int(os.environ.get('PUBLISH_RETRY_INTERVAL_SEC', '60')),
        'min_topup_toman': int(os.environ.get('MIN_TOPUP_TOMAN', '10000')),
        'max_topup_toman': int(os.environ.get('MAX_TOPUP_TOMAN', '1000000')),
        'card_holder': os.environ.get('CARD_HOLDER', '') or '',
        'card_number': os.environ.get('CARD_NUMBER', '') or '',
        'card_iban': os.environ.get('CARD_IBAN', '') or '',
        'card_bank_name': os.environ.get('CARD_BANK_NAME', '') or '',
        'card_note': os.environ.get('CARD_NOTE', '') or 'پس از واریز، رسید را در تیکت پشتیبانی بفرستید.',
    }


def get_settings() -> dict:
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    data = _defaults()
    try:
        if _PATH.is_file():
            raw = json.loads(_PATH.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                for k in data:
                    if k in raw:
                        data[k] = raw[k]
    except Exception:
        pass
    _CACHE = data
    return dict(data)


def update_settings(patch: dict) -> dict:
    global _CACHE
    data = get_settings()
    for k, v in (patch or {}).items():
        if k in _INT_KEYS:
            try:
                data[k] = int(v)
            except (TypeError, ValueError):
                continue
        elif k in _STR_KEYS:
            data[k] = str(v or '')[:500]
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    _CACHE = data
    return dict(data)


def public_card_info() -> dict:
    s = get_settings()
    return {
        'holder': s.get('card_holder') or '',
        'card_number': s.get('card_number') or '',
        'iban': s.get('card_iban') or '',
        'bank_name': s.get('card_bank_name') or '',
        'note': s.get('card_note') or '',
    }
