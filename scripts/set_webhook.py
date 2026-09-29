#!/usr/bin/env python3
"""وب‌هوک در این پروژه استفاده نمی‌شود.

ورود بازو فقط long polling است:
  python scripts/poll_bot.py

این اسکریپت اگر قبلاً وب‌هوک ثبت شده باشد آن را پاک می‌کند.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')

import django

django.setup()

from integrations import bale_client as bc  # noqa: E402


def main() -> None:
    info = bc.get_webhook_info()
    url = ((info.get('result') or {}).get('url') or '') if isinstance(info, dict) else ''
    if url:
        deleted = bc.delete_webhook()
        print('webhook removed:', url, deleted)
    else:
        print('no webhook set')
    print('run: python scripts/poll_bot.py')


if __name__ == '__main__':
    main()
