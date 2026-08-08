#!/usr/bin/env python3
"""Long-polling Bale bot: conversation flow + order commands + free-days calendar."""
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

from bot_flow import handlers as flow  # noqa: E402
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
CB_ORDER_MGR = re.compile(r'^(approve|reject|paid):(\d+)$', re.IGNORECASE)


def normalize_text(text: str) -> str:
    if not text:
        return ''
    t = _INVISIBLE.sub('', text)
    t = t.replace('\u00a0', ' ')
    t = t.strip()
    return re.sub(r'\s+', ' ', t)


def _cmd_id(match: re.Match) -> str | None:
    return match.group(1) or match.group(2)


def ensure_token() -> None:
    token = _token()
    if not token:
        log.error('BALE_BOT_TOKEN missing')
        sys.exit(1)
    log.info('Token loaded (length=%d)', len(token))


def prepare_polling() -> None:
    me = bc.get_me()
    if me.get('error') or not me.get('ok', True):
        log.error('getMe failed: %s', me)
        sys.exit(1)
    result = me.get('result') or me
    log.info('Bot OK → id=%s @%s', result.get('id'), result.get('username'))
    log.info('Flows: /start /free + order callbacks')

    info = bc.get_webhook_info()
    current_url = (info.get('result') or {}).get('url') or ''
    if current_url:
        bc.delete_webhook()
        log.info('Webhook deleted')
    else:
        log.info('No webhook set')


def run_approve(bale_user_id: str, item_id: int) -> str:
    result = process_manager_response(item_id, str(bale_user_id), 'approve')
    log.info('approve item=%s → %s', item_id, result)
    if result.get('ok'):
        return (
            f"✅ آیتم #{item_id} تایید شد.\n"
            f"وضعیت سفارش #{result.get('order_id')}: {result.get('order_status')}"
        )
    return f"❌ خطا: {result.get('error') or result}"


def run_reject(bale_user_id: str, item_id: int) -> str:
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
        return f"💳 سفارش #{order_id} پرداخت‌شده. وضعیت: {result.get('order_status')}"
    return f"❌ خطا: {result.get('error') or result}"


def handle_legacy_commands(chat_id: str, bale_user_id: str, text: str) -> bool:
    m = CMD_APPROVE.match(text)
    if m:
        sid = _cmd_id(m)
        if not sid:
            bc.send_message(str(chat_id), 'فرمت: /approve_1')
            return True
        bc.send_message(str(chat_id), run_approve(str(bale_user_id), int(sid)))
        return True
    m = CMD_REJECT.match(text)
    if m:
        sid = _cmd_id(m)
        if not sid:
            bc.send_message(str(chat_id), 'فرمت: /reject_1')
            return True
        bc.send_message(str(chat_id), run_reject(str(bale_user_id), int(sid)))
        return True
    m = CMD_PAID.match(text)
    if m:
        sid = _cmd_id(m)
        if not sid:
            bc.send_message(str(chat_id), 'فرمت: /paid_1')
            return True
        bc.send_message(str(chat_id), run_paid(int(sid)))
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

    log.info('callback data=%r user=%s @%s', data, bale_uid, username)

    if flow.try_handle_callback(
        chat_id,
        bale_uid,
        data,
        cq_id=str(cq_id) if cq_id else None,
        username=username,
    ):
        return

    m = CB_ORDER_MGR.match(data)
    if m:
        action, sid = m.group(1).lower(), int(m.group(2))
        if action == 'approve':
            text = run_approve(bale_uid, sid)
            toast = 'تایید شد' if text.startswith('✅') else 'خطا'
        elif action == 'reject':
            text = run_reject(bale_uid, sid)
            toast = 'رد شد' if text.startswith('🚫') else 'خطا'
        else:
            text = run_paid(sid)
            toast = 'پرداخت ثبت شد' if text.startswith('💳') else 'خطا'
        if cq_id:
            bc.answer_callback_query(str(cq_id), text=toast)
        if chat_id:
            bc.send_message(chat_id, text)
        return

    if cq_id:
        bc.answer_callback_query(str(cq_id), text='دستور ناشناخته')


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
        log.info('Unhandled keys: %s', list(update.keys()))
        return

    chat_id = str((msg.get('chat') or {}).get('id') or '')
    from_user = msg.get('from') or {}
    bale_uid = str(from_user.get('id') or '')
    username = from_user.get('username') or ''
    text = msg.get('text') or ''
    norm = normalize_text(text)
    log.info('From %s @%s text=%r', bale_uid, username, text)

    if not chat_id or not bale_uid:
        return

    if norm.startswith('/start'):
        flow.handle_start(chat_id, bale_uid, username)
        return

    if handle_legacy_commands(chat_id, bale_uid, norm):
        return

    if flow.try_handle_text(chat_id, bale_uid, text):
        return

    if norm:
        bc.send_message(
            chat_id,
            'دستورات:\n'
            '/start — شروع و انتخاب نقش\n'
            '/free — روزهای خالی کانال‌های شما\n'
            '/approve_1 /reject_1 /paid_1 — سفارش',
        )


def run_polling(timeout: int = 25) -> None:
    offset = None
    log.info('Polling…')
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
            log.exception('loop: %s', e)
            time.sleep(5)


def main() -> None:
    ensure_token()
    prepare_polling()
    run_polling()


if __name__ == '__main__':
    main()
