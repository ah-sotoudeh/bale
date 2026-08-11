#!/usr/bin/env python3
"""شبیه‌سازی مقایسهٔ روش‌های انتشار بنر روی @linktest

جریان:
1) یک بنر (عکس/فیلم/فایل) برای لینک‌ساز بازارسال یا ارسال کن
2) اسکریپت زمان اجرا را روی حدود ۳ دقیقهٔ آینده می‌گذارد
3) هم‌زمان:
   الف) لینک‌ساز → forward با نقل‌قول به @linktest
   ب) لینک‌ساز → copyMessage بدون نقل‌قول به @linktest
   ج) بنر برای لینک‌یار فوروارد می‌شود؛ لینک‌یار با download+upload (send) به @linktest
      سپس پیوند مطلب می‌سازد و برای چت لینک‌ساز می‌فرستد

اجرا:
  python scripts/sim_publish_compare.py
  python scripts/sim_publish_compare.py --delay 180 --channel @linktest
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
from integrations import linkyar_client as ly  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('sim_publish')


def _linkyar_user_id() -> str:
    return (
        os.environ.get('LINKYAR_BALE_USER_ID', '')
        or os.environ.get('LINKYAR_USER_ID', '')
        or '1164810718'
    ).strip()


def build_message_link(channel_username: str, message_id: int, date_ms: int) -> str:
    uname = channel_username.lstrip('@')
    return f'https://ble.ir/{uname}/{message_id}/{date_ms}'


def extract_file_id(msg: dict) -> Tuple[Optional[str], str, Optional[str]]:
    """Returns (file_id, kind, caption). kind: photo|video|document"""
    caption = msg.get('caption') or msg.get('text') or ''
    if msg.get('photo'):
        photos = msg['photo']
        best = photos[-1] if isinstance(photos, list) else photos
        return best.get('file_id'), 'photo', caption
    if msg.get('video'):
        return (msg['video'] or {}).get('file_id'), 'video', caption
    if msg.get('document'):
        return (msg['document'] or {}).get('file_id'), 'document', caption
    return None, '', caption


def wait_for_banner(timeout_sec: int = 600) -> Dict[str, Any]:
    """Long-poll until a media message arrives for the bot."""
    info = bc.get_webhook_info()
    url = (info.get('result') or {}).get('url') or ''
    if url:
        bc.delete_webhook()
        log.info('webhook cleared')

    me = bc.get_me()
    log.info('لینک‌ساز: %s', (me.get('result') or me))
    log.info('یک بنر (عکس/فیلم/فایل) را برای لینک‌ساز بفرست یا بازارسال کن…')

    offset = None
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        data = bc.get_updates(offset=offset, limit=20, timeout=25)
        if data.get('error') or not data.get('ok', True):
            time.sleep(2)
            continue
        for upd in data.get('result') or []:
            uid = upd.get('update_id')
            if uid is not None:
                offset = uid + 1
            msg = upd.get('message') or upd.get('channel_post')
            if not msg:
                continue
            file_id, kind, caption = extract_file_id(msg)
            if not file_id:
                chat_id = str((msg.get('chat') or {}).get('id') or '')
                if chat_id and (msg.get('text') or '').strip():
                    bc.send_message(
                        chat_id,
                        'برای شبیه‌سازی یک بنر تصویری/ویدیویی بفرست (نه فقط متن).',
                    )
                continue
            return {
                'message': msg,
                'chat_id': str((msg.get('chat') or {}).get('id')),
                'message_id': int(msg['message_id']),
                'file_id': file_id,
                'kind': kind,
                'caption': caption or '',
                'from_user': str((msg.get('from') or {}).get('id') or ''),
            }
    raise SystemExit('زمان انتظار برای بنر تمام شد')


def download_banner_file(file_id: str, kind: str) -> Path:
    meta = bc.get_file(file_id)
    if meta.get('error') or not meta.get('ok', True):
        raise RuntimeError(f'getFile failed: {meta}')
    result = meta.get('result') or {}
    path = result.get('file_path')
    if not path:
        raise RuntimeError(f'no file_path in getFile: {meta}')
    content = bc.download_file_bytes(path)
    if not content:
        raise RuntimeError('empty download')
    suffix = {
        'photo': '.jpg',
        'video': '.mp4',
        'document': Path(path).suffix or '.bin',
    }.get(kind, '.bin')
    tmp = Path(tempfile.gettempdir()) / f'bale_sim_banner{suffix}'
    tmp.write_bytes(content)
    log.info('downloaded %s bytes → %s', len(content), tmp)
    return tmp


def run_scheduled(
    banner: Dict[str, Any],
    channel: str,
    delay_sec: int,
) -> None:
    chat_id = banner['chat_id']
    msg_id = banner['message_id']
    run_at = datetime.now() + timedelta(seconds=delay_sec)
    linkyar_uid = _linkyar_user_id()

    bc.send_message(
        chat_id,
        (
            f'✅ بنر دریافت شد (id={msg_id}, kind={banner["kind"]})\n'
            f'زمان انتشار آزمایشی: حدود {run_at.strftime("%H:%M:%S")} '
            f'(+{delay_sec} ثانیه)\n\n'
            f'روش‌ها:\n'
            f'۱) لینک‌ساز forward با نقل‌قول → {channel}\n'
            f'۲) لینک‌ساز copyMessage بدون نقل‌قول → {channel}\n'
            f'۳) فوروارد به لینک‌یار + send (دانلود/آپلود) → {channel}\n'
            f'   سپس پیوند مطلب برای همین چت'
        ),
    )

    # آماده‌سازی فایل برای لینک‌یار از همین الان
    local_file: Optional[Path] = None
    try:
        local_file = download_banner_file(banner['file_id'], banner['kind'])
    except Exception as e:
        log.exception('download for linkyar path failed early: %s', e)
        bc.send_message(chat_id, f'⚠️ دانلود فایل برای مسیر لینک‌یار الان fail شد: {e}')

    # فوروارد فوری بنر به لینک‌یار (تا در اینباکسش باشد)
    fwd_ly = bc.forward_message(linkyar_uid, chat_id, msg_id)
    log.info('forward to linkyar user %s → %s', linkyar_uid, fwd_ly)
    bc.send_message(
        chat_id,
        f'بنر برای لینک‌یار (user {linkyar_uid}) فوروارد شد: '
        f'{"OK" if fwd_ly.get("ok") else fwd_ly}',
    )

    wait = max(0, delay_sec)
    log.info('waiting %s seconds until publish…', wait)
    # countdown every 30s
    left = wait
    while left > 0:
        step = min(30, left)
        time.sleep(step)
        left -= step
        if left > 0:
            log.info('… %ss remaining', left)

    results: Dict[str, Any] = {}

    # ۱) bot forward با نقل‌قول
    log.info('=== 1) bot forwardMessage (با نقل‌قول) ===')
    r1 = bc.forward_message(channel, chat_id, msg_id)
    results['bot_forward_quote'] = r1
    mid1 = ((r1.get('result') or {}) if isinstance(r1, dict) else {}).get('message_id')
    date1 = ((r1.get('result') or {}) if isinstance(r1, dict) else {}).get('date')
    log.info('result: ok=%s message_id=%s', r1.get('ok'), mid1)

    # ۲) bot copy بدون نقل‌قول
    log.info('=== 2) bot copyMessage (بدون نقل‌قول) ===')
    r2 = bc.copy_message(channel, chat_id, msg_id, caption=banner.get('caption') or None)
    results['bot_copy_no_quote'] = r2
    mid2 = None
    if isinstance(r2, dict):
        res2 = r2.get('result')
        if isinstance(res2, dict):
            mid2 = res2.get('message_id')
        elif isinstance(res2, int):
            mid2 = res2
    log.info('result: ok=%s message_id=%s', r2.get('ok'), mid2)

    # ۳) linkyar download+upload send
    log.info('=== 3) linkyar send (download/upload) ===')
    r3: Dict[str, Any] = {'ok': False}
    permalink = None
    if local_file and local_file.exists():
        r3 = ly.send_local_file_to_channel(
            channel,
            str(local_file),
            caption=banner.get('caption') or '',
            kind=banner['kind'],
        )
        log.info('linkyar send: %s', r3)
        if r3.get('ok') and r3.get('message_id') and r3.get('date'):
            uname = channel.lstrip('@')
            permalink = build_message_link(uname, int(r3['message_id']), int(r3['date']))
            log.info('permalink: %s', permalink)
    else:
        r3 = {'ok': False, 'error': 'no local file for upload'}

    results['linkyar_upload'] = r3
    results['permalink'] = permalink

    # گزارش به چت لینک‌ساز
    lines = [
        '📊 نتیجه شبیه‌سازی انتشار',
        f'کانال: {channel}',
        '',
        f'۱) forward با نقل‌قول: {"✅" if r1.get("ok") else "❌"} mid={mid1}',
        f'۲) copy بدون نقل‌قول: {"✅" if r2.get("ok") else "❌"} mid={mid2}',
        f'۳) linkyar upload: {"✅" if r3.get("ok") else "❌"} mid={r3.get("message_id")} date={r3.get("date")}',
    ]
    if permalink:
        lines += ['', f'🔗 پیوند مطلب (مسیر لینک‌یار):', permalink]
    if not r3.get('ok'):
        lines += ['', f'خطای لینک‌یار: {r3.get("error") or r3}']

    bc.send_message(chat_id, '\n'.join(lines))
    log.info('done. full results keys=%s', list(results.keys()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--delay', type=int, default=180, help='seconds until publish (default 180)')
    ap.add_argument('--channel', default=os.environ.get('REFERENCE_CHANNEL', '@linktest'))
    ap.add_argument('--timeout', type=int, default=600, help='wait for banner seconds')
    args = ap.parse_args()

    if not bc._token():
        log.error('BALE_BOT_TOKEN missing')
        sys.exit(1)
    if not ly.user_token():
        log.warning('BALE_TOKEN missing — مسیر لینک‌یار کار نمی‌کند')

    banner = wait_for_banner(timeout_sec=args.timeout)
    log.info(
        'banner ok chat=%s msg=%s kind=%s',
        banner['chat_id'],
        banner['message_id'],
        banner['kind'],
    )
    run_scheduled(banner, args.channel, args.delay)


if __name__ == '__main__':
    main()
