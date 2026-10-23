"""تنظیمات قابل‌ویرایش سامانه — پیش‌فرض‌ها؛ پنل پشتیبان می‌تواند override کند."""
from __future__ import annotations

import json
import os
from pathlib import Path

from django.conf import settings

_CACHE: dict | None = None
_PATH = Path(getattr(settings, 'BASE_DIR', Path('.'))) / 'config' / 'runtime_settings.json'


def _defaults() -> dict:
    return {
        'payment_hold_hours': int(os.environ.get('PAYMENT_HOLD_HOURS', '3')),
        'banner_fee_toman': int(os.environ.get('BANNER_FEE_TOMAN', '0')),
        'service_fee_toman': int(os.environ.get('SERVICE_FEE_TOMAN', '0')),
        'publish_retry_minutes': int(os.environ.get('PUBLISH_RETRY_MINUTES', '30')),
        'publish_retry_interval_sec': int(os.environ.get('PUBLISH_RETRY_INTERVAL_SEC', '60')),
        'min_topup_toman': int(os.environ.get('MIN_TOPUP_TOMAN', '10000')),
        'max_topup_toman': int(os.environ.get('MAX_TOPUP_TOMAN', '1000000')),
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
                data.update({k: raw[k] for k in data if k in raw})
    except Exception:
        pass
    _CACHE = data
    return dict(data)


def update_settings(patch: dict) -> dict:
    global _CACHE
    data = get_settings()
    for k, v in (patch or {}).items():
        if k not in data:
            continue
        try:
            data[k] = int(v)
        except (TypeError, ValueError):
            continue
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    _CACHE = data
    return dict(data)
