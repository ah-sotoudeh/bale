#!/usr/bin/env python3
"""Probe Bale Bot API capabilities on a channel (default @linktest).

Tests: sendMessage, deleteMessage, scheduleMessage (if any), getChat, editMessageText.
Requires BALE_BOT_TOKEN and bot admin in the channel.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / '.env')
    load_dotenv(ROOT / 'config' / '.env')
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')
os.environ.setdefault('USE_SQLITE', '1')

import django

django.setup()

import requests
from integrations.bale_client import _bot_url, _token

CHANNEL = os.environ.get('PROBE_CHANNEL', '@linktest')


def call(method: str, payload: dict | None = None, params: dict | None = None) -> dict:
    url = _bot_url(method)
    try:
        if payload is not None:
            r = requests.post(url, json=payload, timeout=20)
        else:
            r = requests.get(url, params=params or {}, timeout=20)
        try:
            data = r.json()
        except Exception:
            data = {'raw': r.text[:500], 'status_code': r.status_code}
        data['_http'] = r.status_code
        return data
    except Exception as e:
        return {'error': str(e)}


def main() -> None:
    if not _token():
        print('BALE_BOT_TOKEN missing')
        sys.exit(1)

    print('=== getMe ===')
    print(json.dumps(call('getMe'), ensure_ascii=False, indent=2)[:800])

    print('\n=== getChat', CHANNEL, '===')
    print(json.dumps(call('getChat', params={'chat_id': CHANNEL}), ensure_ascii=False, indent=2)[:1200])

    print('\n=== sendMessage (probe) ===')
    sent = call(
        'sendMessage',
        {
            'chat_id': CHANNEL,
            'text': '🔬 تست بازو — پیام آزمایشی (قابل حذف)',
        },
    )
    print(json.dumps(sent, ensure_ascii=False, indent=2)[:1200])
    msg_id = None
    if sent.get('ok') and sent.get('result'):
        msg_id = sent['result'].get('message_id')

    print('\n=== scheduleMessage (probe) ===')
    # Telegram-style schedule is NOT standard Bot API; Bale may differ
    import time as _t

    send_at = int(_t.time()) + 120
    for body in (
        {'chat_id': CHANNEL, 'text': 'زمان‌بندی تست', 'schedule_date': send_at},
        {'chat_id': CHANNEL, 'text': 'زمان‌بندی تست', 'send_at': send_at},
        {'chat_id': CHANNEL, 'payload': {'text': 'x'}, 'send_at': send_at},
    ):
        sch = call('scheduleMessage', body)
        print('body keys', list(body.keys()), '→', json.dumps(sch, ensure_ascii=False)[:400])

    print('\n=== sendMessage with future? (unsupported usually) ===')
    # no-op documentation

    if msg_id:
        print('\n=== editMessageText ===')
        ed = call(
            'editMessageText',
            {
                'chat_id': CHANNEL,
                'message_id': msg_id,
                'text': '🔬 تست بازو — ویرایش شد',
            },
        )
        print(json.dumps(ed, ensure_ascii=False, indent=2)[:800])

        print('\n=== deleteMessage ===')
        time.sleep(1)
        dl = call('deleteMessage', {'chat_id': CHANNEL, 'message_id': msg_id})
        print(json.dumps(dl, ensure_ascii=False, indent=2)[:800])
    else:
        print('No message_id; skip edit/delete')

    print('\n=== Done ===')
    print(
        'Summary expectations:\n'
        '- sendMessage/deleteMessage: should work if bot is channel admin\n'
        '- scheduleMessage: often unsupported on Bale Bot API (use our own scheduler + send)\n'
        '- auto-delete after 24h: implement with job calling deleteMessage, not native TTL'
    )


if __name__ == '__main__':
    main()
