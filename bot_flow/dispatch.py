"""Dispatch layer for Bale updates — used by webhook and poll_bot."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, time as dtime

from django.utils import timezone

from bot_flow import customer as cust
from bot_flow import handlers as flow
from bot_flow import manager_panel as mpanel
from bot_flow import operator_panel as opanel
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
from users.models import BotSession, User, get_bot_session
from wallet.services import (
    build_payout_batch,
    is_operator,
    mark_batch_paid,
)

log = logging.getLogger('poll_bot')

_recent_callbacks: dict[tuple, float] = {}

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


def _answer(cq_id, text: str = '') -> None:
    if cq_id:
        bc.answer_callback_query(str(cq_id), text=text)


def run_mgr(action: str, bale_uid: str, item_id: int, new_start=None) -> str:
    from bot_flow.messages import fa_num, label_order_status, user_error

    result = process_manager_item(item_id, bale_uid, action, new_start=new_start)
    log.info('%s item=%s → %s', action, item_id, result)
    if result.get('ok'):
        if result.get('pending_left'):
            return f'ثبت شد. هنوز {fa_num(result["pending_left"])} کانال‌دار جواب نداده.'
        status = label_order_status(str(result.get('order_status') or ''))
        return f'ثبت شد. سفارش الان {status} است.'
    return user_error(result.get('error'))


def handle_legacy_commands(chat_id: str, bale_uid: str, text: str) -> bool:
    m = CMD_APPROVE.match(text)
    if m:
        sid = _cmd_id(m)
        if sid:
            bc.send_message(chat_id, run_mgr('approve', bale_uid, int(sid)))
        else:
            bc.send_message(chat_id, 'شماره نوبت را هم بفرستید.')
        return True
    m = CMD_REJECT.match(text)
    if m:
        sid = _cmd_id(m)
        if sid:
            bc.send_message(chat_id, run_mgr('reject', bale_uid, int(sid)))
        else:
            bc.send_message(chat_id, 'شماره نوبت را هم بفرستید.')
        return True
    m = CMD_PAID.match(text)
    if m:
        from bot_flow.access import is_debug_user

        sid = _cmd_id(m)
        if not is_debug_user(bale_uid):
            bc.send_message(chat_id, 'پرداخت فقط از فاکتور کیف پول بله ثبت می‌شود.')
            return True
        if sid:
            r = process_payment_paid(int(sid))
            bc.send_message(
                chat_id,
                'سفارش آزمایشی پرداخت‌شده ثبت شد.' if r.get('ok') else 'این سفارش آمادهٔ پرداخت نیست.',
            )
        else:
            bc.send_message(chat_id, 'شماره سفارش را هم بفرستید.')
        return True

    if text in ('/miniapp', '/minapp', '/مینی', '/مینیاپ'):
        sess = BotSession.objects.filter(bale_user_id=bale_uid).first()
        role = (sess.role if sess and sess.role in ('customer', 'manager', 'operator') else None) or 'customer'
        label = {
            'customer': 'بخش مشتری — لینک‌بان را باز کنید:',
            'manager': 'بخش کانال‌دار — لینک‌بان را باز کنید:',
            'operator': 'بخش پشتیبانی — لینک‌بان را باز کنید:',
        }.get(role, 'لینک‌بان را باز کنید:')
        send_miniapp_entry(chat_id, label, role=role)
        return True

    if text in ('/operator', '/op', '/اپراتور', '/پشتیبانی') and is_operator(bale_uid):
        opanel.open_panel(chat_id, bale_uid)
        return True

    if text.startswith('/payout_file') and is_operator(bale_uid):
        user = User.objects.filter(bale_user_id=bale_uid).first()
        if not user:
            bc.send_message(chat_id, 'این کاربر را پیدا نکردم.')
            return True
        r = build_payout_batch(user)
        if not r.get('ok'):
            from bot_flow.messages import user_error

            bc.send_message(chat_id, user_error(r.get('error')))
            return True
        from bot_flow.messages import fa_num

        batch = r['batch']
        body = r['file_text'] or 'چیزی در این فهرست نیست.'
        header = f'فایل تسویه {fa_num(batch.id)} — {fa_num(r["count"])} درخواست\nمبلغ‌ها به ریال:\n'
        bc.send_message(chat_id, header + body[:3500])
        bc.send_message(chat_id, 'پس از واریز بانک، دکمهٔ «پرداخت انجام شد» را بزنید.')
        return True

    m = re.match(r'^/payout_paid_(\d+)$', text, re.I)
    if m and is_operator(bale_uid):
        r = mark_batch_paid(int(m.group(1)))
        bc.send_message(
            chat_id,
            'پرداخت این دسته ثبت شد و به کانال‌دارها خبر داده شد.' if r.get('ok') else 'این دسته را پیدا نکردم، یا قبلاً ثبت شده.',
        )
        return True

    if text in ('/wallet', '/کیف') or text.startswith('/wallet'):
        user = User.objects.filter(bale_user_id=bale_uid).first()
        if user:
            mpanel.show_wallet(chat_id, user)
        else:
            bc.send_message(chat_id, 'اول از منوی اصلی وارد شوید.')
        return True

    if text.startswith('/audit_admin') and is_operator(bale_uid):
        r = daily_admin_audit()
        bc.send_message(chat_id, f'نتیجهٔ بررسی کانال‌ها:\n{r}')
        return True

    return False
