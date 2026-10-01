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
        send_miniapp_entry(chat_id, 'بخش کانال‌دار:')
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


def _callback_is_repeat(bale_uid: str, data: str, message_id) -> bool:
    """لمس دوبارهٔ همان دکمه، تا چند ثانیه، پیام تازه نمی‌سازد."""
    now = time.monotonic()
    key = (str(bale_uid), data, str(message_id or ''))
    stale = [item for item, seen in _recent_callbacks.items() if now - seen > 30]
    for item in stale:
        _recent_callbacks.pop(item, None)
    seen = _recent_callbacks.get(key)
    _recent_callbacks[key] = now
    return seen is not None and now - seen < 4


def handle_callback_query(cq: dict) -> None:
    cq_id = cq.get('id')
    data = (cq.get('data') or '').strip()
    from_user = cq.get('from') or {}
    bale_uid = str(from_user.get('id') or '')
    username = from_user.get('username') or ''
    msg = cq.get('message') or {}
    chat_id = str((msg.get('chat') or {}).get('id') or '')

    _answer(cq_id, '')
    if _callback_is_repeat(bale_uid, data, msg.get('message_id')):
        log.info('callback repeat ignored %r user=%s', data, bale_uid)
        return

    log.info('callback %r user=%s', data, bale_uid)

    if data.startswith('bappr:') or data.startswith('brej:'):
        from orders.banner_publish import operator_decide

        req_id = int(data.split(':')[1])
        r = operator_decide(req_id, bale_uid, approve=data.startswith('bappr:'))
        _answer(cq_id, '')
        msg_out = r.get('message') or (
            'انجام شد.' if r.get('ok') else 'انجام نشد. یک بار دیگر بزنید.'
        )
        bc.send_message(chat_id, msg_out)
        return

    if opanel.try_handle_callback(
        chat_id, bale_uid, data, cq_id=str(cq_id) if cq_id else None, username=username
    ):
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
        _answer(cq_id, '')
        sess = get_bot_session(bale_uid)
        d = dict(sess.data or {})
        d['edit_item_id'] = item_id
        sess.state = 'mgr_edit_date'
        sess.data = d
        sess.save()
        bc.send_message(
            chat_id,
            'تاریخ تازهٔ همین کانال را به شکل ۱۴۰۴/۰۶/۱۵ بفرستید.',
        )
        return
    if data.startswith('paid:'):
        from bot_flow.access import is_debug_user

        if not is_debug_user(bale_uid):
            _answer(cq_id, '')
            bc.send_message(chat_id, 'پرداخت فقط از فاکتور کیف پول بله ثبت می‌شود.')
            return
        r = process_payment_paid(int(data.split(':')[1]))
        _answer(cq_id)
        from bot_flow.messages import user_error

        bc.send_message(
            chat_id,
            'سفارش پرداخت شد.' if r.get('ok') else user_error(r.get('error')),
        )
        return

    if data.startswith('published:'):
        parts = data.split(':')
        item_id = int(parts[1])
        channel_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        r = verify_manager_published(item_id, bale_uid, channel_id=channel_id)
        _answer(cq_id, '')
        if r.get('ok'):
            links = r.get('permalinks') or []
            bc.send_message(
                chat_id,
                '✅ انتشار تأیید شد.\n' + '\n'.join(str(x) for x in links if x),
            )
        else:
            bc.send_message(chat_id, 'انتشار تأیید نشد. یک بار دیگر بزنید.')
        return

    if data.startswith('execok:') or data.startswith('execno:'):
        item_id = int(data.split(':')[1])
        ok = data.startswith('execok:')
        r = customer_confirm_execution(item_id, bale_uid, ok)
        _answer(cq_id, '')
        bc.send_message(chat_id, 'ثبت شد.' if r.get('ok') else 'ثبت نشد. یک بار دیگر تلاش کنید.')
        return

    if data.startswith('opok:') or data.startswith('opno:'):
        item_id = int(data.split(':')[1])
        r = operator_resolve(item_id, bale_uid, executed=data.startswith('opok:'))
        _answer(cq_id, '')
        if r.get('ok'):
            bc.send_message(chat_id, 'ثبت شد.')
        else:
            from bot_flow.messages import user_error

            bc.send_message(chat_id, user_error(r.get('error')))
        return

    _answer(cq_id, '')


def _parse_manager_date(text: str):
    text = text.strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    text = text.replace('/', '-')
    parts = text.split('-')
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if 1300 <= y <= 1500:
        try:
            from bot_flow.jalali import parse_jalali_date

            day = parse_jalali_date(y, m, d)
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

    if update.get('pre_checkout_query'):
        try:
            from orders.bale_pay import handle_pre_checkout

            handle_pre_checkout(update['pre_checkout_query'])
        except Exception:
            log.exception('pre_checkout failed')
            qid = (update.get('pre_checkout_query') or {}).get('id')
            if qid:
                bc.answer_pre_checkout_query(qid, False, 'خطای موقت. یک بار دیگر پرداخت کنید.')
        return

    if update.get('callback_query'):
        try:
            handle_callback_query(update['callback_query'])
        except Exception:
            log.exception('callback failed')
        return

    msg = update.get('message') or update.get('edited_message')
    if not msg:
        return

    if msg.get('successful_payment'):
        try:
            from orders.bale_pay import handle_successful_payment

            handle_successful_payment(msg)
        except Exception:
            log.exception('successful_payment failed')
        return

    chat_id = str((msg.get('chat') or {}).get('id') or '')
    from_user = msg.get('from') or {}
    bale_uid = str(from_user.get('id') or '')
    username = from_user.get('username') or ''
    text = msg.get('text') or ''
    norm = normalize_text(text)

    if not chat_id or not bale_uid:
        return

    if norm.startswith('/start') or norm in ('/menu', '/منو'):
        flow.handle_start(chat_id, bale_uid, username)
        return

    if norm in ('/help', '/راهنما'):
        from bot_flow.messages import MSG_HELP

        bc.send_message(chat_id, MSG_HELP, reply_markup=flow.role_keyboard(is_operator=is_operator(bale_uid)))
        return

    if norm in ('/rules', '/law', '/قوانین'):
        bc.send_message(
            chat_id,
            'شرایط و قوانین لینک‌بان را از دکمهٔ «شرایط و قوانین» بخوانید.\n'
            'خلاصه: تبلیغ قمار، رمزارز، محتوای مستهجن، فریب برای گرفتن اطلاعات و ادعای «تضمینی» پذیرفته نمی‌شود. '
            'پول تا پایان مدت انتشار امانی می‌ماند و اگر کانال منتشر نکند برمی‌گردد. '
            'معامله بیرون از لینک‌بان قبول نمی‌شود. حذف خودکار پست فقط تا ۴۸ ساعت بعد از ارسال ممکن است.',
            reply_markup=flow.role_keyboard(is_operator=is_operator(bale_uid)),
        )
        return

    try:
        sess = BotSession.objects.filter(bale_user_id=bale_uid).first()
        if sess and sess.state == 'mgr_edit_date' and norm:
            item_id = (sess.data or {}).get('edit_item_id')
            start = _parse_manager_date(norm)
            if not start or not item_id:
                bc.send_message(chat_id, 'این تاریخ درست نیست. نمونه: ۱۴۰۴/۰۶/۱۵')
                return
            text_out = run_mgr('edit', bale_uid, int(item_id), new_start=start)
            sess.state = 'idle'
            sess.data = {}
            sess.save()
            bc.send_message(chat_id, text_out)
            return
    except Exception:
        log.exception('mgr edit date')

    is_forward = bool(
        msg.get('forward_date')
        or msg.get('forward_from_chat')
        or msg.get('forward_origin')
        or msg.get('forward_from')
    )
    waiting_banner = False
    try:
        sess_now = BotSession.objects.filter(bale_user_id=bale_uid).only('state').first()
        waiting_banner = bool(sess_now and sess_now.state in ('cust_await_banner', 'cust_banner_hub'))
    except Exception:
        log.exception('banner state')
    has_media = bool(msg.get('photo') or msg.get('video') or msg.get('animation') or msg.get('document'))
    if has_media or is_forward or waiting_banner:
        try:
            if cust.handle_banner_message(chat_id, bale_uid, msg):
                return
        except Exception:
            log.exception('banner handle')
            bc.send_message(chat_id, 'بنر را نگرفتم. یک بار دیگر همان عکس یا متن را بفرستید.')
            return

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
            'این پیام را نشناختم. از دکمه‌های منو یکی را بزنید.',
        )
