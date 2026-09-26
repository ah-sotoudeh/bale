#!/usr/bin/env python3
"""ثبت وب‌هوک بله روی پورت ۴۴۳. اگر WEBHOOK_SECRET دارید به آدرس ?token= اضافه می‌شود."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')

import django

django.setup()

from integrations import bale_client as bc


def main() -> None:
    base = (os.environ.get('MINIAPP_BASE_URL') or os.environ.get('PUBLIC_BASE_URL') or '').rstrip('/')
    if not base.startswith('https://'):
        raise SystemExit('MINIAPP_BASE_URL باید https باشد. بله فقط پورت ۴۴۳ و ۸۸ را برای وب‌هوک می‌پذیرد.')
    url = base + '/bot/webhook/'
    secret = os.environ.get('WEBHOOK_SECRET', '').strip()
    if secret:
        url += '?token=' + secret
    print(bc.set_webhook(url))
    print(bc.get_webhook_info())


if __name__ == '__main__':
    main()
