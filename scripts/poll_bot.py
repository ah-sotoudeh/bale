#!/usr/bin/env python3
"""Long-polling Bale bot with real order commands.

Commands:
  /start
  /approve <order_item_id>
  /reject <order_item_id>
  /paid <order_id>

Setup:
  .env with BALE_BOT_TOKEN
  python scripts/demo_order_flow.py
  python scripts/poll_bot.py
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

# Invisible / bidi marks Bale or mobile keyboards sometimes inject
_INVISIBLE = re.compile(
    r'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00a0]'
)

CMD_APPROVE = re.compile(
    r'^/approve(?:@[^\s]+)?(?:\s+|$)(\d+)?\s*$', re.IGNORECASE
)
CMD_REJECT = re.compile(
    r'^/reject(?:@[^\s]+)?(?:\s+|$)(\d+)?\s*$', re.IGNORECASE
)
CMD_PAID = re.compile(
    r'^/paid(?:@[^\s]+)?(?:\s+|$)(\d+)?\s*$', re.IGNORECASE
)


def normalize_text(text: str) -> str:
    if not text:
        return ''
    t = _INVISIBLE.sub('', text)
    t = t.replace('\u00a0', ' ')
    t = t.strip()
    # collapse whitespace
    t = re.sub(r'\s+', ' ', t)
    return t


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
    log.info('Command handlers active: /approve /reject /paid')

    info = bc.get_webhook_info()
    current_url = (info.get('result') or {}).get('url') or ''
    if current_url:
        log.info('Deleting webhook %s', current_url)
        bc.delete_webhook()
    else:
        log.info('No webhook set. Ready for polling.')


def handle_text_command(chat_id: str, bale_user_id: str, text: str) -> bool:
    """Return True if a command was handled (including help for incomplete cmds)."""
    raw = text
    text = normalize_text(text)
    log.info('CMD parse raw=%r normalized=%r user=%s', raw, text, bale_user_id)

    m = CMD_APPROVE.match(text)
    if m:
        if not m.group(1):
            bc.send_message(str(chat_id), 'فرمت: /approve <شماره_آیتم>\nمثال: /approve 1')
            return True
        item_id = int(m.group(1))
        result = process_manager_response(item_id, str(bale_user_id), 'approve')
        log.info('approve item=%s → %s', item_id, result)
        if result.get('ok'):
            msg = (
                f"✅ آیتم #{item_id} تایید شد.\n"
                f"وضعیت سفارش #{result.get('order_id')}: {result.get('order_status')}"
            )
        else:
            msg = f"❌ خطا: {result.get('error') or result}"
        bc.send_message(str(chat_id), msg)
        return True

    m = CMD_REJECT.match(text)
    if m:
        if not m.group(1):
            bc.send_message(str(chat_id), 'فرمت: /reject <شماره_آیتم>\nمثال: /reject 1')
            return True
        item_id = int(m.group(1))
        result = process_manager_response(item_id, str(bale_user_id), 'reject')
        log.info('reject item=%s → %s', item_id, result)
        if result.get('ok'):
            msg = (
                f"🚫 آیتم #{item_id} رد شد.\n"
                f"وضعیت سفارش #{result.get('order_id')}: {result.get('order_status')}"
            )
        else:
            msg = f"❌ خطا: {result.get('error') or result}"
        bc.send_message(str(chat_id), msg)
        return True

    m = CMD_PAID.match(text)
    if m:
        if not m.group(1):
            bc.send_message(str(chat_id), 'فرمت: /paid <شماره_سفارش>\nمثال: /paid 1')
            return True
        order_id = int(m.group(1))
        result = process_payment_paid(order_id)
        log.info('paid order=%s → %s', order_id, result)
        if result.get('ok'):
            msg = f"💳 سفارش #{order_id} پرداخت‌شده ثبت شد. وضعیت: {result.get('order_status')}"
        else:
            msg = f"❌ خطا: {result.get('error') or result}"
        bc.send_message(str(chat_id), msg)
        return True

    return False


def handle_update(update: dict) -> None:
    log.info('── update_id=%s ──', update.get('update_id'))

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
                '/approve 1\n'
                '/reject 1\n'
                '/paid 1',
            )
            return

        if norm and handle_text_command(str(chat_id), str(bale_uid), text):
            return

        if norm:
            bc.send_message(str(chat_id), f'دریافت شد: {norm}')
        return

    if update.get('callback_query'):
        log.info('callback_query: %s', update['callback_query'])
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
