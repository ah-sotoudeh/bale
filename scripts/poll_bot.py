#!/usr/bin/env python3
"""Long-polling listener for Bale Bot (no public domain / webhook needed).

Setup (once):
    1. Copy config/.env.example to .env in project root
    2. Put BALE_BOT_TOKEN=... in .env
    3. python scripts/poll_bot.py

Windows PowerShell alternative:
    $env:BALE_BOT_TOKEN = "your_token"
    python scripts/poll_bot.py

Press Ctrl+C to stop.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env before importing client (client also loads it, this is belt-and-suspenders)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    load_dotenv(ROOT / 'config' / '.env', override=False)
except ImportError:
    pass

from integrations import bale_client as bc
from integrations.bale_client import _token  # runtime token resolver

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('poll_bot')


def ensure_token() -> None:
    token = _token()
    if not token:
        log.error(
            'BALE_BOT_TOKEN is not set.\n'
            '  • Create a file named .env in the project root with:\n'
            '      BALE_BOT_TOKEN=your_token_here\n'
            '  • Or in PowerShell:  $env:BALE_BOT_TOKEN = "your_token"\n'
            '  • GitHub Secrets only apply inside GitHub Actions, not on your PC.'
        )
        sys.exit(1)
    log.info('Token loaded (length=%d)', len(token))


def prepare_polling() -> None:
    me = bc.get_me()
    if me.get('error') or not me.get('ok', True):
        log.error('getMe failed: %s', me)
        sys.exit(1)

    result = me.get('result') or me
    username = result.get('username') or result.get('first_name') or '?'
    bot_id = result.get('id', '?')
    log.info('Bot OK → id=%s username=@%s', bot_id, username)

    info = bc.get_webhook_info()
    current_url = (info.get('result') or {}).get('url') or info.get('url') or ''
    if current_url:
        log.info('Webhook set to %s — deleting for polling...', current_url)
        log.info('deleteWebhook → %s', bc.delete_webhook())
    else:
        log.info('No webhook set. Ready for polling.')


def handle_update(update: dict) -> None:
    update_id = update.get('update_id')
    log.info('── update_id=%s ──', update_id)

    msg = update.get('message') or update.get('edited_message')
    if msg:
        chat = msg.get('chat') or {}
        chat_id = chat.get('id')
        from_user = msg.get('from') or {}
        text = (msg.get('text') or '').strip()
        user_label = from_user.get('username') or from_user.get('first_name') or from_user.get('id')
        log.info('Message from %s (chat_id=%s): %s', user_label, chat_id, text[:120])

        if not chat_id:
            return

        if text.startswith('/start'):
            reply = (
                'سلام 👋\n'
                'ربات تبلیغات بله آماده‌ست.\n'
                f"شناسه شما: {from_user.get('id')}\n\n"
                'فعلاً در حالت تست (polling) هستیم.'
            )
            resp = bc.send_message(str(chat_id), reply)
            log.info('Replied to /start → %s', 'ok' if not resp.get('error') else resp)
            return

        if text:
            resp = bc.send_message(str(chat_id), f'دریافت شد: {text}')
            log.info('Echo reply → %s', 'ok' if not resp.get('error') else resp)
            return

        log.info('Non-text message ignored for now.')
        return

    cq = update.get('callback_query')
    if cq:
        log.info('Callback from %s: data=%s', (cq.get('from') or {}).get('id'), cq.get('data'))
        return

    if update.get('pre_checkout_query'):
        log.info('pre_checkout_query: %s', update['pre_checkout_query'])
        return

    log.info('Unhandled update keys: %s', list(update.keys()))


def run_polling(timeout: int = 25) -> None:
    offset = None
    log.info('Starting long-polling (timeout=%ss). Message the bot in Bale.', timeout)

    while True:
        try:
            data = bc.get_updates(offset=offset, limit=50, timeout=timeout)

            if data.get('error'):
                log.warning('getUpdates error: %s — retry in 3s', data['error'])
                time.sleep(3)
                continue

            if not data.get('ok', True):
                log.warning('API not ok: %s — retry in 5s', data.get('description') or data)
                time.sleep(5)
                continue

            for upd in data.get('result') or []:
                handle_update(upd)
                uid = upd.get('update_id')
                if uid is not None:
                    offset = uid + 1

        except KeyboardInterrupt:
            log.info('Stopped by user.')
            break
        except Exception as e:
            log.exception('Unexpected error: %s — retry in 5s', e)
            time.sleep(5)


def main() -> None:
    ensure_token()
    prepare_polling()
    run_polling()


if __name__ == '__main__':
    main()
