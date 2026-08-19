#!/usr/bin/env python3
"""Long-polling: لینک‌ساز (Bot API) + لینک‌یار (aiobale user)."""
from __future__ import annotations

import logging
import os
import sys
import time
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

from django.utils import timezone  # noqa: E402

from bot_flow.dispatch import handle_update  # noqa: E402
from integrations import bale_client as bc  # noqa: E402
from integrations.bale_client import _token  # noqa: E402
from integrations import linkyar_client as ly  # noqa: E402
from orders.cart import expire_timed_out_items  # noqa: E402
from orders.execution import (  # noqa: E402
    escalate_unconfirmed,
    send_publish_reminders,
)
from orders.publish import (  # noqa: E402
    daily_admin_audit,
    delete_expired_posts,
    publish_due_items,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('poll_bot')

_last_daily_audit_date = None


def ensure_token() -> None:
    token = _token()
    if not token:
        log.error('BALE_BOT_TOKEN missing (لینک‌ساز)')
        sys.exit(1)
    log.info('لینک‌ساز bot token length=%d', len(token))

    ut = ly.user_token()
    if not ut:
        log.warning(
            'BALE_TOKEN missing — لینک‌یار (کاربر) وصل نیست. '
            'حالت linkyar و تأیید تاریخچه محدود می‌شود.'
        )
    else:
        log.info('لینک‌یار user token length=%d', len(ut))
        me = ly.get_me()
        if me.get('ok'):
            log.info('لینک‌یار get_me OK user_id=%s', me.get('user_id'))
        else:
            log.warning('لینک‌یار get_me failed: %s', me)


def prepare_polling() -> None:
    me = bc.get_me()
    if me.get('error') or not me.get('ok', True):
        log.error('لینک‌ساز getMe failed: %s', me)
        sys.exit(1)
    result = me.get('result') or me
    log.info('لینک‌ساز OK → id=%s @%s', result.get('id'), result.get('username'))
    info = bc.get_webhook_info()
    url = (info.get('result') or {}).get('url') or ''
    if url:
        bc.delete_webhook()
        log.info('Webhook deleted')


def run_background_jobs() -> None:
    global _last_daily_audit_date
    try:
        n = expire_timed_out_items()
        if n:
            log.info('expired manager timeouts: %s', n)

        reminded = send_publish_reminders()
        if reminded:
            log.info('publish reminders: %s', reminded)

        pub = publish_due_items()
        if any(pub.get(k) for k in ('published', 'failed_channels', 'manual_reminded')):
            log.info('publish job: %s', pub)

        if ly.user_token():
            deleted = delete_expired_posts()
            if deleted:
                log.info('deleted channel posts: %s', deleted)

        escalated = escalate_unconfirmed()
        if escalated:
            log.info('escalated unconfirmed: %s', escalated)

        today = timezone.localdate()
        if _last_daily_audit_date != today:
            audit = daily_admin_audit()
            log.info('daily admin audit: %s', audit)
            _last_daily_audit_date = today
    except Exception:
        log.exception('background jobs')


def run_polling(timeout: int = 25) -> None:
    offset = None
    last_jobs = 0.0
    log.info('Polling…')
    while True:
        try:
            now = time.time()
            if now - last_jobs > 60:
                run_background_jobs()
                last_jobs = now

            data = bc.get_updates(offset=offset, limit=50, timeout=timeout)
            if data.get('error'):
                log.warning('getUpdates error: %s', data['error'])
                time.sleep(3)
                continue
            if not data.get('ok', True):
                time.sleep(5)
                continue
            for upd in data.get('result') or []:
                try:
                    handle_update(upd)
                except Exception:
                    log.exception('handle_update')
                uid = upd.get('update_id')
                if uid is not None:
                    offset = uid + 1
        except KeyboardInterrupt:
            log.info('Stopped.')
            break
        except Exception as e:
            log.exception('loop: %s', e)
            time.sleep(5)


def main() -> None:
    ensure_token()
    prepare_polling()
    run_polling()


if __name__ == '__main__':
    main()
