#!/usr/bin/env python3
"""شبیه‌سازی مقایسهٔ روش‌های انتشار بنر روی @linktest

جریان:
1) یک بنر (عکس/فیلم/فایل) برای لینک‌ساز بازارسال یا ارسال کن
2) اسکریپت زمان اجرا را روی حدود N ثانیهٔ آینده می‌گذارد
3) هم‌زمان:
   الف) لینک‌ساز → forward با نقل‌قول به کانال
   ب) لینک‌ساز → copyMessage بدون نقل‌قول به کانال
   ج) لینک‌یار → download/upload (send) به کانال
4) برای هر پست موفق، چند کاندید پیوند مطلب (ble.ir) ساخته و به چت لینک‌ساز فرستاده می‌شود

اجرا (PowerShell — channel را quote کنید):
  python scripts/sim_publish_compare.py --delay 60 --channel "@linktest"
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
from typing import Any, Dict, List, Optional, Tuple

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


def normalize_date_ms(date_val: Optional[int]) -> Optional[int]:
    """Bot API date is usually seconds; aiobale uses milliseconds."""
    if date_val is None:
        return None
    d = int(date_val)
    # timestamps before year ~2001 in ms would be < 1e12; seconds now are ~1.7e9
    if d < 10_000_000_000:  # clearly seconds
        return d * 1000
    return d


def build_message_link_candidates(
    channel_username: str, message_id: int, date_val: Optional[int]
) -> List[str]:
    uname = channel_username.lstrip('@')
    mid = int(message_id)
    out: List[str] = []
    date_ms = normalize_date_ms(date_val)
    if date_ms is not None:
        out.append(f'https://ble.ir/{uname}/{mid}/{date_ms}')
        # also seconds form (in case client expects sec)
        out.append(f'https://ble.ir/{uname}/{mid}/{date_ms // 1000}')
    out.append(f'https://ble.ir/{uname}/{mid}')
    # unique preserve order
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def extract_bot_message_meta(api_result: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """Extract message_id and date from Bot API forward/copy response."""
    if not isinstance(api_result, dict):
        return None, None
    res = api_result.get('result')
    mid = None
    date = None
    if isinstance(res, dict):
        mid = res.get('message_id')
        date = res.get('date') or res.get('forward_date')
    elif isinstance(res, int):
        mid = res
    # some Bale variants: result.message_id at top
    if mid is None:
        mid = api_result.get('message_id')
    if date is None:
        date = api_result.get('date')
    return (int(mid) if mid is not None else None, int(date) if date is not None else None)


def extract_file_id(msg: dict) -> Tuple[Optional[str], str, Optional[str]]:
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
    uname = channel.lstrip('@')

    bc.send_message(
        chat_id,
        (
            f'✅ بنر دریافت شد (id={msg_id}, kind={banner["kind"]})\n'
            f'زمان انتشار آزمایشی: حدود {run_at.strftime("%H:%M:%S")} '
            f'(+{delay_sec} ثانیه)\n\n'
            f'روش‌ها:\n'
            f'۱) لینک‌ساز forward با نقل‌قول → {channel}\n'
            f'۲) لینک‌ساز copyMessage بدون نقل‌قول → {channel}\n'
            f'۳) لینک‌یار send (دانلود/آپلود) → {channel}\n'
            f'۴) ساخت پیوند مطلب برای پست‌های موفق'
        ),
    )

    local_file: Optional[Path] = None
    try:
        local_file = download_banner_file(banner['file_id'], banner['kind'])
    except Exception as e:
        log.exception('download for linkyar path failed early: %s', e)
        bc.send_message(chat_id, f'⚠️ دانلود فایل برای مسیر لینک‌یار الان fail شد: {e}')

    fwd_ly = bc.forward_message(linkyar_uid, chat_id, msg_id)
    log.info('forward to linkyar user %s → %s', linkyar_uid, fwd_ly)
    bc.send_message(
        chat_id,
        f'بنر برای لینک‌یار (user {linkyar_uid}) فوروارد شد: '
        f'{"OK" if fwd_ly.get("ok") else fwd_ly}',
    )

    wait = max(0, delay_sec)
    log.info('waiting %s seconds until publish…', wait)
    left = wait
    while left > 0:
        step = min(30, left)
        time.sleep(step)
        left -= step
        if left > 0:
            log.info('… %ss remaining', left)

    # fallback date if API omits it
    fallback_date_sec = int(time.time())

    # ۱) bot forward با نقل‌قول
    log.info('=== 1) bot forwardMessage (با نقل‌قول) ===')
    r1 = bc.forward_message(channel, chat_id, msg_id)
    log.info('forward full result: %s', r1)
    mid1, date1 = extract_bot_message_meta(r1)
    if mid1 and not date1:
        date1 = fallback_date_sec
    log.info('forward meta mid=%s date=%s', mid1, date1)

    # ۲) bot copy بدون نقل‌قول
    log.info('=== 2) bot copyMessage (بدون نقل‌قول) ===')
    r2 = bc.copy_message(channel, chat_id, msg_id, caption=banner.get('caption') or None)
    log.info('copy full result: %s', r2)
    mid2, date2 = extract_bot_message_meta(r2)
    if mid2 and not date2:
        # copy often returns only message_id — reuse forward date or now
        date2 = date1 or fallback_date_sec
    log.info('copy meta mid=%s date=%s', mid2, date2)

    # ۳) linkyar download+upload send
    log.info('=== 3) linkyar send (download/upload) ===')
    r3: Dict[str, Any] = {'ok': False}
    if local_file and local_file.exists():
        r3 = ly.send_local_file_to_channel(
            channel,
            str(local_file),
            caption=banner.get('caption') or '',
            kind=banner['kind'],
        )
        log.info('linkyar send: %s', r3)
    else:
        r3 = {'ok': False, 'error': 'no local file for upload'}

    mid3 = r3.get('message_id')
    date3 = r3.get('date')

    # ۴) پیوندها
    link_sections: List[str] = []
    if mid1:
        cands = build_message_link_candidates(uname, mid1, date1)
        link_sections.append('🔗 پیوند forward (با نقل‌قول) mid=%s:' % mid1)
        link_sections.extend(cands)
        link_sections.append('')
    if mid2:
        cands = build_message_link_candidates(uname, mid2, date2)
        link_sections.append('🔗 پیوند copy (بدون نقل‌قول) mid=%s:' % mid2)
        link_sections.extend(cands)
        link_sections.append('')
    if r3.get('ok') and mid3:
        cands = build_message_link_candidates(uname, int(mid3), date3)
        link_sections.append('🔗 پیوند linkyar upload mid=%s:' % mid3)
        link_sections.extend(cands)
        link_sections.append('')

    lines = [
        '📊 نتیجه شبیه‌سازی انتشار',
        f'کانال: {channel}',
        '',
        f'۱) forward با نقل‌قول: {"✅" if r1.get("ok") else "❌"} mid={mid1} date={date1}',
        f'۲) copy بدون نقل‌قول: {"✅" if r2.get("ok") else "❌"} mid={mid2} date={date2}',
        f'۳) linkyar upload: {"✅" if r3.get("ok") else "❌"} mid={mid3} date={date3}',
        '',
    ]
    if link_sections:
        lines += ['کاندیدهای پیوند مطلب (یکی را در بله باز کن تا فرمت درست مشخص شود):', '']
        lines += link_sections
    if not r3.get('ok'):
        lines += [f'خطای لینک‌یار: {r3.get("error") or r3}']

    report = '\n'.join(lines)
    log.info('REPORT\n%s', report)
    bc.send_message(chat_id, report[:3500])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--delay', type=int, default=180, help='seconds until publish (default 180)')
    ap.add_argument('--channel', default=os.environ.get('REFERENCE_CHANNEL', '@linktest'))
    ap.add_argument('--timeout', type=int, default=600, help='wait for banner seconds')
    args = ap.parse_args()

    # normalize channel: PowerShell may strip @
    ch = args.channel.strip()
    if ch and not ch.startswith('@') and not ch.lstrip('-').isdigit():
        ch = '@' + ch

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
    run_scheduled(banner, ch, args.delay)


if __name__ == '__main__':
    main()
