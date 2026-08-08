#!/usr/bin/env python3
"""Seed demo data and create an order with distinct customer vs manager.

Examples (PowerShell)::

    # Manager = you (default 80619262), customer = other account
    python scripts/demo_order_flow.py --customer-bale-id 12345678

    # Explicit both
    python scripts/demo_order_flow.py --manager-bale-id 80619262 --customer-bale-id 12345678
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    load_dotenv(ROOT / 'config' / '.env', override=False)
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')
os.environ.setdefault('USE_SQLITE', '1')

import django

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db.migrations.exceptions import InconsistentMigrationHistory  # noqa: E402
from django.db.utils import OperationalError, ProgrammingError  # noqa: E402
from django.utils import timezone  # noqa: E402

from channels_app.models import Channel, Tariff  # noqa: E402
from orders.models import Order, OrderItem  # noqa: E402
from orders.services import notify_managers_for_order  # noqa: E402
from users.models import User  # noqa: E402


def _sqlite_path() -> Path | None:
    db = settings.DATABASES.get('default', {})
    if 'sqlite' not in db.get('ENGINE', ''):
        return None
    name = db.get('NAME')
    return Path(name) if name else None


def _reset_sqlite() -> None:
    path = _sqlite_path()
    if not path:
        print('Not using SQLite; cannot auto-reset.')
        return
    for candidate in (path, Path(str(path) + '-journal'), Path(str(path) + '-wal'), Path(str(path) + '-shm')):
        if candidate.exists():
            candidate.unlink()
            print(f'Removed {candidate}')


def ensure_db() -> None:
    call_command('makemigrations', 'users', 'channels_app', 'orders', interactive=False, verbosity=1)
    try:
        call_command('migrate', interactive=False, verbosity=1)
    except InconsistentMigrationHistory as e:
        print('Inconsistent migration history:', e)
        print('Resetting local SQLite...')
        _reset_sqlite()
        call_command('migrate', interactive=False, verbosity=1)


def get_or_create_user(role: str, bale_id: str) -> User:
    """One Django user per unique bale_user_id."""
    bale_id = str(bale_id).strip()
    existing = User.objects.filter(bale_user_id=bale_id).first()
    if existing:
        return existing

    username = f'{role}_{bale_id}'
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'bale_user_id': bale_id},
    )
    if not user.bale_user_id:
        user.bale_user_id = bale_id
        user.save(update_fields=['bale_user_id'])
    if created:
        user.set_password('demo-pass-not-used')
        user.save()
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description='Create a demo Bale ads order')
    parser.add_argument(
        '--manager-bale-id',
        default=os.environ.get('DEMO_MANAGER_BALE_ID', '80619262'),
        help='Channel manager Bale user id (default: 80619262)',
    )
    parser.add_argument(
        '--customer-bale-id',
        default=os.environ.get('DEMO_CUSTOMER_BALE_ID') or os.environ.get('DEMO_BALE_USER_ID'),
        help='Customer Bale user id (required if different from manager)',
    )
    parser.add_argument(
        '--bale-id',
        default=None,
        help='Deprecated: same id for both roles (solo test)',
    )
    parser.add_argument('--price', type=int, default=10000, help='Price in Rials')
    args = parser.parse_args()

    if args.bale_id and not args.customer_bale_id:
        # legacy solo mode
        manager_id = customer_id = str(args.bale_id)
    else:
        manager_id = str(args.manager_bale_id)
        customer_id = str(args.customer_bale_id) if args.customer_bale_id else None

    if not customer_id:
        print('ERROR: customer Bale id is required.')
        print('  1) From the other account send /start to the bot')
        print('  2) Copy the numeric id from the reply')
        print('  3) Run:')
        print('     python scripts/demo_order_flow.py --customer-bale-id <ID>')
        sys.exit(1)

    print('Ensuring database tables exist...')
    ensure_db()

    print(f'Manager bale_user_id = {manager_id}')
    print(f'Customer bale_user_id = {customer_id}')
    if manager_id == customer_id:
        print('(same person for both roles — solo mode)')

    try:
        manager = get_or_create_user('manager', manager_id)
        customer = get_or_create_user('customer', customer_id)
    except (OperationalError, ProgrammingError) as e:
        print('Database error:', e)
        sys.exit(1)

    channel, _ = Channel.objects.get_or_create(
        link='@demo_channel',
        defaults={'name': 'کانال دمو', 'description': 'برای تست فلو', 'manager': manager},
    )
    if channel.manager_id != manager.id:
        channel.manager = manager
        channel.save(update_fields=['manager'])

    tariff, _ = Tariff.objects.get_or_create(
        channel=channel,
        name='12h',
        defaults={'duration_hours': 12, 'price': args.price},
    )
    if tariff.price != args.price:
        tariff.price = args.price
        tariff.save(update_fields=['price'])

    start = timezone.now() + timedelta(days=1)
    end = start + timedelta(hours=tariff.duration_hours)

    order = Order.objects.create(
        customer=customer,
        status='waiting_managers',
        total_amount=tariff.price,
    )
    item = OrderItem.objects.create(
        order=order,
        channel=channel,
        tariff=tariff,
        requested_start=start,
        requested_end=end,
        price=tariff.price,
        manager=manager,
        manager_status='pending',
        banner_message_id=None,
    )

    print(f'Created order #{order.id} item #{item.id} status={order.status}')
    print(f'  customer user_id={customer.id} bale={customer.bale_user_id}')
    print(f'  manager  user_id={manager.id} bale={manager.bale_user_id}')
    print('Notifying manager on Bale...')
    notify_managers_for_order(order)
    print('Done.')
    print()
    print('Expected flow:')
    print(f'  • Manager account ({manager_id}): taps ✅ تأیید on the order message')
    print(f'  • Customer account ({customer_id}): receives payment prompt, taps 💳')
    print()


if __name__ == '__main__':
    main()
