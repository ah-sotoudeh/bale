"""Dispatch layer for Bale updates — used by webhook and poll_bot."""
from __future__ import annotations

import logging
import re
from datetime import datetime, time as dtime

from django.utils import timezone

from bot_flow import customer as cust
from bot_flow import handlers as flow
from bot_flow import manager_panel as mpanel
from integrations import bale_client as bc
from miniapp.launch import send_miniapp_entry
from orders.cart import process_manager_item
from orders.execution import (
    customer_confirm_execution,
    operator_resolve,
)
from orders.publish import (
    daily_admin_audit,
    verify_manager_published,
)
from orders.services import process_payment_paid
from users.models import BotSession, User
from wallet.services import (
    build_payout_batch,
    is_operator,
    mark_batch_paid,
)

log = logging.getLogger('poll_bot')

_INVISIBLE = re.compile(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00a0]')
CMD_APPROVE = re.compile(r'^/approve(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$', re.I)
CMD_REJECT = re.compile(r'^/reject(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$', re.I)
CMD_PAID = re.compile(r'^/paid(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$', re.I)


def normalize_text(text: str) -> str:
    if not text:
        return ''
    t = _INVISIBLE.sub('', text).replace('\u00a0', ' ').strip()
    return re.sub(r'\s+', ' ', t)


def _cmd_id(m: re.Match) -> str | None:
    return m.group(1) or m.group(2)


def _answer(cq_id, text: str = 'OK') -> None:
    if cq_id:
        bc.answer_callback_query(str(cq_id), text=text)


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

    if text in ('/miniapp', '/minapp', '/مینی', '/مینیاپ'):
        send_miniapp_entry(chat_id, 'پنل مدیر (مینی‌اپ):')
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
        mpanel.try_handle_text(chat_id, bale_uid, '/panel')
        user = User.objects.filter(bale_user_id=bale_uid).first()
        if user:
            mpanel.show_wallet(chat_id, user)
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

    # تأیید بنر لینک‌بانک توسط اپراتور
    if data.startswith('bappr:') or data.startswith('brej:'):
        from orders.banner_publish import operator_decide

        req_id = int(data.split(':')[1])
        r = operator_decide(req_id, bale_uid, approve=data.startswith('bappr:'))
        _answer(cq_id, 'OK' if r.get('ok') else 'ERR')
        bc.send_message(chat_id, f'نتیجه درخواست بنر: {r}')
        return

    if cust.handle_customer_callback(
        chat_id, bale_uid, data, cq_id=str(cq_id) if cq_id else None
    ):
        return

    if mpanel.try_handle_callback(
        chat_id, bale_uid, data, cq_id=str(cq_id) if cq_id else None, username=username
    ):
        return

    if flow.try_handle_callback(
        chat_id, bale_uid, data, cq_id=str(cq_id) if cq_id else None, username=username
    ):
        return

    if data.startswith('approve:'):
        text = run_mgr('approve', bale_uid, int(data.split(':')[1]))
        _answer(cq_id)
        bc.send_message(chat_id, text)
        return
    if data.startswith('reject:'):
        text = run_mgr('reject', bale_uid, int(data.split(':')[1]))
        _answer(cq_id)
        bc.send_message(chat_id, text)
        return
    if data.startswith('editask:'):
        item_id = int(data.split(':')[1])
        _answer(cq_id, 'date')
        sess, _ = BotSession.objects.get_or_create(
            bale_user_id=bale_uid, defaults={'state': 'idle', 'data': {}}
        )
        d = dict(sess.data or {})
        d['edit_item_id'] = item_id
        sess.state = 'mgr_edit_date'
        sess.data = d
        sess.save()
        bc.send_message(chat_id, f'تاریخ جدید آیتم #{item_id}: 1405/05/20')
        return
    if data.startswith('paid:'):
        r = process_payment_paid(int(data.split(':')[1]))
        _answer(cq_id)
        bc.send_message(
            chat_id,
            '💳 سفارش پرداخت شد' if r.get('ok') else f'❌ {r.get("error")}',
        )
        return

    if data.startswith('published:'):
        parts = data.split(':')
        item_id = int(parts[1])
        channel_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        r = verify_manager_published(item_id, bale_uid, channel_id=channel_id)
        _answer(cq_id, 'OK' if r.get('ok') else 'NO')
        if r.get('ok'):
            links = r.get('permalinks') or []
            bc.send_message(
                chat_id,
                '✅ انتشار تأیید شد.\n' + '\n'.join(str(x) for x in links if x),
            )
        else:
            bc.send_message(chat_id, f'❌ {r.get("error") or r}')
        return

    if data.startswith('execok:') or data.startswith('execno:'):
        item_id = int(data.split(':')[1])
        ok = data.startswith('execok:')
        r = customer_confirm_execution(item_id, bale_uid, ok)
        _answer(cq_id, 'OK' if r.get('ok') else 'ERR')
        bc.send_message(chat_id, '✅ ثبت شد' if r.get('ok') else f'❌ {r.get("error")}')
        return

    if data.startswith('opok:') or data.startswith('opno:'):
        item_id = int(data.split(':')[1])
        r = operator_resolve(item_id, bale_uid, executed=data.startswith('opok:'))
        _answer(cq_id, 'OK' if r.get('ok') else 'ERR')
        bc.send_message(chat_id, f'{r}')
        return

    _answer(cq_id, 'OK')


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

    if mpanel.try_handle_text(chat_id, bale_uid, text, username=username):
        return

    if cust.try_handle_customer_text(chat_id, bale_uid, text):
        return

    if flow.try_handle_text(chat_id, bale_uid, text):
        return

    if norm:
        bc.send_message(
            chat_id,
            '/start نقش\n/panel پنل متنی\n/miniapp مینی‌اپ\n/free روز خالی\n/wallet موجودی',
        )
