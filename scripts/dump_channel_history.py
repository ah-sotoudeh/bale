#!/usr/bin/env python3
"""آخرین پیام‌های کانال را با لینک‌یار بخوان و پیوند واقعی ble.ir بساز.

الگوی پیوند مطلب (از وب بله):
  https://ble.ir/{username}/{message_id}/{date_ms}

نکته مهم: message_id برگشتی از Bot API (مثل 263) با message_id داخلی بله
یکی نیست. شناسه واقعی فقط از طریق aiobale/load_history قابل گرفتن است.

اجرا:
  python scripts/dump_channel_history.py --channel "@linktest" --limit 6
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / '.env', override=False)
    load_dotenv(ROOT / 'config' / '.env', override=False)
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')
os.environ.setdefault('USE_SQLITE', os.environ.get('USE_SQLITE', '1'))

import django

django.setup()

from integrations import linkyar_client as ly  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('dump_history')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', default='@linktest')
    ap.add_argument('--limit', type=int, default=6)
    args = ap.parse_args()

    ch = args.channel.strip()
    if ch and not ch.startswith('@') and not ch.lstrip('-').isdigit():
        ch = '@' + ch

    if not ly.user_token():
        log.error('BALE_TOKEN missing')
        sys.exit(1)

    log.info('loading last %s messages from %s …', args.limit, ch)
    res = ly.load_channel_history(ch, limit=args.limit)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    if not res.get('ok'):
        sys.exit(1)

    print('\n=== پیوندهای ساخته‌شده ===')
    for i, m in enumerate(res.get('messages') or [], 1):
        link = m.get('permalink')
        print(f"{i}. mid={m.get('message_id')} date={m.get('date')} sender={m.get('sender_id')}")
        print(f"   kind={m.get('kind')} preview={m.get('preview')!r}")
        print(f"   {link}")


if __name__ == '__main__':
    main()
