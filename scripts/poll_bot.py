#!/usr/bin/env python3
"""Long-polling Bale bot with commands + inline keyboard callbacks.

Text commands:
  /approve_1  /reject_1  /paid_1
  (space form also works)

Inline buttons send callback_data:
  approve:1  reject:1  paid:1
"""
from __future__ import annotations

import logging
import os
import re
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

from integrations import bale_client as bc  # noqa: E402
from integrations.bale_client import _token  # noqa: E402
from orders.services import process_manager_response, process_payment_paid  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('poll_bot')

_INVISIBLE = re.compile(
    r'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00a0]'
)

CMD_APPROVE = re.compile(
    r'^/approve(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$',
    re.IGNORECASE,
)
CMD_REJECT = re.compile(
    r'^/reject(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$',
    re.IGNORECASE,
)
CMD_PAID = re.compile(
    r'^/paid(?:@[^\s_]+)?(?:_(\d+)|(?:\s+(\d+))?\s*)$',
    re.IGNORECASE,
)

CB_ACTION = re.compile(r'^(approve|reject|paid):(\d+)$', re.IGNORECASE)


def normalize_text(text: str) -> str:
    if not text:
        return ''
    t = _INVISIBLE.sub('', text)
    t = t.replace('\u00a0', ' ')
    t = t.strip()
    t = re.sub(r'\s+', ' ', t)
    return t


def _cmd_id(match: re.Match) -> str | None:
    return match.group(1) or match.group(2)


def ensure_token() -> None:
    token = _token()
    if not token:
        log.error('BALE_BOT_TOKEN missing. Put it in .env')
        sys.exit(1)
    log.info('Token loaded (length=%d)', len(token))


def prepare_polling() -> None:
    me = bc.get_me()
    if me.get('error') or not me.get('ok', True):
        log.error('getMe failed: %s', me)
        sys.exit(1)
    result = me.get('result') or me
    log.info('Bot OK → id=%s @%s', result.get('id'), result.get('username'))
    log.info('Handlers: commands + inline callbacks (approve:/reject:/paid:)')

    info = bc.get_webhook_info()
    current_url = (info.get('result') or {}).get('url') or ''
    if current_url:
        log.info('Deleting webhook %s', current_url)
        bc.delete_webhook()
    else:
        log.info('No webhook set. Ready for polling.')


def run_approve(chat_id: str, bale_user_id: str, item_id: int) -> str:
    result = process_manager_response(item_id, str(bale_user_id), 'approve')
    log.info('approve item=%s → %s', item_id, result)
    if result.get('ok'):
        return (
            f"✅ آیتم #{item_id} تایید شد.\n"
            f"وضعیت سفارش #{result.get('order_id')}: {result.get('order_status')}"
        )
    return f"❌ خطا: {result.get('error') or result}"


def run_reject(chat_id: str, bale_user_id: str, item_id: int) -> str:
    result = process_manager_response(item_id, str(bale_user_id), 'reject')
    log.info('reject item=%s → %s', item_id, result)
    if result.get('ok'):
        return (
            f"🚫 آیتم #{item_id} رد شد.\n"
            f"وضعیت سفارش #{result.get('order_id')}: {result.get('order_status')}"
        )
    return f"❌ خطا: {result.get('error') or result}"


def run_paid(order_id: int) -> str:
    result = process_payment_paid(order_id)
    log.info('paid order=%s → %s', order_id, result)
    if result.get('ok'):
        return f"💳 سفارش #{order_id} پرداخت‌شده ثبت شد. وضعیت: {result.get('order_status')}"
    return f"❌ خطا: {result.get('error') or result}"


def handle_text_command(chat_id: str, bale_user_id: str, text: str) -> bool:
    raw = text
    text = normalize_text(text)
    log.info('CMD parse raw=%r normalized=%r user=%s', raw, text, bale_user_id)

    m = CMD_APPROVE.match(text)
    if m:
        sid = _cmd_id(m)
        if not sid:
            bc.send_message(str(chat_id), 'فرمت: /approve_1  یا  /approve 1')
            return True
        bc.send_message(str(chat_id), run_approve(str(chat_id), str(bale_user_id), int(sid)))
        return True

    m = CMD_REJECT.match(text)
    if m:
        sid = _cmd_id(m)
        if not sid:
            bc.send_message(str(chat_id), 'فرمت: /reject_1  یا  /reject 1')
            return True
        bc.send_message(str(chat_id), run_reject(str(chat_id), str(bale_user_id), int(sid)))
        return True

    m = CMD_PAID.match(text)
    if m:
        sid = _cmd_id(m)
        if not sid:
            bc.send_message(str(chat_id), 'فرمت: /paid_1  یا  /paid 1')
            return True
        bc.send_message(str(chat_id), run_paid(int(sid)))
        return True

    return False


def handle_callback_query(cq: dict) -> None:
    cq_id = cq.get('id')
    data = (cq.get('data') or '').strip()
    from_user = cq.get('from') or {}
    bale_uid = from_user.get('id')
    msg = cq.get('message') or {}
    chat = msg.get('chat') or {}
    chat_id = chat.get('id')

    log.info('callback_query id=%s data=%r user=%s', cq_id, data, bale_uid)

    m = CB_ACTION.match(data)
    if not m:
        if cq_id:
            bc.answer_callback_query(str(cq_id), text='دستور ناشناخته', show_alert=False)
        return

    action, sid = m.group(1).lower(), int(m.group(2))

    if action == 'approve':
        text = run_approve(str(chat_id), str(bale_uid), sid)
        toast = 'تایید شد' if text.startswith('✅') else 'خطا'
    elif action == 'reject':
        text = run_reject(str(chat_id), str(bale_uid), sid)
        toast = 'رد شد' if text.startswith('🚫') else 'خطا'
    else:  # paid
        text = run_paid(sid)
        toast = 'پرداخت ثبت شد' if text.startswith('💳') else 'خطا'

    if cq_id:
        bc.answer_callback_query(str(cq_id), text=toast, show_alert=False)

    if chat_id:
        bc.send_message(str(chat_id), text)


def handle_update(update: dict) -> None:
    log.info('── update_id=%s ──', update.get('update_id'))

    if update.get('callback_query'):
        try:
            handle_callback_query(update['callback_query'])
        except Exception:
            log.exception('callback_query handler failed')
        return

    msg = update.get('message') or update.get('edited_message')
    if msg:
        chat = msg.get('chat') or {}
        chat_id = chat.get('id')
        from_user = msg.get('from') or {}
        text = (msg.get('text') or '')
        bale_uid = from_user.get('id')
        log.info('From %s text=%r', bale_uid, text)

        if not chat_id:
            return

        norm = normalize_text(text)
        if norm.startswith('/start'):
            bc.send_message(
                str(chat_id),
                'سلام 👋 ربات تبلیغات بله\n'
                f"شناسه شما: {bale_uid}\n\n"
                'دستورات:\n'
                '/approve_1\n'
                '/reject_1\n'
                '/paid_1\n\n'
                'یا از دکمه‌های زیر پیام سفارش استفاده کنید.',
            )
            return

        if norm and handle_text_command(str(chat_id), str(bale_uid), text):
            return

        if norm:
            bc.send_message(str(chat_id), f'دریافت شد: {norm}')
        return

    if update.get('pre_checkout_query'):
        log.info('pre_checkout_query: %s', update['pre_checkout_query'])
        return

    log.info('Unhandled keys: %s', list(update.keys()))


def run_polling(timeout: int = 25) -> None:
    offset = None
    log.info('Polling… (Ctrl+C to stop)')
    while True:
        try:
            data = bc.get_updates(offset=offset, limit=50, timeout=timeout)
            if data.get('error'):
                log.warning('getUpdates error: %s', data['error'])
                time.sleep(3)
                continue
            if not data.get('ok', True):
                log.warning('API not ok: %s', data.get('description') or data)
                time.sleep(5)
                continue
            for upd in data.get('result') or []:
                try:
                    handle_update(upd)
                except Exception:
                    log.exception('handle_update failed')
                uid = upd.get('update_id')
                if uid is not None:
                    offset = uid + 1
        except KeyboardInterrupt:
            log.info('Stopped.')
            break
        except Exception as e:
            log.exception('loop error: %s', e)
            time.sleep(5)


def main() -> None:
    ensure_token()
    prepare_polling()
    run_polling()


if __name__ == '__main__':
    main()
