#!/usr/bin/env python3
"""Seed demo data and create a real order that notifies on Bale.

Usage (PowerShell)::

    cd G:\\GitHub\\bale
    python scripts/demo_order_flow.py

If DB is broken, delete db.sqlite3 once, then re-run.
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
        print('Not using SQLite; cannot auto-reset. Fix migrations manually.')
        return
    for candidate in (path, Path(str(path) + '-journal'), Path(str(path) + '-wal'), Path(str(path) + '-shm')):
        if candidate.exists():
            candidate.unlink()
            print(f'Removed {candidate}')


def ensure_db() -> None:
    """Create migrations and tables; reset SQLite if history is inconsistent."""
    call_command('makemigrations', 'users', 'channels_app', 'orders', interactive=False, verbosity=1)
    try:
        call_command('migrate', interactive=False, verbosity=1)
    except InconsistentMigrationHistory as e:
        print('Inconsistent migration history detected.')
        print(e)
        print('Resetting local SQLite database and migrating again...')
        _reset_sqlite()
        call_command('migrate', interactive=False, verbosity=1)


def get_or_create_demo_user(bale_id: str) -> User:
    existing = User.objects.filter(bale_user_id=bale_id).first()
    if existing:
        return existing

    user, created = User.objects.get_or_create(
        username=f'demo_{bale_id}',
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
        '--bale-id',
        default=os.environ.get('DEMO_BALE_USER_ID', '80619262'),
        help='Your Bale user id',
    )
    parser.add_argument('--price', type=int, default=10000, help='Price in Rials')
    args = parser.parse_args()
    bale_id = str(args.bale_id)

    print('Ensuring database tables exist...')
    ensure_db()

    print(f'Using bale_user_id={bale_id}')
    try:
        user = get_or_create_demo_user(bale_id)
    except (OperationalError, ProgrammingError) as e:
        print('Database error after migrate:', e)
        print('Try:')
        print('  del db.sqlite3')
        print('  python manage.py makemigrations')
        print('  python manage.py migrate')
        sys.exit(1)

    channel, _ = Channel.objects.get_or_create(
        link='@demo_channel',
        defaults={'name': 'کانال دمو', 'description': 'برای تست فلو', 'manager': user},
    )
    if channel.manager_id != user.id:
        channel.manager = user
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
        customer=user,
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
        manager=user,
        manager_status='pending',
        banner_message_id=None,
    )

    print(f'Created order #{order.id} item #{item.id} status={order.status}')
    print('Notifying on Bale...')
    notify_managers_for_order(order)
    print('Done.')
    print()
    print('Next:')
    print('  1) python scripts/poll_bot.py')
    print(f'  2) In Bale:  /approve {item.id}')
    print(f'  3) In Bale:  /paid {order.id}')
    print()


if __name__ == '__main__':
    main()
