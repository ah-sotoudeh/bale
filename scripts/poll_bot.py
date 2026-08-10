#!/usr/bin/env python3
"""Long-polling: لینک‌سازه (Bot API) + لینک‌یار (aiobale user)."""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import datetime, time as dtime
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

from bot_flow import customer as cust  # noqa: E402
from bot_flow import handlers as flow  # noqa: E402
from integrations import bale_client as bc  # noqa: E402
from integrations.bale_client import _token  # noqa: E402
from integrations import linkyar_client as ly  # noqa: E402
from orders.cart import expire_timed_out_items, process_manager_item  # noqa: E402
from orders.publish import daily_admin_audit, delete_expired_posts, publish_due_items  # noqa: E402
from orders.services import process_payment_paid  # noqa: E402
from users.models import BotSession, User  # noqa: E402
from wallet.services import (  # noqa: E402
    available_balance,
    build_payout_batch,
    is_operator,
    mark_batch_paid,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('poll_bot')

_INVISIBLE = re.compile(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00a0]')
CMD_APPROVE = re.compile(r'^/approve(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$', re.I)
CMD_REJECT = re.compile(r'^/reject(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$', re.I)
CMD_PAID = re.compile(r'^/paid(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$', re.I)

_last_daily_audit_date = None


def normalize_text(text: str) -> str:
    if not text:
        return ''
    t = _INVISIBLE.sub('', text).replace('\u00a0', ' ').strip()
    return re.sub(r'\s+', ' ', t)


def _cmd_id(m: re.Match) -> str | None:
    return m.group(1) or m.group(2)


def ensure_token() -> None:
    token = _token()
    if not token:
        log.error('BALE_BOT_TOKEN missing (لینک‌سازه)')
        sys.exit(1)
    log.info('لینک‌سازه bot token length=%d', len(token))

    ut = ly.user_token()
    if not ut:
        log.warning(
            'BALE_TOKEN missing — لینک‌یار (کاربر) وصل نیست. '
            'ارسال خودکار کانال کار نمی‌کند تا JWT سشن را در .env بگذارید.'
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
        log.error('لینک‌سازه getMe failed: %s', me)
        sys.exit(1)
    result = me.get('result') or me
    log.info('لینک‌سازه OK → id=%s @%s', result.get('id'), result.get('username'))
    info = bc.get_webhook_info()
    url = (info.get('result') or {}).get('url') or ''
    if url:
        bc.delete_webhook()
        log.info('Webhook deleted')


def run_mgr(action: str, bale_uid: str, item_id: int, new_start=None) -> str:
    result = process_manager_item(item_id, bale_uid, action, new_start=new_start)
    log.info('%s item=%s → %s', action, item_id, result)
    if result.get('ok'):
        if result.get('pending_left'):
            return f'✅ ثبت شد. هنوز {result["pending_left"]} آیتم در انتظار است.'
        return f'✅ ثبت شد. وضعیت سفارش: {result.get("order_status")}'
    return f'❌ {result.get("error") or result}'


def handle_legacy_commands(chat_id: str, bale_uid: str, text: str) -> bool:
    m = CMD_APPROVE.match(text)
    if m:
        sid = _cmd_id(m)
        if sid:
            bc.send_message(chat_id, run_mgr('approve', bale_uid, int(sid)))
        return True
    m = CMD_REJECT.match(text)
    if m:
        sid = _cmd_id(m)
        if sid:
            bc.send_message(chat_id, run_mgr('reject', bale_uid, int(sid)))
        return True
    m = CMD_PAID.match(text)
    if m:
        sid = _cmd_id(m)
        if sid:
            r = process_payment_paid(int(sid))
            bc.send_message(
                chat_id,
                '💳 سفارش پرداخت شد' if r.get('ok') else f'❌ {r.get("error")}',
            )
        return True

    if text.startswith('/payout_file') and is_operator(bale_uid):
        user = User.objects.filter(bale_user_id=bale_uid).first()
        if not user:
            bc.send_message(chat_id, 'کاربر یافت نشد')
            return True
        r = build_payout_batch(user)
        if not r.get('ok'):
            bc.send_message(chat_id, f'خطا: {r.get("error")}')
            return True
        batch = r['batch']
        body = r['file_text'] or '(خالی)'
        header = f'📁 Batch #{batch.id} — {r["count"]} درخواست\nمبالغ ریال:\n'
        bc.send_message(chat_id, header + body[:3500])
        bc.send_message(chat_id, f'پس از واریز بانک: /payout_paid_{batch.id}')
        return True

    m = re.match(r'^/payout_paid_(\d+)$', text, re.I)
    if m and is_operator(bale_uid):
        r = mark_batch_paid(int(m.group(1)))
        bc.send_message(
            chat_id,
            '✅ پرداخت batch ثبت شد' if r.get('ok') else f'❌ {r.get("error")}',
        )
        return True

    if text in ('/wallet', '/کیف') or text.startswith('/wallet'):
        user = User.objects.filter(bale_user_id=bale_uid).first()
        if user:
            bal = available_balance(user)
            bc.send_message(chat_id, f'💰 موجودی قابل برداشت: {bal:,} تومان')
        return True

    if text.startswith('/audit_admin') and is_operator(bale_uid):
        r = daily_admin_audit()
        bc.send_message(chat_id, f'چک ادمین: {r}')
        return True

    return False


def handle_callback_query(cq: dict) -> None:
    cq_id = cq.get('id')
    data = (cq.get('data') or '').strip()
    from_user = cq.get('from') or {}
    bale_uid = str(from_user.get('id') or '')
    username = from_user.get('username') or ''
    msg = cq.get('message') or {}
    chat_id = str((msg.get('chat') or {}).get('id') or '')

    log.info('callback %r user=%s', data, bale_uid)

    if cust.handle_customer_callback(
        chat_id, bale_uid, data, cq_id=str(cq_id) if cq_id else None
    ):
        return

    if flow.try_handle_callback(
        chat_id, bale_uid, data, cq_id=str(cq_id) if cq_id else None, username=username
    ):
        return

    if data.startswith('approve:'):
        text = run_mgr('approve', bale_uid, int(data.split(':')[1]))
        if cq_id:
            bc.answer_callback_query(str(cq_id), text='OK')
        bc.send_message(chat_id, text)
        return
    if data.startswith('reject:'):
        text = run_mgr('reject', bale_uid, int(data.split(':')[1]))
        if cq_id:
            bc.answer_callback_query(str(cq_id), text='OK')
        bc.send_message(chat_id, text)
        return
    if data.startswith('editask:'):
        item_id = int(data.split(':')[1])
        if cq_id:
            bc.answer_callback_query(str(cq_id), text='تاریخ')
        sess, _ = BotSession.objects.get_or_create(
            bale_user_id=bale_uid, defaults={'state': 'idle', 'data': {}}
        )
        d = dict(sess.data or {})
        d['edit_item_id'] = item_id
        sess.state = 'mgr_edit_date'
        sess.data = d
        sess.save()
        bc.send_message(chat_id, f'تاریخ جدید آیتم #{item_id}: 2026-08-15')
        return
    if data.startswith('paid:'):
        r = process_payment_paid(int(data.split(':')[1]))
        if cq_id:
            bc.answer_callback_query(str(cq_id), text='OK')
        bc.send_message(
            chat_id,
            '💳 سفارش پرداخت شد' if r.get('ok') else f'❌ {r.get("error")}',
        )
        return

    if cq_id:
        bc.answer_callback_query(str(cq_id), text='؟')


def _parse_manager_date(text: str):
    text = text.strip().replace('/', '-')
    parts = text.split('-')
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if 1300 <= y <= 1500:
        try:
            import jdatetime

            day = jdatetime.date(y, m, d).togregorian()
        except Exception:
            try:
                day = datetime(y, m, d).date()
            except ValueError:
                return None
    else:
        try:
            day = datetime(y, m, d).date()
        except ValueError:
            return None
    return timezone.make_aware(datetime.combine(day, dtime(hour=10)))


def handle_update(update: dict) -> None:
    log.info('── update_id=%s ──', update.get('update_id'))

    if update.get('callback_query'):
        try:
            handle_callback_query(update['callback_query'])
        except Exception:
            log.exception('callback failed')
        return

    msg = update.get('message') or update.get('edited_message')
    if not msg:
        return

    chat_id = str((msg.get('chat') or {}).get('id') or '')
    from_user = msg.get('from') or {}
    bale_uid = str(from_user.get('id') or '')
    username = from_user.get('username') or ''
    text = msg.get('text') or ''
    norm = normalize_text(text)

    if not chat_id or not bale_uid:
        return

    if norm.startswith('/start'):
        flow.handle_start(chat_id, bale_uid, username)
        return

    try:
        sess = BotSession.objects.filter(bale_user_id=bale_uid).first()
        if sess and sess.state == 'mgr_edit_date' and norm:
            item_id = (sess.data or {}).get('edit_item_id')
            start = _parse_manager_date(norm)
            if not start or not item_id:
                bc.send_message(chat_id, 'تاریخ نامعتبر.')
                return
            text_out = run_mgr('edit', bale_uid, int(item_id), new_start=start)
            sess.state = 'idle'
            sess.data = {}
            sess.save()
            bc.send_message(chat_id, text_out)
            return
    except Exception:
        log.exception('mgr edit date')

    if msg.get('photo') or msg.get('video') or msg.get('document'):
        try:
            if cust.handle_banner_message(chat_id, bale_uid, msg):
                return
        except Exception:
            log.exception('banner handle')

    if handle_legacy_commands(chat_id, bale_uid, norm):
        return

    if cust.try_handle_customer_text(chat_id, bale_uid, text):
        return

    if flow.try_handle_text(chat_id, bale_uid, text):
        return

    if norm:
        bc.send_message(
            chat_id,
            '/start نقش\n/free روز خالی\n/wallet موجودی',
        )


def run_background_jobs() -> None:
    global _last_daily_audit_date
    try:
        n = expire_timed_out_items()
        if n:
            log.info('expired manager timeouts: %s', n)

        if ly.user_token():
            pub = publish_due_items()
            if pub.get('published') or pub.get('failed_channels'):
                log.info('publish job: %s', pub)

            deleted = delete_expired_posts()
            if deleted:
                log.info('deleted channel posts: %s', deleted)

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
