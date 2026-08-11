#!/usr/bin/env python3
"""تست سریع انتشار با حالت bot روی @linktest.

مراحل:
  1) migrate در صورت نیاز
  2) کانال @linktest با publish_mode=bot
  3) بنر تستی از لینک‌ساز به چت مدیر
  4) OrderItem با status=paid و زمان شروع = الان
  5) publish_due_items()
  6) چاپ نتیجه + تاریخچه کانال

اجرا (venv فعال):
  python scripts/test_publish_bot_mode.py
  python scripts/test_publish_bot_mode.py --manager-bale-id 80619262 --customer-bale-id 1164810718
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import timedelta
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

from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402

from channels_app.models import Channel, Tariff  # noqa: E402
from integrations import bale_client as bc  # noqa: E402
from integrations import linkyar_client as ly  # noqa: E402
from orders.models import Order, OrderItem  # noqa: E402
from orders.publish import (  # noqa: E402
    check_bot_admin,
    publish_due_items,
    recover_permalink,
)
from users.models import User  # noqa: E402


def ensure_user(role: str, bale_id: str) -> User:
    bale_id = str(bale_id).strip()
    u = User.objects.filter(bale_user_id=bale_id).first()
    if u:
        return u
    username = f'{role}_{bale_id}'[:30]
    base = username
    n = 0
    while User.objects.filter(username=username).exists():
        n += 1
        username = f'{base}_{n}'[:30]
    u = User(username=username, bale_user_id=bale_id)
    u.set_unusable_password()
    u.save()
    return u


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', default='@linktest')
    ap.add_argument('--manager-bale-id', default=os.environ.get('DEMO_MANAGER_BALE_ID', '80619262'))
    ap.add_argument(
        '--customer-bale-id',
        default=os.environ.get('DEMO_CUSTOMER_BALE_ID', '1164810718'),
    )
    ap.add_argument('--price', type=int, default=50000)
    ap.add_argument('--skip-migrate', action='store_true')
    args = ap.parse_args()

    if not args.skip_migrate:
        print('=== migrate ===')
        try:
            call_command('makemigrations', 'channels_app', 'orders', interactive=False, verbosity=1)
            call_command('migrate', interactive=False, verbosity=1)
        except Exception as e:
            print('migrate warning:', e)

    ch_ref = args.channel.strip()
    if not ch_ref.startswith('@') and not ch_ref.lstrip('-').isdigit():
        ch_ref = '@' + ch_ref

    print('=== bot getMe ===')
    me = bc.get_me()
    print(json.dumps(me, ensure_ascii=False, indent=2)[:500])

    print('=== bot admin on', ch_ref, '===')
    is_admin = bc.bot_is_channel_admin(ch_ref)
    print('bot_is_channel_admin:', is_admin)
    if not is_admin:
        print(
            '⚠️ لینک‌ساز ادمین این کانال نیست. اول @linkbank_bot را در',
            ch_ref,
            'ادمین کنید و دوباره اجرا کنید.',
        )

    manager = ensure_user('manager', args.manager_bale_id)
    customer = ensure_user('customer', args.customer_bale_id)
    print(f'manager={manager.bale_user_id} customer={customer.bale_user_id}')

    ch, _ = Channel.objects.get_or_create(
        link=ch_ref,
        defaults={
            'name': 'لینک تست',
            'description': 'test',
            'manager': manager,
            'publish_mode': Channel.PUBLISH_BOT,
        },
    )
    ch.manager = manager
    ch.publish_mode = Channel.PUBLISH_BOT
    ch.name = ch.name or 'لینک تست'
    ch.save()
    print(f'channel id={ch.id} link={ch.link} mode={ch.publish_mode}')

    if is_admin:
        check_bot_admin(ch)
        print('bot_is_admin flag:', ch.bot_is_admin)

    tariff, _ = Tariff.objects.get_or_create(
        channel=ch,
        name='تست-بات',
        defaults={'duration_hours': 1, 'price': args.price, 'is_active': True},
    )
    tariff.is_active = True
    tariff.price = args.price
    tariff.save()

    # بنر تست: پیام متنی به چت خصوصی مدیر (منبع copy)
    banner_text = (
        f'🧪 بنر تست انتشار bot-mode\n'
        f'ts={int(time.time())}\n'
        f'کانال هدف: {ch_ref}'
    )
    print('=== send banner source to manager chat ===')
    src = bc.send_message(str(manager.bale_user_id), banner_text)
    print(json.dumps(src, ensure_ascii=False, indent=2)[:800])
    if not src.get('ok'):
        print('ارسال بنر منبع ناموفق — مدیر باید قبلاً /start زده باشد.')
        sys.exit(1)
    result = src.get('result') or {}
    banner_mid = result.get('message_id')
    banner_chat = str((result.get('chat') or {}).get('id') or manager.bale_user_id)
    if not banner_mid:
        print('message_id بنر پیدا نشد')
        sys.exit(1)
    print(f'banner_from_chat_id={banner_chat} banner_message_id={banner_mid}')

    now = timezone.now()
    order = Order.objects.create(
        customer=customer,
        status='paid',
        total_amount=tariff.price,
        banner_message_id=str(banner_mid),
        banner_from_chat_id=str(banner_chat),
        banner_caption='',
    )
    item = OrderItem.objects.create(
        order=order,
        channel=ch,
        tariff=tariff,
        requested_start=now - timedelta(minutes=1),
        requested_end=now + timedelta(hours=1),
        price=tariff.price,
        manager=manager,
        manager_status='approved',
        execution_status='paid',
    )
    print(f'order=#{order.id} item=#{item.id} execution_status=paid start=now')

    print('=== publish_due_items ===')
    pub = publish_due_items()
    print(pub)

    item.refresh_from_db()
    print('item after:')
    print(
        '  execution_status=', item.execution_status,
        ' published_link=', item.published_link,
        ' channel_message_id=', (item.channel_message_id or '')[:300],
    )

    print('=== load history @linktest (permalinks) ===')
    if ly.user_token():
        hist = ly.load_channel_history(ch_ref, limit=5)
        print(json.dumps(hist, ensure_ascii=False, indent=2, default=str)[:2500])
        meta = recover_permalink(ch, min_date_ms=int((time.time() - 120) * 1000))
        print('recover_permalink:', meta)
    else:
        print('BALE_TOKEN missing — history skip')

    print('\nDone. چک کنید کانال', ch_ref, 'و پیام مشتری', customer.bale_user_id)


if __name__ == '__main__':
    main()
