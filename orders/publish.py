"""Scheduled publish by mode + daily admin health check + permalink recovery."""
from __future__ import annotations

import json
import logging
import os
import time
import threading
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from channels_app.models import Channel, ChannelGroup, Tariff
from integrations import bale_client as bc
from integrations import linkyar_client as ly
from orders.models import OrderItem
from wallet.services import (
    OPERATOR_BALE_ID,
    apply_manager_penalty,
    credit_customer_refund,
    credit_manager_for_execution,
)

logger = logging.getLogger(__name__)


def _bot_numeric_id() -> Optional[int]:
    me = bc.get_me()
    result = me.get('result') or me
    bid = result.get('id')
    try:
        return int(bid) if bid is not None else None
    except (TypeError, ValueError):
        return None


def _linkyar_numeric_id() -> Optional[int]:
    try:
        me = ly.get_me()
    except Exception:
        logger.warning('linkyar get_me failed')
        return None
    if not isinstance(me, dict) or not me.get('ok'):
        return None
    try:
        return int(me.get('user_id')) if me.get('user_id') is not None else None
    except (TypeError, ValueError):
        return None


def channel_ref(ch: Channel) -> str:
    """مرجع کانال: ترجیح @username از link (دقیق)، بعد peer عددی.

    peer_id اشتباه در DB قبلاً باعث resolve به کانال غلط می‌شد.
    """
    link = (ch.link or '').strip()
    if link:
        s = link.replace('https://', '').replace('http://', '')
        for prefix in ('ble.ir/', 'bale.ai/'):
            if s.lower().startswith(prefix):
                s = s[len(prefix):].lstrip('/')
                break
        s = s.split('/')[0].strip()
        if s:
            if s.lstrip('-').isdigit():
                return s
            if not s.startswith('@'):
                s = '@' + s
            return s
    uname = getattr(ch, 'username', None) or getattr(ch, 'bale_username', None)
    if uname:
        u = str(uname).strip().lstrip('@')
        if u:
            return '@' + u
    peer = getattr(ch, 'bale_peer_id', None)
    if peer not in (None, '', 0, '0'):
        return str(peer).strip()
    return str(ch.id)


def channel_username(ch: Channel) -> str:
    """یوزرنیم کانال (برای verify بعد از resolve)."""
    link = (ch.link or '').strip()
    if link:
        s = link.replace('https://', '').replace('http://', '')
        for prefix in ('ble.ir/', 'bale.ai/'):
            if s.lower().startswith(prefix):
                s = s[len(prefix):].lstrip('/')
                break
        s = s.split('/')[0].strip().lstrip('@')
        if s and not s.lstrip('-').isdigit():
            return s.lower()
    uname = getattr(ch, 'username', None) or getattr(ch, 'bale_username', None)
    if uname:
        return str(uname).strip().lstrip('@').lower()
    return ''


def check_linkyar_admin(ch: Channel) -> str:
    state = ly.linkyar_admin_state(channel_ref(ch))
    if state in ('admin', 'not_admin'):
        ch.linkyar_is_admin = state == 'admin'
        ch.linkyar_checked_at = timezone.now()
        ch.save(update_fields=['linkyar_is_admin', 'linkyar_checked_at'])
    return state


def check_bot_admin(ch: Channel) -> str:
    """وضعیت ادمین بودن بازو را با چند مرجع کانال چک می‌کند."""
    candidates = []
    peer = getattr(ch, 'bale_peer_id', None)
    if peer not in (None, '', 0, '0'):
        candidates.append(str(peer))
    ref = channel_ref(ch)
    if ref:
        candidates.append(ref)
    link = (ch.link or '').strip()
    if link and link not in candidates:
        candidates.append(link)

    state = 'unknown'
    for cid in candidates:
        state = bc.bot_admin_state(cid)
        if state == 'admin':
            break
        if state == 'not_admin':
            # ادامه بده؛ شاید با peer جواب admin بیاید
            continue
    if state in ('admin', 'not_admin'):
        ch.bot_is_admin = state == 'admin'
        ch.bot_checked_at = timezone.now()
        ch.save(update_fields=['bot_is_admin', 'bot_checked_at'])
    return state


def deactivate_tariffs_for_channel(ch: Channel, reason: str) -> int:
    n = 0
    n += Tariff.objects.filter(channel=ch, is_active=True).update(is_active=False)
    for g in ch.groups.all():
        n += Tariff.objects.filter(group=g, is_active=True).update(is_active=False)
    if ch.manager and ch.manager.bale_user_id:
        bc.send_message(
            ch.manager.bale_user_id,
            f'⚠️ تعرفه(های) «{ch.name}» موقتاً غیرفعال شد.\nعلت: {reason}',
        )
    return n


def daily_admin_audit() -> Dict[str, int]:
    channel_ids: Set[int] = set(
        Tariff.objects.filter(is_active=True, channel__isnull=False).values_list('channel_id', flat=True)
    )
    for gid in Tariff.objects.filter(is_active=True, group__isnull=False).values_list('group_id', flat=True):
        g = ChannelGroup.objects.filter(id=gid).first()
        if g:
            channel_ids.update(g.channels.values_list('id', flat=True))
    checked = 0
    deactivated = 0
    for cid in channel_ids:
        ch = Channel.objects.filter(id=cid).first()
        if not ch:
            continue
        checked += 1
        mode = ch.publish_mode or Channel.PUBLISH_BOT
        if mode == Channel.PUBLISH_MANUAL:
            continue
        if mode == Channel.PUBLISH_BOT and check_bot_admin(ch) == 'not_admin':
            deactivated += deactivate_tariffs_for_channel(ch, 'لینک‌ساز دیگر مدیر کانال نیست')
        elif mode == Channel.PUBLISH_LINKYAR and check_linkyar_admin(ch) == 'not_admin':
            deactivated += deactivate_tariffs_for_channel(ch, 'لینک‌یار دیگر مدیر کانال نیست')
    return {'checked': checked, 'deactivated_tariffs': deactivated}


def targets_for_item(item: OrderItem) -> List[Channel]:
    t = item.tariff
    if t.group_id:
        return list(t.group.channels.order_by('id'))
    if item.channel_id:
        return [item.channel]
    if t.channel_id:
        return [t.channel]
    return []


def recover_permalink(
    ch: Channel, *,
    min_date_ms: Optional[int] = None,
    preferred_senders: Optional[List[int]] = None,
    limit: int = 12,
) -> Optional[Dict[str, Any]]:
    hist = ly.load_channel_history(channel_ref(ch), limit=limit)
    if not hist.get('ok'):
        return None
    messages = hist.get('messages') or []
    for m in messages:
        mid, date = m.get('message_id'), m.get('date')
        if mid is None or date is None:
            continue
        if min_date_ms is not None and int(date) < int(min_date_ms) - 15_000:
            continue
        if preferred_senders:
            sid = m.get('sender_id')
            if sid is not None and int(sid) not in preferred_senders:
                continue
        link = m.get('permalink') or ly.message_permalink(
            (ch.link or '').lstrip('@').split('/')[-1] if ch.link else '',
            int(mid), int(date),
        )
        return {
            'message_id': int(mid), 'date': int(date), 'sender_id': m.get('sender_id'),
            'permalink': link, 'channel_id': ch.id, 'ref': channel_ref(ch),
        }
    if preferred_senders:
        for m in messages:
            mid, date = m.get('message_id'), m.get('date')
            if mid is None or date is None:
                continue
            if min_date_ms is not None and int(date) < int(min_date_ms) - 15_000:
                continue
            link = m.get('permalink')
            if not link:
                continue
            return {
                'message_id': int(mid), 'date': int(date), 'sender_id': m.get('sender_id'),
                'permalink': link, 'channel_id': ch.id, 'ref': channel_ref(ch),
            }
    return None


def _notify_customer_executed(item: OrderItem, ch: Channel, permalink: str) -> None:
    cust = item.order.customer.bale_user_id
    if cust:
        bc.send_message(cust, f'✅ بنر شما در «{ch.name}» منتشر شد.\n🔗 {permalink}')


def _bot_chat_refs(ch: Channel) -> List[str]:
    """ترتیب امتحان chat_id برای Bot API."""
    refs: List[str] = []
    primary = channel_ref(ch)
    if primary:
        refs.append(primary)
    if getattr(ch, 'bale_peer_id', None):
        refs.append(str(ch.bale_peer_id))
    link = (ch.link or '').strip()
    if link and link not in refs:
        refs.append(link)
    # unique preserve order
    seen = set()
    out = []
    for r in refs:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _local_banner_path(banner_id: int | None) -> tuple:
    """(path, kind, caption) یا (None, '', '')."""
    if not banner_id:
        return None, '', ''
    try:
        from orders.banner_media import ensure_local_file, stored_banner_file
        from orders.models import CustomerBanner

        bn = CustomerBanner.objects.filter(id=int(banner_id)).first()
        if not bn:
            return None, '', ''
        path = ensure_local_file(bn) or stored_banner_file(bn.id)
        mk = (bn.media_kind or 'photo').lower()
        if mk in ('video', 'animation'):
            kind = 'video'
        elif mk == 'document':
            kind = 'document'
        else:
            kind = 'photo'
        return path, kind, (bn.caption or '')
    except Exception:
        logger.exception('local banner path')
        return None, '', ''


def _resolve_linkbank_forward_source(
    from_chat_id: str,
    message_id: int,
    caption: str = '',
    banner_id: int | None = None,
) -> Dict[str, Any]:
    """منبع فوروارد = کانال مرجع لینک‌بانک.

    بات: from_chat + message_id بات.
    لینک‌یار: peer داخلی + message_id داخلی + date از history.messages
    (کلید posts اشتباه بود و همیشه خالی می‌ماند).
    """
    from orders.banner_publish import linkbank_channel
    from orders.models import CustomerBanner

    lb = linkbank_channel()
    src_chat = str(from_chat_id or '').strip() or lb
    src_mid = int(message_id or 0)
    caption = caption or ''

    if banner_id:
        bn = CustomerBanner.objects.filter(id=int(banner_id)).first()
        if bn:
            if bn.linkbank_chat_id and bn.linkbank_message_id:
                src_chat = str(bn.linkbank_chat_id).strip() or lb
                try:
                    src_mid = int(str(bn.linkbank_message_id).strip())
                except (TypeError, ValueError):
                    pass
            if not caption and bn.caption:
                caption = bn.caption

    bot_from = src_chat or lb
    if bot_from and not str(bot_from).startswith('@') and 'ble.ir' not in str(bot_from) and not str(bot_from).lstrip('-').isdigit():
        bot_from = '@' + str(bot_from).lstrip('@')

    ly_peer = 0
    ly_mid = 0
    ly_date = 0
    hist_err = ''
    hist = None
    try:
        # لینک‌بانک را با چند شکل امتحان کن
        for ref_try in (src_chat, lb, str(lb).lstrip('@'), '@' + str(lb).lstrip('@')):
            if not ref_try:
                continue
            hist = ly.load_channel_history(str(ref_try), limit=50)
            if hist and hist.get('ok'):
                break
        if not hist or not hist.get('ok'):
            hist_err = str((hist or {}).get('error') or 'history_failed')
        else:
            if hist.get('peer_id'):
                try:
                    ly_peer = int(hist['peer_id'])
                except (TypeError, ValueError):
                    ly_peer = 0
            # کلید درست: messages (نه posts)
            posts = list(hist.get('messages') or hist.get('posts') or [])
            # مرتب بر اساس date نزولی
            def _date(p):
                try:
                    return int(p.get('date') or 0)
                except (TypeError, ValueError):
                    return 0
            posts = sorted(posts, key=_date, reverse=True)

            # 1) تطبیق preview/کپشن
            if caption.strip():
                cap_key = caption.strip()[:30]
                for post in posts:
                    prev = str(post.get('preview') or post.get('caption') or post.get('text') or '')
                    try:
                        pmid = int(post.get('message_id') or 0)
                        pdate = int(post.get('date') or 0)
                    except (TypeError, ValueError):
                        continue
                    if pmid and pdate and cap_key and cap_key in prev:
                        ly_mid, ly_date = pmid, pdate
                        break

            # 2) آخرین رسانه (عکس/ویدیو)
            if not ly_date:
                for post in posts:
                    kind = str(post.get('kind') or '')
                    try:
                        pmid = int(post.get('message_id') or 0)
                        pdate = int(post.get('date') or 0)
                    except (TypeError, ValueError):
                        continue
                    if pmid and pdate and kind in ('photo', 'video', 'document'):
                        ly_mid, ly_date = pmid, pdate
                        break

            # 3) هر پیام معتبر
            if not ly_date:
                for post in posts:
                    try:
                        pmid = int(post.get('message_id') or 0)
                        pdate = int(post.get('date') or 0)
                    except (TypeError, ValueError):
                        continue
                    if pmid and pdate:
                        ly_mid, ly_date = pmid, pdate
                        break
    except Exception as e:
        logger.exception('resolve linkbank history')
        hist_err = str(e)[:120]

    ly_ah = None
    if hist and hist.get('ok') and hist.get('access_hash') is not None:
        try:
            ly_ah = int(hist['access_hash'])
        except (TypeError, ValueError):
            ly_ah = None
    # فایل همان پیام برای ارسال بدون دانلود (اگر فوروارد شکست خورد)
    file_meta: Dict[str, Any] = {}
    if hist and hist.get('ok') and ly_mid:
        for post in list(hist.get('messages') or []):
            try:
                if int(post.get('message_id') or 0) == int(ly_mid):
                    if post.get('file_id') and post.get('file_access_hash'):
                        file_meta = {
                            'file_id': post.get('file_id'),
                            'file_access_hash': post.get('file_access_hash'),
                            'file_size': post.get('file_size') or 0,
                            'file_name': post.get('file_name') or 'banner.jpg',
                            'mime_type': post.get('mime_type') or 'image/jpeg',
                            'kind': post.get('kind') or 'photo',
                            'preview': post.get('preview') or '',
                        }
                    break
            except (TypeError, ValueError):
                continue
    # همیشه username مرجع برای AH — نه شناسه عددی بات
    src_ref_uname = lb
    return {
        'linkbank_ref': lb,
        'bot_from_chat_id': bot_from or lb,
        'bot_message_id': src_mid,
        'ly_peer_id': ly_peer,
        'ly_access_hash': ly_ah,
        'ly_message_id': ly_mid,
        'ly_message_date': ly_date,
        'caption': caption,
        'hist_error': hist_err,
        'source_channel_ref': src_ref_uname,
        'file_meta': file_meta,
    }


def _bot_success(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get('ok') is True:
        return True
    if result.get('ok') is False:
        return False
    # پاسخ بدون ok ولی با result
    return bool(result.get('result') or result.get('message_id'))


def _post_via_bot(
    ch: Channel,
    from_chat_id: str,
    message_id: int,
    caption: str = '',
    banner_id: int | None = None,
) -> Dict[str, Any]:
    """فوروارد یک‌بار از لینک‌بانک با لینک‌ساز."""
    src = _resolve_linkbank_forward_source(from_chat_id, message_id, caption, banner_id)
    from_chat = src['bot_from_chat_id']
    mid = int(src['bot_message_id'] or 0)
    if not from_chat or not mid:
        return {
            'ok': False,
            'method': 'failed',
            'channel_ref': channel_ref(ch),
            'api': {'error': 'no_linkbank_source'},
            'error': 'منبع بنر در لینک‌بانک مشخص نیست.',
        }

    # فقط یک chat_id اصلی — جلوگیری از ارسال دوبل
    refs = _bot_chat_refs(ch)
    primary = refs[0] if refs else channel_ref(ch)
    result = bc.forward_message(primary, str(from_chat), int(mid))
    if _bot_success(result):
        if isinstance(result, dict) and 'ok' not in result:
            result = dict(result)
            result['ok'] = True
        return {
            'api': result,
            'channel_ref': primary,
            'ok': True,
            'method': 'forward',
            'from_chat_id': from_chat,
            'message_id': mid,
        }

    # فقط اگر primary شکست خورد، یک ref جایگزین (بدون تکرار موفق)
    for ref in refs[1:]:
        result = bc.forward_message(ref, str(from_chat), int(mid))
        if _bot_success(result):
            if isinstance(result, dict) and 'ok' not in result:
                result = dict(result)
                result['ok'] = True
            return {
                'api': result,
                'channel_ref': ref,
                'ok': True,
                'method': 'forward',
                'from_chat_id': from_chat,
                'message_id': mid,
            }

    err = str((result or {}).get('description') or (result or {}).get('error') or 'فوروارد بات ناموفق')[:300]
    return {
        'api': result if isinstance(result, dict) else {'ok': False},
        'channel_ref': primary,
        'ok': False,
        'method': 'failed',
        'error': err,
    }


def _post_via_linkyar(
    ch: Channel,
    from_chat_id: str,
    message_id: int,
    caption: str = '',
    message_date: int = 0,
    banner_id: int | None = None,
) -> Dict[str, Any]:
    """فوروارد با نقل‌قول از لینک‌بانک → کانال مقصد.

    مبدأ: linkbank_chat_id بنر / from_chat_id (نه لزوماً LINKBANK_CHANNEL env)
    مقصد: channel_ref(ch) با اولویت bale_peer_id
    """
    from orders.banner_publish import linkbank_channel

    dst_ref = channel_ref(ch)
    lb_env = linkbank_channel()

    # شناسه عددی Bot API ≠ peer داخلی لینک‌یار
    # مبدأ برای لینک‌یار: همیشه یوزرنیم/رفرنس لینک‌بانک (قابل resolve)
    # مبدأ برای بات: linkbank_chat_id عددی بنر
    bot_from = str(from_chat_id or '').strip()
    bot_mid = int(message_id or 0)
    cap = caption or ''
    ly_rid = ''
    ly_date = ''
    ly_seq = ''
    if banner_id:
        try:
            from orders.models import CustomerBanner
            bn = CustomerBanner.objects.filter(id=int(banner_id)).first()
            if bn:
                if bn.linkbank_chat_id:
                    bot_from = str(bn.linkbank_chat_id).strip() or bot_from
                if bn.linkbank_message_id:
                    try:
                        bot_mid = int(str(bn.linkbank_message_id).strip())
                    except (TypeError, ValueError):
                        pass
                if not cap and bn.caption:
                    cap = bn.caption
                ly_rid = str(getattr(bn, 'linkyar_rid', '') or '')
                ly_date = str(getattr(bn, 'linkyar_date', '') or '')
                ly_seq = str(getattr(bn, 'linkyar_seq', '') or '')
        except Exception:
            pass

    def _norm(ref: str) -> str:
        r = str(ref or '').strip()
        if not r:
            return r
        if r.lstrip('-').isdigit():
            return r  # فقط برای بات نگه می‌داریم
        if 'ble.ir/' in r or 'bale.ai/' in r:
            s = r.replace('https://', '').replace('http://', '')
            for prefix in ('ble.ir/', 'bale.ai/'):
                if s.lower().startswith(prefix):
                    s = s[len(prefix):].lstrip('/')
                    break
            s = s.split('/')[0].strip()
            return ('@' + s.lstrip('@')) if s else r
        if not r.startswith('@'):
            return '@' + r.lstrip('@')
        return r

    def _is_numeric(ref: str) -> bool:
        return bool(ref) and str(ref).strip().lstrip('-').isdigit()

    # src برای لینک‌یار: هرگز شناسهٔ خالص Bot API
    src_ref = _norm(lb_env)
    if bot_from and not _is_numeric(bot_from):
        src_ref = _norm(bot_from) or src_ref
    dst_ref = _norm(dst_ref)

    # bot_from برای hop/بات: ترجیح عددی
    if not bot_from:
        bot_from = src_ref
    elif not _is_numeric(bot_from):
        bot_from = _norm(bot_from)

    peer_id = getattr(ch, 'bale_peer_id', None)
    try:
        peer_id = int(peer_id) if peer_id not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        peer_id = None

    result = ly.forward_banner_from_linkbank(
        dst_ref,
        src_ref,
        caption_match=cap,
        limit=80,
        bot_from_chat_id=bot_from,
        bot_message_id=bot_mid,
        message_date=int(message_date or 0),
        linkyar_rid=ly_rid,
        linkyar_date=ly_date,
        linkyar_seq=ly_seq,
        dst_peer_id=peer_id,
        dst_title=str(getattr(ch, 'name', None) or ''),
    )
    if result.get('ok'):
        return {
            'api': result,
            'channel_ref': dst_ref,
            'ok': True,
            'method': result.get('method') or 'forward',
            'message_id': result.get('message_id'),
            'message_date': result.get('message_date'),
            'lib': result.get('lib'),
        }

    err = str(result.get('error') or 'forward_failed')
    if result.get('lib'):
        err = f'{err} | lib={result.get("lib")}'
    if result.get('picked'):
        err = f'{err} | picked={result.get("picked")}'
    if result.get('want_mid') is not None:
        err = f'{err} | want_mid={result.get("want_mid")}'
    if result.get('previews'):
        err = f'{err} | hist={result.get("previews")}'[:400]
    if result.get('src_peer') or result.get('target'):
        err = (
            f'{err} | src={result.get("src_peer")}(ah={result.get("src_ah")}) '
            f'tgt={result.get("target")}(ah={result.get("tgt_ah")}) '
            f'mid={result.get("mid")}'
        )[:480]
    tries = result.get('tries') or result.get('tries_all') or []
    if tries:
        err = f'{err} | try0={tries[0]}'[:560]
    return {
        'ok': False,
        'method': 'failed',
        'channel_ref': dst_ref,
        'api': result if isinstance(result, dict) else {'ok': False},
        'error': f'فوروارد لینک‌یار ناموفق: {err}'[:500],
    }



def _fail_one_channel(item: OrderItem, ch: Channel, reason: str) -> None:
    msg = f'❌ ارسال آیتم #{item.id} در «{ch.name}» ناموفق.\nعلت: {reason}'
    if ch.manager and ch.manager.bale_user_id:
        bc.send_message(ch.manager.bale_user_id, msg)
    if OPERATOR_BALE_ID:
        bc.send_message(OPERATOR_BALE_ID, msg)


def _finalize_channel_ok(item: OrderItem, ch: Channel, post_meta: Dict[str, Any], posts: List) -> None:
    posts.append(post_meta)
    permalink = post_meta.get('permalink') or ''
    if permalink:
        item.published_link = permalink[:500]
        _notify_customer_executed(item, ch, permalink)


def _refund_failed_item(item: OrderItem) -> None:
    try:
        order = item.order
        entry = credit_customer_refund(order.customer, item.price, item.id, f'عدم انتشار #{item.id}')
        if item.manager:
            apply_manager_penalty(item.manager, item.price, item.id)
        if order.customer.bale_user_id and entry is not None:
            bc.send_message(
                order.customer.bale_user_id,
                f'مبلغ {entry.amount:,} تومان بابت آیتم #{item.id} به کیف پول برگشت.',
            )
    except Exception:
        logger.exception('refund failed item=%s', item.id)


@transaction.atomic
def publish_due_items() -> Dict[str, int]:
    now = timezone.now()
    items = (
        OrderItem.objects.select_related(
            'order', 'order__customer', 'order__customer_banner',
            'channel', 'tariff', 'tariff__group', 'manager',
        )
        .filter(execution_status='paid', manager_status='approved')
        .filter(
            Q(manager_edited_start__lte=now)
            | Q(manager_edited_start__isnull=True, requested_start__lte=now)
        )
    )
    published = failed = manual_reminded = 0
    bot_id, ly_id = _bot_numeric_id(), _linkyar_numeric_id()

    for item in items:
        order = item.order
        if not order.banner_message_id or not order.banner_from_chat_id:
            continue
        start = item.effective_start
        if start and start > now:
            continue
        channels = targets_for_item(item)
        if not channels:
            continue

        posts: List[Dict[str, Any]] = []
        any_ok = any_manual = False
        retry_later = False
        t0_ms = int(time.time() * 1000)
        from_chat = str(order.banner_from_chat_id)
        try:
            msg_id = int(order.banner_message_id)
        except (TypeError, ValueError):
            continue
        cb = order.customer_banner
        if cb and cb.from_linkbank and cb.linkbank_message_id:
            from_chat = str(cb.linkbank_chat_id or from_chat)
            try:
                msg_id = int(cb.linkbank_message_id)
            except (TypeError, ValueError):
                pass

        for ch in channels:
            mode = ch.publish_mode or Channel.PUBLISH_BOT
            if mode == Channel.PUBLISH_MANUAL:
                any_manual = True
                if item.manager and item.manager.bale_user_id:
                    kb = bc.inline_keyboard([[{
                        'text': '✅ منتشر شد', 'callback_data': f'published:{item.id}:{ch.id}'
                    }]])
                    bc.send_message(
                        item.manager.bale_user_id,
                        f'⏰ زمان انتشار #{item.id} — «{ch.name}»',
                        reply_markup=kb,
                    )
                continue

            if mode == Channel.PUBLISH_BOT:
                state = check_bot_admin(ch)
                if state == 'unknown':
                    retry_later = True
                    continue
                if state != 'admin':
                    _fail_one_channel(item, ch, 'لینک‌ساز مدیر کانال نیست')
                    failed += 1
                    continue
                res = _post_via_bot(ch, from_chat, msg_id, order.banner_caption or '', banner_id=(order.customer_banner_id or None))
                bot_mid = ((res.get('api') or {}).get('result') or {}).get('message_id')
                time.sleep(1.5)
                meta = recover_permalink(ch, min_date_ms=t0_ms, preferred_senders=[x for x in [bot_id] if x])
                if meta and meta.get('permalink'):
                    any_ok = True
                    if bot_mid:
                        meta['bot_message_id'] = int(bot_mid)
                    _finalize_channel_ok(item, ch, meta, posts)
                elif res.get('ok'):
                    any_ok = True
                    row = {'channel_id': ch.id, 'ref': channel_ref(ch), 'permalink': ''}
                    if bot_mid:
                        row['bot_message_id'] = int(bot_mid)
                    posts.append(row)
                    if order.customer.bale_user_id:
                        bc.send_message(order.customer.bale_user_id, f'✅ بنر در «{ch.name}» ارسال شد.')
                else:
                    api_err = (res.get('api') or {})
                    reason = str(api_err.get('description') or api_err.get('error') or 'ارسال ناموفق')[:200]
                    logger.warning('bot publish fail item=%s ch=%s api=%s', item.id, ch.id, api_err)
                    _fail_one_channel(item, ch, reason)
                    failed += 1
                continue

            if mode == Channel.PUBLISH_LINKYAR:
                state = check_linkyar_admin(ch)
                if state == 'unknown':
                    retry_later = True
                    continue
                if state != 'admin':
                    _fail_one_channel(item, ch, 'لینک‌یار مدیر کانال نیست')
                    failed += 1
                    continue
                ly_res = _post_via_linkyar(ch, from_chat, msg_id, order.banner_caption or '', banner_id=(order.customer_banner_id or None))
                time.sleep(2)
                meta = recover_permalink(ch, min_date_ms=t0_ms, preferred_senders=[x for x in [ly_id] if x])
                if not (meta and meta.get('permalink')):
                    meta = recover_permalink(ch, min_date_ms=t0_ms, preferred_senders=None)
                if meta and meta.get('permalink'):
                    any_ok = True
                    _finalize_channel_ok(item, ch, meta, posts)
                elif ly_res.get('ok'):
                    any_ok = True
                    posts.append({'channel_id': ch.id, 'ref': channel_ref(ch), 'permalink': ''})
                    if order.customer.bale_user_id:
                        bc.send_message(order.customer.bale_user_id, f'✅ بنر در «{ch.name}» ارسال شد.')
                else:
                    api_err = (ly_res.get('api') or {})
                    reason = str(api_err.get('description') or api_err.get('error') or 'تأیید لینک‌یار ناموفق')[:200]
                    logger.warning('linkyar publish fail item=%s ch=%s api=%s', item.id, ch.id, api_err)
                    _fail_one_channel(item, ch, reason)
                    failed += 1

        if retry_later and not any_ok and not any_manual:
            continue

        if any_manual and not any_ok:
            item.execution_status = 'awaiting_manager_publish'
            item.save(update_fields=['execution_status'])
            manual_reminded += 1
            continue

        if any_ok:
            item.execution_status = 'executed'
            item.executed_at = now
            item.published_at = now
            item.channel_message_id = json.dumps(posts, ensure_ascii=False)[:4000]
            if posts and posts[0].get('permalink'):
                item.published_link = str(posts[0]['permalink'])[:500]
            item.save(update_fields=[
                'execution_status', 'executed_at', 'published_at',
                'channel_message_id', 'published_link',
            ])
            if item.manager:
                credit_manager_for_execution(item.manager, item.price, item.id)
            published += 1
            from orders.execution import settle_paid_order

            settle_paid_order(item.order_id)
        elif not any_manual:
            item.execution_status = 'failed_publish'
            item.save(update_fields=['execution_status'])
            _refund_failed_item(item)
            from orders.execution import settle_paid_order

            settle_paid_order(item.order_id)

    return {'published': published, 'failed_channels': failed, 'manual_reminded': manual_reminded}


def verify_manager_published(
    item_id: int, manager_bale_id: str, channel_id: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        item = OrderItem.objects.select_related(
            'order', 'order__customer', 'channel', 'tariff', 'tariff__group', 'manager'
        ).get(id=item_id)
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'not_found'}
    if item.manager and str(item.manager.bale_user_id) != str(manager_bale_id):
        return {'ok': False, 'error': 'not_manager'}
    if item.execution_status not in ('paid', 'remind_sent', 'awaiting_manager_publish'):
        return {'ok': False, 'error': 'bad_status'}
    channels = targets_for_item(item)
    if channel_id:
        channels = [c for c in channels if c.id == int(channel_id)]
    if not channels:
        return {'ok': False, 'error': 'no_channel'}
    posts: List[Dict[str, Any]] = []
    any_ok = False
    min_ms = int((item.effective_start.timestamp() - 3600) * 1000) if item.effective_start else None
    for ch in channels:
        meta = recover_permalink(ch, min_date_ms=min_ms, preferred_senders=None)
        if meta and meta.get('permalink'):
            any_ok = True
            _finalize_channel_ok(item, ch, meta, posts)
        else:
            _fail_one_channel(item, ch, 'بنر در تاریخچه پیدا نشد')
    if any_ok:
        item.execution_status = 'executed'
        item.executed_at = timezone.now()
        item.published_at = timezone.now()
        item.channel_message_id = json.dumps(posts, ensure_ascii=False)[:4000]
        if posts and posts[0].get('permalink'):
            item.published_link = str(posts[0]['permalink'])[:500]
        item.save(update_fields=[
            'execution_status', 'executed_at', 'published_at',
            'channel_message_id', 'published_link',
        ])
        if item.manager:
            credit_manager_for_execution(item.manager, item.price, item.id)
        from orders.execution import settle_paid_order

        settle_paid_order(item.order_id)
        return {'ok': True, 'permalinks': [p.get('permalink') for p in posts]}
    return {'ok': False, 'error': 'not_found_in_history'}


def delete_expired_posts() -> int:
    """حذف پست کانال پس از پایان مدت — یا TEST_AD_TTL_MINUTES برای تست کوتاه."""
    try:
        process_pending_test_deletes()
    except Exception:
        logger.exception('process_pending_test_deletes')
    now = timezone.now()
    ttl_min = int(os.environ.get('TEST_AD_TTL_MINUTES', '0') or '0')
    if ttl_min > 0:
        cutoff = now - timedelta(minutes=ttl_min)
        items = (
            OrderItem.objects.filter(execution_status='executed', published_at__lte=cutoff)
            .exclude(channel_message_id__isnull=True)
            .exclude(channel_message_id='')
        )
    else:
        items = (
            OrderItem.objects.filter(execution_status='executed', requested_end__lte=now)
            .exclude(channel_message_id__isnull=True)
            .exclude(channel_message_id='')
        )
    n = 0
    for item in items:
        try:
            posts = json.loads(item.channel_message_id or '[]')
        except Exception:
            posts = []
        if not isinstance(posts, list):
            posts = []
        for p in posts:
            mid, date, ref = p.get('message_id'), p.get('date') or 0, p.get('ref')
            bot_mid = p.get('bot_message_id')
            touched = False
            if bot_mid and ref:
                bc.delete_message(str(ref), int(bot_mid))
                touched = True
            if mid and ref:
                ly.delete_message(str(ref), int(mid), message_date=int(date or 0))
                touched = True
            if touched:
                n += 1
        item.channel_message_id = ''
        item.save(update_fields=['channel_message_id'])
    return n



def delete_test_post(
    channel_ref_or_id: str,
    *,
    mode: str = 'bot',
    bot_message_id: int | None = None,
    ly_message_id: int | None = None,
    ly_message_date: int = 0,
) -> Dict[str, Any]:
    """حذف دستی پست تستی که بازو یا لینک‌یار فرستاده."""
    ref = str(channel_ref_or_id or '').strip()
    if not ref:
        return {'ok': False, 'error': 'channel_required'}
    # اگر شناسه عددی کانال است
    if ref.isdigit():
        ch = Channel.objects.filter(id=int(ref)).first()
        if ch:
            ref = channel_ref(ch)
    out: Dict[str, Any] = {'ok': False, 'ref': ref, 'mode': mode}
    try:
        if mode == 'bot' and bot_message_id:
            r = bc.delete_message(str(ref), int(bot_message_id))
            out['bot'] = r
            out['ok'] = bool(r.get('ok'))
        elif mode == 'linkyar' and ly_message_id:
            r = ly.delete_message(str(ref), int(ly_message_id), message_date=int(ly_message_date or 0))
            out['linkyar'] = r
            out['ok'] = bool(r.get('ok'))
        else:
            # هر دو را امتحان کن اگر داده باشد
            ok = False
            if bot_message_id:
                r = bc.delete_message(str(ref), int(bot_message_id))
                out['bot'] = r
                ok = ok or bool(r.get('ok'))
            if ly_message_id:
                r = ly.delete_message(str(ref), int(ly_message_id), message_date=int(ly_message_date or 0))
                out['linkyar'] = r
                ok = ok or bool(r.get('ok'))
            out['ok'] = ok
        if not out['ok'] and not out.get('error'):
            out['error'] = 'delete_failed'
    except Exception as e:
        logger.exception('delete_test_post')
        out['error'] = str(e)[:200]
    return out



def test_upload_then_forward_same_channel(
    channel: Channel,
    banner_id: int | None = None,
) -> Dict[str, Any]:
    """تست فوروارد واقعی به سبک پروتکل بله:

    در تاریخچهٔ بله، فوروارد = emptyMessage + quotedMessage (peer دیگر).
    ForwardMessages به کانال no-op بود؛ این مسیر SendMessage با
    emptyMessage + quotedMessageReference را امتحان می‌کند.
    """
    from integrations import linkyar_client as ly
    import time as _time
    import random

    FIXED_PEER = 1085567241
    FIXED_REF = '@linkya'
    marker = f'[ly-fwd-test-{int(_time.time())}-{random.randint(1000, 9999)}]'

    result: Dict[str, Any] = {
        'ok': False,
        'mode': 'upload_then_forward',
        'fixed_target': f'{FIXED_REF} id={FIXED_PEER}',
        'marker': marker,
    }

    # 1) ارسال متن معمولی (کاربر تأیید کرده دیده می‌شود)
    ly_send = ly.send_text_to_channel(FIXED_REF, marker)
    result['linkyar_send'] = {
        'ok': bool(ly_send.get('ok')),
        'error': ly_send.get('error'),
        'message_id': ly_send.get('message_id'),
        'date': ly_send.get('date'),
    }
    if not ly_send.get('ok'):
        result['error'] = f"ارسال متن ناموفق: {ly_send.get('error')}"
        return result

    _time.sleep(2.0)

    token = ly.user_token()
    if not token:
        result['error'] = 'BALE_TOKEN missing'
        return result

    async def _run():
        import asyncio
        import random as _rnd
        from bale import BaleClient
        from bale import pb
        from bale.peer import Peer, PeerInfo

        def _u64(v):
            if v is None:
                return 0
            if hasattr(v, 'value'):
                try:
                    return int(v.value)
                except Exception:
                    pass
            try:
                return int(v)
            except Exception:
                return 0

        def _rid(h):
            return _u64(getattr(h, 'rid', None))

        def _date(h):
            return _u64(getattr(h, 'date', None))

        def _content_text(h) -> str:
            c = getattr(h, 'content', None)
            if c is None:
                return ''
            # Content dataclass from bale-sdk
            for a in ('text', 'caption', 'body'):
                v = getattr(c, a, None)
                if v:
                    return str(v)
            return str(c)[:80]

        async with BaleClient(token) as client:
            peer = Peer.channel(FIXED_PEER, access_hash=1)
            try:
                full = await client.get_full(PeerInfo(peer=peer))
                if full and getattr(full, 'peer', None):
                    peer = full.peer
            except Exception:
                pass

            hist = list(await client.get_history(peer, limit=25) or [])
            chosen = None
            for h in hist:
                if marker[:18] in _content_text(h):
                    chosen = h
                    break
            if chosen is None:
                # تازه‌ترین پیام خودمان
                me_id = int(getattr(client, 'me_id', 0) or 0)
                for h in hist:
                    if int(getattr(h, 'sender_id', 0) or 0) == me_id:
                        chosen = h
                        break
            if chosen is None and hist:
                chosen = hist[0]

            if chosen is None:
                return {'ok': False, 'error': 'no_source_message_in_history'}

            rid = _rid(chosen)
            date = _date(chosen)
            seq = _u64(getattr(chosen, 'seq', None))
            before_n = sum(1 for h in hist if marker[:18] in _content_text(h))
            before_rids = {_rid(h) for h in hist}
            before_fwd_flags = sum(1 for h in hist if getattr(h, 'is_forward', False))

            tries = []
            me_id = int(getattr(client, 'me_id', 0) or 0)
            me = Peer.user(me_id) if me_id else None

            # --- A) ForwardMessages مستقیم (قبلاً no-op) ---
            try:
                req = pb.ForwardMessagesRequest()
                req.peer.CopyFrom(peer.to_out_proto())
                f = req.forwardedMessages.add()
                f.peer.CopyFrom(peer.to_proto())
                f.rid = int(rid)
                f.date.value = int(date)
                if seq:
                    f.seq.value = int(seq)
                req.rid.append(_rnd.getrandbits(63))
                await client.call(
                    'bale.messaging.v2.Messaging', 'ForwardMessages', req, timeout=15.0,
                )
                tries.append('ForwardMessages_direct:called')
            except Exception as e:
                tries.append(f'ForwardMessages_direct:{type(e).__name__}:{e}')

            # --- B) SendMessage با emptyMessage + quotedMessageReference = شکل فوروارد در پروتکل ---
            try:
                req = pb.SendMessageRequest()
                req.peer.CopyFrom(peer.to_proto())
                req.exPeer.CopyFrom(peer.to_out_proto())
                req.rid = _rnd.getrandbits(63)
                req.message.emptyMessage.SetInParent()
                req.quotedMessageReference.peer.CopyFrom(peer.to_proto())
                req.quotedMessageReference.rid = int(rid)
                req.quotedMessageReference.date.value = int(date)
                if seq:
                    req.quotedMessageReference.seq.value = int(seq)
                await client.call(
                    'bale.messaging.v2.Messaging', 'SendMessage', req, timeout=15.0,
                )
                tries.append('empty+quote_same_peer:called')
            except Exception as e:
                tries.append(f'empty+quote_same_peer:{type(e).__name__}:{e}')

            # --- C) hop به شخصی، بعد empty+quote از شخصی به کانال ---
            if me:
                try:
                    req = pb.ForwardMessagesRequest()
                    req.peer.CopyFrom(me.to_out_proto())
                    f = req.forwardedMessages.add()
                    f.peer.CopyFrom(peer.to_proto())
                    f.rid = int(rid)
                    f.date.value = int(date)
                    req.rid.append(_rnd.getrandbits(63))
                    await client.call(
                        'bale.messaging.v2.Messaging', 'ForwardMessages', req, timeout=15.0,
                    )
                    await asyncio.sleep(1.5)
                    me_hist = list(await client.get_history(me, limit=5) or [])
                    hop = me_hist[0] if me_hist else None
                    if hop:
                        hr, hd = _rid(hop), _date(hop)
                        tries.append(f'hop_me:rid={hr}')
                        # empty+quote با مبدأ = شخصی (peer ≠ کانال → is_forward در تاریخچه)
                        req2 = pb.SendMessageRequest()
                        req2.peer.CopyFrom(peer.to_proto())
                        req2.exPeer.CopyFrom(peer.to_out_proto())
                        req2.rid = _rnd.getrandbits(63)
                        req2.message.emptyMessage.SetInParent()
                        req2.quotedMessageReference.peer.CopyFrom(me.to_proto())
                        req2.quotedMessageReference.rid = int(hr)
                        req2.quotedMessageReference.date.value = int(hd)
                        await client.call(
                            'bale.messaging.v2.Messaging', 'SendMessage', req2, timeout=15.0,
                        )
                        tries.append('empty+quote_from_me:called')
                        # ForwardMessages از me به channel
                        req3 = pb.ForwardMessagesRequest()
                        req3.peer.CopyFrom(peer.to_out_proto())
                        f3 = req3.forwardedMessages.add()
                        f3.peer.CopyFrom(me.to_proto())
                        f3.rid = int(hr)
                        f3.date.value = int(hd)
                        req3.rid.append(_rnd.getrandbits(63))
                        await client.call(
                            'bale.messaging.v2.Messaging', 'ForwardMessages', req3, timeout=15.0,
                        )
                        tries.append('ForwardMessages_from_me:called')
                except Exception as e:
                    tries.append(f'hop_path:{type(e).__name__}:{e}')

            await asyncio.sleep(3.0)
            after = list(await client.get_history(peer, limit=25) or [])
            after_n = sum(1 for h in after if marker[:18] in _content_text(h))
            after_rids = {_rid(h) for h in after}
            new_rids = after_rids - before_rids
            new_rids.discard(0)
            after_fwd = sum(1 for h in after if getattr(h, 'is_forward', False))
            # نمونه محتوا
            samples = []
            for h in after[:6]:
                samples.append({
                    'rid': _rid(h),
                    'fwd': bool(getattr(h, 'is_forward', False)),
                    'text': _content_text(h)[:40],
                    'sender': getattr(h, 'sender_id', None),
                })

            # فقط افزایش واقعی — نه «از قبل چند marker بوده»
            ok = (after_n > before_n) or (after_fwd > before_fwd_flags)
            return {
                'ok': ok,
                'src_rid': rid,
                'src_date': date,
                'marker_before': before_n,
                'marker_after': after_n,
                'fwd_flags_before': before_fwd_flags,
                'fwd_flags_after': after_fwd,
                'new_rids': list(new_rids)[:5],
                'tries': tries,
                'samples': samples,
                'peer_id': int(peer.id),
                'peer_ah': int(peer.access_hash),
            }

    out = ly._run(_run())
    if not isinstance(out, dict):
        result['error'] = str(out)
        return result

    result.update(out)
    if out.get('ok'):
        result['message'] = (
            f'فوروارد/تکرار دیده شد در @linkya | marker {out.get("marker_before")}→{out.get("marker_after")} '
            f'| is_forward {out.get("fwd_flags_before")}→{out.get("fwd_flags_after")} '
            f'| tries={out.get("tries")}'
        )
        result['ok'] = True
    else:
        result['error'] = (
            f'متن ok بود؛ فوروارد دیده نشد | marker {out.get("marker_before")}→{out.get("marker_after")} '
            f'| is_forward {out.get("fwd_flags_before")}→{out.get("fwd_flags_after")} '
            f'| tries={out.get("tries")} | samples={out.get("samples")}'
        )[:900]
        result['ok'] = False
    return result



def test_publish_to_channel(
    channel: Channel,
    from_chat_id: str,
    message_id: int,
    mode: str | None = None,
    caption: str = '',
    message_date: int = 0,
    delete_after_minutes: int = 0,
    banner_id: int | None = None,
) -> Dict[str, Any]:
    """ارسال تستی بنر به یک کانال — بدون سفارش/پرداخت. برای پشتیبان.

    اگر delete_after_minutes > 0 باشد، پس از آن مدت پست تستی حذف می‌شود.
    """
    try:
        process_pending_test_deletes()
    except Exception:
        logger.exception('process_pending_test_deletes on test')
    mode = mode or (channel.publish_mode or Channel.PUBLISH_BOT)
    ref = channel_ref(channel)
    result: Dict[str, Any] = {
        'ok': False,
        'mode': mode,
        'channel_id': channel.id,
        'channel_name': channel.name,
        'channel_ref': ref,
    }
    if mode == Channel.PUBLISH_MANUAL:
        result['error'] = 'حالت انتشار این کانال دستی است؛ ارسال خودکار ندارد.'
        return result

    posted_bot_mid = None
    posted_ly_mid = None
    posted_ly_date = 0

    if mode == Channel.PUBLISH_BOT:
        state = check_bot_admin(channel)
        result['admin_state'] = state
        if state != 'admin':
            result['error'] = (
                'لینک‌ساز مدیر کانال نیست' if state == 'not_admin'
                else 'وضعیت ادمین لینک‌ساز مشخص نشد (شبکه؟)'
            )
            return result
        res = _post_via_bot(channel, str(from_chat_id), int(message_id), caption or '', banner_id=banner_id)
        result['api'] = res.get('api')
        result['ok'] = bool(res.get('ok'))
        result['method'] = res.get('method')
        if not result['ok']:
            api = res.get('api') or {}
            result['error'] = str(api.get('description') or api.get('error') or 'ارسال ناموفق')[:300]
            return result
        api_res = res.get('api') or {}
        result_obj = api_res.get('result') if isinstance(api_res.get('result'), dict) else api_res
        posted_bot_mid = None
        if isinstance(result_obj, dict):
            posted_bot_mid = result_obj.get('message_id')
            if not posted_bot_mid and isinstance(result_obj.get('message'), dict):
                posted_bot_mid = result_obj['message'].get('message_id')
        try:
            posted_bot_mid = int(posted_bot_mid) if posted_bot_mid is not None else None
        except (TypeError, ValueError):
            posted_bot_mid = None
        result['bot_message_id'] = posted_bot_mid
        result['channel_ref'] = res.get('channel_ref') or ref
        result['message'] = f'ارسال با لینک‌ساز به «{channel.name}» انجام شد.'
    elif mode == Channel.PUBLISH_LINKYAR:
        state = check_linkyar_admin(channel)
        result['admin_state'] = state
        if state != 'admin':
            result['error'] = (
                'لینک‌یار مدیر کانال نیست' if state == 'not_admin'
                else 'وضعیت ادمین لینک‌یار مشخص نشد'
            )
            return result
        res = _post_via_linkyar(
            channel,
            str(from_chat_id),
            int(message_id),
            caption or '',
            message_date=int(message_date or 0),
            banner_id=banner_id,
        )
        result['api'] = res.get('api')
        result['ok'] = bool(res.get('ok'))
        if not result['ok']:
            api = res.get('api') or {}
            result['error'] = str(
                res.get('error') or api.get('description') or api.get('error') or api.get('hint') or 'ارسال ناموفق'
            )[:300]
            return result
        api = res.get('api') or {}
        posted_ly_mid = api.get('message_id')
        if posted_ly_mid is None and isinstance(api.get('result'), int):
            posted_ly_mid = api.get('result')
        posted_ly_date = int(api.get('message_date') or api.get('date') or 0)
        result['linkyar_message_id'] = posted_ly_mid
        result['linkyar_message_date'] = posted_ly_date
        result['method'] = res.get('method')
        method_fa = 'فوروارد' if res.get('method') == 'forward' else 'آپلود فایل'
        result['message'] = f'ارسال با لینک‌یار به «{channel.name}» انجام شد ({method_fa}).'
    else:
        result['error'] = f'حالت انتشار ناشناخته: {mode}'
        return result

    mins = int(delete_after_minutes or 0)
    if mins > 0:
        result['delete_after_minutes'] = mins
        del_ref = str(result.get('channel_ref') or ref)
        if mode == Channel.PUBLISH_BOT and not posted_bot_mid:
            result['message'] = (result.get('message') or '') + ' — حذف خودکار ثبت نشد (message_id نیامد).'
            logger.warning('test publish bot ok but no message_id for delete')
        else:
            result['message'] = (result.get('message') or '') + f' — حذف خودکار تا {mins} دقیقه دیگر.'
            _schedule_test_delete(
                ref=del_ref,
                mode=mode,
                bot_message_id=int(posted_bot_mid) if posted_bot_mid else None,
                ly_message_id=int(posted_ly_mid) if posted_ly_mid else None,
                ly_message_date=int(posted_ly_date or 0),
                minutes=mins,
            )
    return result



def test_send_capability_matrix(
    channel: Channel,
    from_chat_id: str = '',
    message_id: int = 0,
    caption: str = '',
    banner_id: int | None = None,
    delete_after_minutes: int = 1,
) -> Dict[str, Any]:
    """یک‌مرحله‌ای: مقایسه قابلیت ارسال بازو و لینک‌یار.

    هر حساب با متدهای موجودش تست می‌شود (فوروارد، کپی، متن خام، آپلود فایل).
    خروجی برای تصمیم‌گیری نهایی است — بدون آزمون‌وخطای دستی.
    """
    import time as _time
    from orders.banner_media import stored_banner_file
    from orders.banner_publish import linkbank_channel

    ref = channel_ref(channel)
    lb = linkbank_channel()
    src = _resolve_linkbank_forward_source(
        str(from_chat_id or ''),
        int(message_id or 0),
        caption or '',
        banner_id=banner_id,
    )
    bot_from = str(src.get('bot_from_chat_id') or from_chat_id or lb or '')
    try:
        bot_mid = int(src.get('bot_message_id') or message_id or 0)
    except (TypeError, ValueError):
        bot_mid = int(message_id or 0)
    try:
        ly_peer = int(src.get('ly_peer_id') or 0)
    except (TypeError, ValueError):
        ly_peer = 0
    try:
        ly_mid = int(src.get('ly_message_id') or 0)
    except (TypeError, ValueError):
        ly_mid = 0
    try:
        ly_date = int(src.get('ly_message_date') or 0)
    except (TypeError, ValueError):
        ly_date = 0
    cap = str(src.get('caption') or caption or '')[:500]
    src_ref = str(src.get('source_channel_ref') or bot_from or lb or '')
    marker = f'[lb-matrix-{int(_time.time())}]'

    file_path = None
    if banner_id:
        try:
            p = stored_banner_file(int(banner_id))
            if p is not None and p.is_file():
                file_path = str(p)
        except Exception:
            file_path = None

    probes: Dict[str, Any] = {
        'channel_ref': ref,
        'channel_name': channel.name,
        'channel_id': channel.id,
        'linkbank': lb,
        'bot_from': bot_from,
        'bot_mid': bot_mid,
        'ly_peer': ly_peer,
        'ly_mid': ly_mid,
        'ly_date': ly_date,
        'has_local_file': bool(file_path),
        'bot_admin': None,
        'linkyar_admin': None,
        'bot_me': None,
        'linkyar_me': None,
    }
    try:
        probes['bot_admin'] = check_bot_admin(channel)
    except Exception as e:
        probes['bot_admin'] = f'err:{type(e).__name__}'
    try:
        probes['linkyar_admin'] = check_linkyar_admin(channel)
    except Exception as e:
        probes['linkyar_admin'] = f'err:{type(e).__name__}'
    try:
        me = bc.get_me()
        res = me.get('result') or me
        probes['bot_me'] = res.get('username') or res.get('id')
    except Exception as e:
        probes['bot_me'] = f'err:{type(e).__name__}'
    try:
        ly_me = ly.get_me()
        if isinstance(ly_me, dict):
            probes['linkyar_me'] = ly_me.get('user_id') or ly_me.get('username') or ly_me
        else:
            probes['linkyar_me'] = str(ly_me)[:80]
    except Exception as e:
        probes['linkyar_me'] = f'err:{type(e).__name__}'

    trials: List[Dict[str, Any]] = []

    def _trial(account: str, method: str, fn) -> None:
        started = _time.time()
        row: Dict[str, Any] = {
            'account': account,
            'method': method,
            'ok': False,
            'error': '',
            'message_id': None,
            'message_date': None,
            'ms': 0,
            'raw': '',
        }
        try:
            out = fn()
            if not isinstance(out, dict):
                out = {'ok': False, 'error': str(out)[:200]}
            row['ok'] = bool(out.get('ok'))
            row['error'] = str(out.get('error') or out.get('description') or '')[:240]
            # extract message id from various shapes
            mid = out.get('message_id') or out.get('bot_message_id') or out.get('linkyar_rid')
            if mid is None:
                result = out.get('result')
                if isinstance(result, dict):
                    mid = result.get('message_id')
                    if mid is None and isinstance(result.get('message'), dict):
                        mid = result['message'].get('message_id')
            try:
                row['message_id'] = int(mid) if mid is not None else None
            except (TypeError, ValueError):
                row['message_id'] = None
            if out.get('message_date') is not None:
                try:
                    row['message_date'] = int(out.get('message_date'))
                except (TypeError, ValueError):
                    pass
            # short raw for debug (no secrets)
            row['raw'] = str({k: out.get(k) for k in ('ok', 'error', 'method', 'description') if k in out})[:180]
        except Exception as e:
            logger.exception('matrix trial %s/%s', account, method)
            row['ok'] = False
            row['error'] = f'{type(e).__name__}: {e}'[:240]
        row['ms'] = int((_time.time() - started) * 1000)
        trials.append(row)

    # ── BOT ──────────────────────────────────────────────
    def bot_forward():
        if not bot_from or not bot_mid:
            return {'ok': False, 'error': 'no_bot_source (from_chat/message_id)'}
        return bc.forward_message(ref, str(bot_from), int(bot_mid))

    def bot_copy():
        if not bot_from or not bot_mid:
            return {'ok': False, 'error': 'no_bot_source'}
        return bc.copy_message(ref, str(bot_from), int(bot_mid), caption=cap or None)

    def bot_text():
        return bc.send_message(ref, f'{marker} bot-text')

    def bot_upload():
        if not file_path:
            return {'ok': False, 'error': 'no_local_file'}
        # photo vs document by extension
        low = file_path.lower()
        if low.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            return bc.send_photo(ref, file_path, caption=f'{marker} bot-upload')
        if hasattr(bc, 'send_video') and low.endswith(('.mp4', '.webm')):
            return bc.send_video(ref, file_path, caption=f'{marker} bot-upload')
        if hasattr(bc, 'send_document'):
            return bc.send_document(ref, file_path, caption=f'{marker} bot-upload')
        return {'ok': False, 'error': 'no_upload_method'}

    _trial('bot', 'forwardMessage', bot_forward)
    _trial('bot', 'copyMessage', bot_copy)
    _trial('bot', 'sendMessage(text)', bot_text)
    _trial('bot', 'sendMedia(upload)', bot_upload)

    # ── LINKYAR ──────────────────────────────────────────
    def ly_forward():
        kwargs = {
            'target_channel_ref': ref,
            'source_channel_ref': str(src_ref or bot_from or lb or ''),
            'caption_match': cap,
            'bot_from_chat_id': str(bot_from or ''),
            'bot_message_id': int(bot_mid or 0),
            'message_date': int(ly_date or 0),
        }
        if banner_id:
            try:
                from orders.models import CustomerBanner
                bn = CustomerBanner.objects.filter(id=int(banner_id)).first()
                if bn is not None:
                    for attr, key in (
                        ('linkyar_rid', 'linkyar_rid'),
                        ('linkyar_date', 'linkyar_date'),
                        ('linkyar_seq', 'linkyar_seq'),
                    ):
                        val = getattr(bn, attr, None)
                        if val not in (None, '', 0, '0'):
                            kwargs[key] = val
            except Exception:
                pass
        try:
            return ly.forward_banner_from_linkbank(**kwargs)
        except TypeError as e:
            return {'ok': False, 'error': f'signature:{e}'}

    def ly_text():
        return ly.send_text_to_channel(ref, f'{marker} ly-text')

    def ly_upload():
        if not file_path:
            return {'ok': False, 'error': 'no_local_file'}
        if hasattr(ly, 'send_local_file_to_channel'):
            return ly.send_local_file_to_channel(ref, file_path, caption=f'{marker} ly-upload')
        if hasattr(ly, 'send_existing_file_to_channel'):
            return ly.send_existing_file_to_channel(ref, file_path, caption=f'{marker} ly-upload')
        return {'ok': False, 'error': 'no_upload_method'}

    def ly_copy():
        # برخی کلاینت‌ها copy را alias فوروارد می‌دانند
        if hasattr(ly, 'copy_message') and bot_from and bot_mid:
            try:
                return ly.copy_message(ref, str(bot_from), int(bot_mid), message_date=int(ly_date or 0))
            except TypeError:
                return ly.copy_message(ref, str(bot_from), int(bot_mid))
        return {'ok': False, 'error': 'copy_not_available'}

    _trial('linkyar', 'forward_from_linkbank', ly_forward)
    _trial('linkyar', 'sendText', ly_text)
    _trial('linkyar', 'sendMedia(upload)', ly_upload)
    _trial('linkyar', 'copyMessage', ly_copy)

    # حذف خودکار پیام‌های موفق
    mins = max(0, int(delete_after_minutes or 0))
    scheduled = 0
    if mins > 0:
        for row in trials:
            if not row.get('ok') or not row.get('message_id'):
                continue
            try:
                if row['account'] == 'bot':
                    _schedule_test_delete(
                        ref=ref,
                        mode=Channel.PUBLISH_BOT,
                        bot_message_id=int(row['message_id']),
                        ly_message_id=None,
                        ly_message_date=0,
                        minutes=mins,
                    )
                    scheduled += 1
                elif row['account'] == 'linkyar':
                    _schedule_test_delete(
                        ref=ref,
                        mode=Channel.PUBLISH_LINKYAR,
                        bot_message_id=None,
                        ly_message_id=int(row['message_id']),
                        ly_message_date=int(row.get('message_date') or 0),
                        minutes=mins,
                    )
                    scheduled += 1
            except Exception:
                logger.exception('matrix schedule delete')

    bot_ok = [t for t in trials if t['account'] == 'bot' and t['ok']]
    ly_ok = [t for t in trials if t['account'] == 'linkyar' and t['ok']]
    summary_lines = [
        f'کانال: {channel.name} ({ref})',
        f'ادمین بازو: {probes["bot_admin"]} | ادمین لینک‌یار: {probes["linkyar_admin"]}',
        f'منبع بنر بات: {bot_from} / mid={bot_mid} | فایل محلی: {"بله" if file_path else "خیر"}',
        '— بازو —',
    ]
    for t in trials:
        if t['account'] != 'bot':
            continue
        mark = '✓' if t['ok'] else '✗'
        summary_lines.append(f'{mark} {t["method"]} ({t["ms"]}ms) {t["error"] or ("mid="+str(t["message_id"]) if t["message_id"] else "ok")}')
    summary_lines.append('— لینک‌یار —')
    for t in trials:
        if t['account'] != 'linkyar':
            continue
        mark = '✓' if t['ok'] else '✗'
        summary_lines.append(f'{mark} {t["method"]} ({t["ms"]}ms) {t["error"] or ("mid="+str(t["message_id"]) if t["message_id"] else "ok")}')
    if bot_ok or ly_ok:
        bot_fwd = any(t['method'] == 'forwardMessage' and t['ok'] for t in trials if t['account'] == 'bot')
        ly_fwd = any('forward' in t['method'] and t['ok'] for t in trials if t['account'] == 'linkyar')
        if bot_fwd:
            rec = 'توصیه تولید: بازو + forwardMessage از لینک‌بانک (پایدار + پیش‌نمایش تصویر)'
        elif bot_ok:
            rec = 'توصیه: بازو (فوروارد در این کانال نشد؛ از copy/upload بات استفاده شود)'
        elif ly_fwd:
            rec = 'توصیه: لینک‌یار فوروارد (بازو در این کانال موفق نبود)'
        else:
            rec = 'توصیه: فقط ارسال خام لینک‌یار (فوروارد لینک‌یار پایدار نیست)'
        summary_lines.append(rec)
        summary_lines.append(
            f'موفق: بازو {len(bot_ok)} متد / لینک‌یار {len(ly_ok)} متد'
            + f' | حذف خودکار: {scheduled} پیام تا {mins} دقیقه'
        )
    else:
        summary_lines.append('هیچ متدی موفق نشد — دسترسی ادمین یا منبع بنر را چک کنید.')

    return {
        'ok': True,
        'matrix': True,
        'probes': probes,
        'trials': trials,
        'bot_success_count': len(bot_ok),
        'linkyar_success_count': len(ly_ok),
        'delete_after_minutes': mins,
        'scheduled_deletes': scheduled,
        'message': '\n'.join(summary_lines),
    }




def test_linkyar_libraries_matrix(
    channel: Channel,
    banner_id: int | None = None,
    caption: str = '',
    from_chat_id: str = '',
    message_id: int = 0,
    delete_after_seconds: int = 60,
) -> Dict[str, Any]:
    """ماتریس فقط حساب شخصی (لینک‌یار) — بدون هیچ فراخوانی بازو.

    کتابخانه‌های موجود را در runtime کشف می‌کند و برای هر کدام
    متدهای ارسال/حذف موجود را جداگانه تست می‌کند.
    """
    import time as _time
    from orders.banner_media import stored_banner_file
    from orders.banner_publish import linkbank_channel

    ref = channel_ref(channel)
    lb = linkbank_channel()
    marker_base = f'ly-lib-{int(_time.time())}'
    trials: List[Dict[str, Any]] = []
    libs_info: Dict[str, Any] = {}

    file_path = None
    if banner_id:
        try:
            p = stored_banner_file(int(banner_id))
            if p is not None and p.is_file():
                file_path = str(p)
        except Exception:
            file_path = None

    # منبع بنر فقط از تاریخچه لینک‌یار (نه بات)
    src = _resolve_linkbank_forward_source(
        str(from_chat_id or ''),
        int(message_id or 0),
        caption or '',
        banner_id=banner_id,
    )
    ly_mid = int(src.get('ly_message_id') or 0)
    ly_date = int(src.get('ly_message_date') or 0)
    ly_peer = int(src.get('ly_peer_id') or 0)
    cap = str(src.get('caption') or caption or '')[:400]
    src_ref = str(src.get('source_channel_ref') or lb or '')

    # ── کشف کتابخانه‌ها ─────────────────────────────────
    def _probe_libs() -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        # baleclient
        try:
            import baleclient  # noqa: F401
            out['baleclient'] = {
                'available': True,
                'version': getattr(baleclient, '__version__', None),
                'file': getattr(baleclient, '__file__', None),
            }
        except Exception as e:
            out['baleclient'] = {'available': False, 'error': f'{type(e).__name__}:{e}'}
        # aiobale / aiobale-py
        try:
            import aiobale  # noqa: F401
            out['aiobale'] = {
                'available': True,
                'version': getattr(aiobale, '__version__', None),
                'file': getattr(aiobale, '__file__', None),
            }
        except Exception as e:
            out['aiobale'] = {'available': False, 'error': f'{type(e).__name__}:{e}'}
        # bale-sdk
        try:
            from bale import BaleClient, pb  # noqa: F401
            out['bale-sdk'] = {
                'available': True,
                'has_BaleClient': True,
                'pb_sample': [x for x in dir(pb) if 'Message' in x or 'Forward' in x or 'Delete' in x][:30],
            }
        except Exception as e:
            out['bale-sdk'] = {'available': False, 'error': f'{type(e).__name__}:{e}'}
        # balethon (اگر نصب باشد)
        try:
            import balethon  # noqa: F401
            out['balethon'] = {
                'available': True,
                'version': getattr(balethon, '__version__', None),
            }
        except Exception as e:
            out['balethon'] = {'available': False, 'error': f'{type(e).__name__}:{e}'}
        # آنچه linkyar_client الان bind کرده
        try:
            from integrations import linkyar_client as ly_mod
            out['linkyar_bound'] = {
                'lib_name': getattr(ly_mod, '_BALE_LIB_NAME', None),
                'token_present': bool(ly_mod.user_token()),
                'me': ly_mod.get_me(),
            }
        except Exception as e:
            out['linkyar_bound'] = {'error': f'{type(e).__name__}:{e}'}
        return out

    libs_info = _probe_libs()

    def _trial(lib: str, method: str, fn) -> Dict[str, Any]:
        started = _time.time()
        row: Dict[str, Any] = {
            'lib': lib,
            'method': method,
            'ok': False,
            'error': '',
            'message_id': None,
            'message_date': None,
            'ms': 0,
            'detail': '',
        }
        try:
            out = fn()
            if not isinstance(out, dict):
                out = {'ok': False, 'error': str(out)[:240]}
            row['ok'] = bool(out.get('ok'))
            row['error'] = str(out.get('error') or out.get('description') or '')[:300]
            mid = out.get('message_id') or out.get('linkyar_rid') or out.get('rid')
            if mid is None and isinstance(out.get('result'), dict):
                mid = out['result'].get('message_id')
            try:
                row['message_id'] = int(mid) if mid is not None else None
            except (TypeError, ValueError):
                row['message_id'] = None
            for dk in ('message_date', 'date', 'ly_message_date'):
                if out.get(dk) is not None:
                    try:
                        row['message_date'] = int(out.get(dk))
                        break
                    except (TypeError, ValueError):
                        pass
            # detail keys useful for diagnosis
            keep = {k: out.get(k) for k in (
                'method', 'combo', 'lib', 'peer_id', 'tries', 'prev_error', 'hint', 'hist_error'
            ) if k in out}
            row['detail'] = str(keep)[:220]
        except Exception as e:
            logger.exception('ly-lib trial %s/%s', lib, method)
            row['ok'] = False
            row['error'] = f'{type(e).__name__}: {e}'[:300]
        row['ms'] = int((_time.time() - started) * 1000)
        trials.append(row)
        return row

    # ── لایهٔ مشترک linkyar_client (روی baleclient یا aiobale bind شده) ──
    bound_lib = str((libs_info.get('linkyar_bound') or {}).get('lib_name') or 'linkyar_client')

    def t_send_text():
        return ly.send_text_to_channel(ref, f'[{marker_base}-text] send_text_to_channel')

    def t_send_message_alias():
        return ly.send_message(ref, f'[{marker_base}-alias] send_message')

    def t_upload():
        if not file_path:
            return {'ok': False, 'error': 'no_local_file'}
        return ly.send_local_file_to_channel(
            ref, file_path, caption=f'[{marker_base}-upload] media', kind='photo'
        )

    def t_send_existing():
        """ارسال همان file_id سرور بله (بدون دانلود) — از file_meta تاریخچه."""
        if not hasattr(ly, 'send_existing_file_to_channel'):
            return {'ok': False, 'error': 'method_missing'}
        fm = src.get('file_meta') if isinstance(src.get('file_meta'), dict) else {}
        if not fm or not fm.get('file_id') or not fm.get('file_access_hash'):
            return {'ok': False, 'error': 'no_file_meta_from_linkbank_history'}
        return ly.send_existing_file_to_channel(
            ref,
            file_id=fm.get('file_id'),
            file_access_hash=int(fm.get('file_access_hash')),
            file_size=int(fm.get('file_size') or 0),
            file_name=str(fm.get('file_name') or 'banner.jpg'),
            mime_type=str(fm.get('mime_type') or 'image/jpeg'),
            caption=f'[{marker_base}-existing] ' + (cap[:80] if cap else 'media'),
            kind=str(fm.get('kind') or 'photo'),
        )

    def t_forward_sdk_only():
        """فوروارد فقط با حساب شخصی — بدون پل بازو."""
        # اگر rid از تاریخچه لینک‌بانک داریم، مستقیم SDK
        if ly_mid and ly_date:
            try:
                return ly._forward_via_bale_sdk_from_self_or_source(
                    target_channel_ref=ref,
                    source_channel_ref=src_ref or lb,
                    caption_match=cap,
                    bot_message_id=0,
                    message_date=int(ly_date),
                    dst_peer_id=None,
                    prefer_self_inbox=False,
                    me_id=None,
                    force_rid=int(ly_mid),
                    force_date=int(ly_date),
                    force_seq=0,
                )
            except TypeError as e:
                return {'ok': False, 'error': f'signature:{e}'}
        # بدون mid: تلاش با caption match از لینک‌بانک (هنوز بدون بات)
        try:
            return ly._forward_via_bale_sdk(
                target_channel_ref=ref,
                source_channel_ref=src_ref or lb,
                caption_match=cap[:40] if cap else marker_base,
            )
        except Exception as e:
            return {'ok': False, 'error': f'{type(e).__name__}:{e}'}

    def t_copy_no_bot():
        """copy_message لینک‌یار بدون استفاده از بات."""
        if not ly_mid:
            return {'ok': False, 'error': 'no_ly_source_mid'}
        try:
            return ly.copy_message(
                ref,
                str(src_ref or lb),
                int(ly_mid),
                message_date=int(ly_date or 0),
            )
        except TypeError:
            return ly.copy_message(ref, str(src_ref or lb), int(ly_mid))

    def t_forward_message_alias():
        if not ly_mid:
            return {'ok': False, 'error': 'no_ly_source_mid'}
        return ly.forward_message(ref, str(src_ref or lb), int(ly_mid), message_date=int(ly_date or 0))

    def t_client_highlevel_photo():
        """مستقیم متدهای media روی client (امضاهای رایج baleclient)."""
        if not file_path:
            return {'ok': False, 'error': 'no_local_file'}

        async def _fn(client):
            from aiobale.enums import ChatType
            try:
                from aiobale.types import FileInput
            except Exception:
                FileInput = None
            resolved = await ly._resolve_peer(client, ref)
            if not resolved.get('ok'):
                return {'ok': False, 'error': resolved.get('error')}
            peer_id = int(resolved['peer_id'])
            try:
                await client.join_public_chat(peer_id)
            except Exception:
                pass
            cap = f'[{marker_base}-hl-photo]'
            fin = FileInput(str(file_path)) if FileInput else str(file_path)
            methods_tried = []
            # ترتیب: photo بعد document — فقط اگر متد روی client باشد
            candidates = []
            for name in ('send_photo', 'send_document', 'send_gif'):
                if hasattr(client, name):
                    candidates.append(name)
            for name in candidates:
                fn = getattr(client, name)
                attempts = [
                    dict(file=fin, chat_id=peer_id, chat_type=ChatType.GROUP, caption=cap),
                    dict(file=str(file_path), chat_id=peer_id, chat_type=ChatType.GROUP, caption=cap),
                    dict(path=str(file_path), chat_id=peer_id, chat_type=ChatType.GROUP, caption=cap),
                ]
                for kwargs in attempts:
                    try:
                        msg = await fn(**kwargs)
                        return {
                            'ok': True,
                            'message_id': getattr(msg, 'message_id', None) or getattr(msg, 'id', None),
                            'date': getattr(msg, 'date', None),
                            'method': name,
                            'kwargs': list(kwargs.keys()),
                        }
                    except TypeError as e:
                        methods_tried.append(f'{name}{list(kwargs.keys())}:TypeError:{e}')
                    except Exception as e:
                        methods_tried.append(f'{name}{list(kwargs.keys())}:{type(e).__name__}:{e}')
                        break  # همین متد با خطای غیر امضا — برو بعدی
                # positional
                try:
                    msg = await fn(fin, chat_id=peer_id, chat_type=ChatType.GROUP, caption=cap)
                    return {
                        'ok': True,
                        'message_id': getattr(msg, 'message_id', None),
                        'date': getattr(msg, 'date', None),
                        'method': name + '_pos',
                    }
                except Exception as e:
                    methods_tried.append(f'{name}_pos:{type(e).__name__}:{e}')
            return {'ok': False, 'error': 'highlevel_failed', 'tries': methods_tried[:12]}

        out = ly._run(ly._with_client(_fn))
        # بازیابی از تاریخچه اگر API خطا داد ولی پیام رفت
        if isinstance(out, dict) and not out.get('ok'):
            import time as _t2
            _t2.sleep(2.0)
            try:
                hist = ly.load_channel_history(ref, limit=30)
            except Exception:
                hist = None
            if isinstance(hist, dict) and hist.get('ok'):
                key = f'{marker_base}-hl'
                for post in list(hist.get('messages') or []):
                    prev = str(post.get('preview') or '')
                    if key not in prev:
                        continue
                    try:
                        mid = int(post.get('message_id') or 0)
                        dt = int(post.get('date') or 0)
                    except (TypeError, ValueError):
                        continue
                    if mid:
                        return {
                            'ok': True,
                            'message_id': mid,
                            'date': dt,
                            'method': 'highlevel_recovered',
                            'prev_error': out.get('error'),
                        }
        return out if isinstance(out, dict) else {'ok': False, 'error': str(out)[:200]}

    def t_client_list_methods():
        """فقط کشف متدهای messaging روی client — ارسال نیست."""
        async def _fn(client):
            names = sorted(
                m for m in dir(client)
                if not m.startswith('_') and any(
                    k in m.lower()
                    for k in ('send', 'forward', 'copy', 'delete', 'upload', 'history', 'message')
                )
            )
            return {'ok': True, 'methods': names, 'message_id': None}
        out = ly._run(ly._with_client(_fn))
        if isinstance(out, dict) and out.get('methods'):
            libs_info.setdefault('client_methods', out['methods'])
        return out if isinstance(out, dict) else {'ok': False, 'error': str(out)}

    # اجرا

    def t_native_send_photo():
        """client.send_photo با امضای رسمی baleclient (photo= نه file=)."""
        if not file_path:
            return {'ok': False, 'error': 'no_local_file'}

        async def _fn(client):
            from aiobale.enums import ChatType
            from aiobale.types import FileInput
            resolved = await ly._resolve_peer(client, ref)
            if not resolved.get('ok'):
                return {'ok': False, 'error': resolved.get('error')}
            peer_id = int(resolved['peer_id'])
            try:
                await client.join_public_chat(peer_id)
            except Exception:
                pass
            cap = f'[{marker_base}-native-photo]'
            photo = FileInput(str(file_path))
            last_err = ''
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    msg = await client.send_photo(
                        photo=photo,
                        chat_id=peer_id,
                        chat_type=ctype,
                        caption=cap,
                    )
                    return {
                        'ok': True,
                        'message_id': getattr(msg, 'message_id', None),
                        'date': getattr(msg, 'date', None) if not hasattr(getattr(msg, 'date', None), 'value') else getattr(msg.date, 'value', None),
                        'method': f'send_photo/{ctype}',
                        'peer_id': peer_id,
                    }
                except Exception as e:
                    last_err = f'{ctype}:{type(e).__name__}:{e}'
            return {'ok': False, 'error': last_err or 'send_photo_failed'}

        out = ly._run(ly._with_client(_fn))
        if isinstance(out, dict) and out.get('ok'):
            # normalize date
            d = out.get('date')
            if hasattr(d, 'value'):
                try:
                    out['date'] = int(d.value)
                except Exception:
                    pass
            elif d is not None:
                try:
                    out['date'] = int(d)
                except Exception:
                    pass
            return out
        # recover from history by marker
        import time as _t2
        _t2.sleep(2.0)
        try:
            hist = ly.load_channel_history(ref, limit=30)
        except Exception:
            hist = None
        if isinstance(hist, dict) and hist.get('ok'):
            key = f'{marker_base}-native-photo'
            for post in list(hist.get('messages') or []):
                prev = str(post.get('preview') or '')
                if key not in prev and post.get('kind') not in ('photo', 'document', 'video'):
                    continue
                if key not in prev:
                    # newest media from me within window — still accept if only one recent media
                    pass
                else:
                    try:
                        return {
                            'ok': True,
                            'message_id': int(post.get('message_id') or 0),
                            'date': int(post.get('date') or 0),
                            'method': 'send_photo_recovered',
                        }
                    except Exception:
                        pass
        return out if isinstance(out, dict) else {'ok': False, 'error': str(out)[:200]}

    def t_native_forward():
        """فوروارد واقعی: load_history مبدأ → client.forward_message به مقصد.

        امضای رسمی baleclient: forward_message(message, chat_id, chat_type)
        """
        src_channel = src_ref or lb
        if not src_channel:
            return {'ok': False, 'error': 'no_source_channel'}

        async def _fn(client):
            from aiobale.enums import ChatType
            from aiobale.types import InfoMessage, Peer
            from aiobale.enums import PeerType

            src_res = await ly._resolve_peer(client, src_channel)
            dst_res = await ly._resolve_peer(client, ref)
            if not src_res.get('ok'):
                return {'ok': False, 'error': f"src_resolve:{src_res.get('error')}"}
            if not dst_res.get('ok'):
                return {'ok': False, 'error': f"dst_resolve:{dst_res.get('error')}"}
            src_id = int(src_res['peer_id'])
            dst_id = int(dst_res['peer_id'])
            src_ah = src_res.get('access_hash')
            tries = []

            # 1) load_history native برای گرفتن Message واقعی
            hist_msgs = []
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    hist_msgs = await client.load_history(
                        chat_id=src_id,
                        chat_type=ctype,
                        limit=40,
                    )
                    if hist_msgs:
                        tries.append(f'load_history/{ctype}:n={len(hist_msgs)}')
                        break
                except Exception as e:
                    tries.append(f'load_history/{ctype}:{type(e).__name__}:{e}')
            if not hist_msgs:
                return {'ok': False, 'error': 'source_history_empty', 'tries': tries}

            # پیدا کردن پیام هدف
            target_msg = None
            want = int(ly_mid or 0)
            for m in hist_msgs:
                mid = getattr(m, 'message_id', None)
                try:
                    mid = int(mid) if mid is not None else None
                except Exception:
                    mid = None
                if want and mid == want:
                    target_msg = m
                    break
            if target_msg is None:
                # اولین پیام رسانه‌ای / غیرمتن
                for m in hist_msgs:
                    content = getattr(m, 'content', None)
                    # بدون حدس پیچیده: اگر mid از بنر نبود، اولین پیام
                    target_msg = m
                    break
            if target_msg is None:
                return {'ok': False, 'error': 'no_message_picked', 'tries': tries}

            picked_mid = getattr(target_msg, 'message_id', None)
            picked_date = getattr(target_msg, 'date', None)
            if hasattr(picked_date, 'value'):
                picked_date = picked_date.value

            # 2) forward_message به مقصد با هر chat_type
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    resp = await client.forward_message(
                        message=target_msg,
                        chat_id=dst_id,
                        chat_type=ctype,
                    )
                    tries.append(f'forward/{ctype}:ok={resp}')
                    # verify
                    import asyncio as _aio
                    await _aio.sleep(1.5)
                    after = []
                    try:
                        after = await client.load_history(chat_id=dst_id, chat_type=ctype, limit=15)
                    except Exception as e:
                        tries.append(f'verify_hist:{type(e).__name__}:{e}')
                    # count growth or matching forward
                    ok_vis = False
                    new_mid = None
                    new_date = None
                    if after:
                        # اگر تعداد زیاد شد یا is_forward
                        for am in after[:8]:
                            if getattr(am, 'is_forward', False) or getattr(am, 'forwarded_from', None):
                                ok_vis = True
                                new_mid = getattr(am, 'message_id', None)
                                new_date = getattr(am, 'date', None)
                                break
                        if not ok_vis and len(after) >= 1:
                            # API بدون exception = احتمالاً ok؛ mid جدید را از generate حدس نزن
                            ok_vis = True
                            new_mid = getattr(after[0], 'message_id', None)
                            new_date = getattr(after[0], 'date', None)
                    if hasattr(new_date, 'value'):
                        new_date = new_date.value
                    if ok_vis:
                        return {
                            'ok': True,
                            'message_id': int(new_mid) if new_mid is not None else None,
                            'date': int(new_date) if new_date is not None else None,
                            'method': f'native_forward/{ctype}',
                            'src_mid': int(picked_mid) if picked_mid is not None else None,
                            'src_date': int(picked_date) if picked_date is not None else None,
                            'tries': tries,
                        }
                    tries.append(f'forward/{ctype}:not_visible')
                except Exception as e:
                    tries.append(f'forward/{ctype}:{type(e).__name__}:{e}')

            # 3) fallback: InfoMessage دستی با peer مبدأ
            try:
                peer_kwargs = {'type': PeerType.GROUP, 'id': src_id}
                if src_ah not in (None, 0):
                    peer_kwargs['access_hash'] = int(src_ah)
                info = InfoMessage(
                    peer=Peer(**peer_kwargs),
                    message_id=int(picked_mid),
                    date=int(picked_date or 0),
                )
                for ctype in (ChatType.GROUP, ChatType.CHANNEL):
                    try:
                        resp = await client.forward_message(
                            message=info, chat_id=dst_id, chat_type=ctype
                        )
                        tries.append(f'info_forward/{ctype}:ok')
                        return {
                            'ok': True,
                            'message_id': None,
                            'date': int(picked_date or 0),
                            'method': f'info_forward/{ctype}',
                            'tries': tries,
                            'note': 'API accepted InfoMessage; visibility not verified',
                        }
                    except Exception as e:
                        tries.append(f'info_forward/{ctype}:{type(e).__name__}:{e}')
            except Exception as e:
                tries.append(f'info_build:{type(e).__name__}:{e}')

            return {'ok': False, 'error': 'native_forward_failed', 'tries': tries[:20]}

        return ly._run(ly._with_client(_fn))

    def t_native_forward_messages_list():
        """client.forward_messages(list) — همان API چندتایی."""
        src_channel = src_ref or lb

        async def _fn(client):
            from aiobale.enums import ChatType
            src_res = await ly._resolve_peer(client, src_channel)
            dst_res = await ly._resolve_peer(client, ref)
            if not src_res.get('ok') or not dst_res.get('ok'):
                return {'ok': False, 'error': 'resolve_failed'}
            src_id = int(src_res['peer_id'])
            dst_id = int(dst_res['peer_id'])
            msgs = []
            for ctype in (ChatType.GROUP, ChatType.CHANNEL):
                try:
                    msgs = await client.load_history(chat_id=src_id, chat_type=ctype, limit=20)
                    if msgs:
                        break
                except Exception:
                    continue
            if not msgs:
                return {'ok': False, 'error': 'no_msgs'}
            pick = msgs[0]
            want = int(ly_mid or 0)
            if want:
                for m in msgs:
                    try:
                        if int(getattr(m, 'message_id', 0) or 0) == want:
                            pick = m
                            break
                    except Exception:
                        pass
            last = ''
            for ctype in (ChatType.GROUP, ChatType.CHANNEL):
                try:
                    await client.forward_messages(messages=[pick], chat_id=dst_id, chat_type=ctype)
                    return {'ok': True, 'method': f'forward_messages/{ctype}', 'message_id': getattr(pick, 'message_id', None)}
                except Exception as e:
                    last = f'{ctype}:{type(e).__name__}:{e}'
            return {'ok': False, 'error': last or 'failed'}

        return ly._run(ly._with_client(_fn))


    _trial(bound_lib, 'discover_client_methods', t_client_list_methods)
    _trial(bound_lib, 'send_text_to_channel', t_send_text)
    _trial(bound_lib, 'send_message(alias)', t_send_message_alias)
    _trial(bound_lib, 'send_local_file_to_channel', t_upload)
    _trial(bound_lib, 'native send_photo(photo=)', t_native_send_photo)
    _trial(bound_lib, 'send_existing_file_to_channel', t_send_existing)
    _trial(bound_lib, 'NATIVE forward_message(Message)', t_native_forward)
    _trial(bound_lib, 'NATIVE forward_messages(list)', t_native_forward_messages_list)
    _trial('bale-sdk', 'ForwardMessages(source→dst)', t_forward_sdk_only)
    _trial(bound_lib, 'copy_message(wrapper)', t_copy_no_bot)

    # ── حذف برای هر ارسال موفق ───────────────────────────
    delete_trials: List[Dict[str, Any]] = []
    for row in list(trials):
        if not row.get('ok') or not row.get('message_id'):
            continue
        if row['method'] == 'discover_client_methods':
            continue
        mid = int(row['message_id'])
        mdate = int(row.get('message_date') or 0)

        def _make_del(mid=mid, mdate=mdate, method=row['method']):
            def _del():
                r = ly.delete_message(ref, mid, message_date=mdate)
                if isinstance(r, dict) and r.get('ok'):
                    r['deleted_method'] = method
                    r['deleted_mid'] = mid
                return r if isinstance(r, dict) else {'ok': False, 'error': str(r)}
            return _del

        # کمی صبر تا پیام در سرور commit شود
        _time.sleep(0.4)
        drow = _trial(bound_lib, f'delete_after:{row["method"]}', _make_del())
        delete_trials.append(drow)

    # اگر delete_after_seconds و هنوز چیزی مانده — schedule
    # (فقط برای مواردی که delete فوری شکست خورد)
    scheduled = 0
    mins = max(1, int(delete_after_seconds or 60) // 60)
    for row in trials:
        if not row.get('ok') or not row.get('message_id'):
            continue
        if row['method'] == 'discover_client_methods':
            continue
        # اگر حذف فوری برای این mid موفق بوده، schedule نکن
        mid = row['message_id']
        deleted = any(
            d.get('ok') and f'delete_after:{row["method"]}' == d.get('method')
            for d in delete_trials
        )
        if deleted:
            continue
        try:
            _schedule_test_delete(
                ref=ref,
                mode=Channel.PUBLISH_LINKYAR,
                bot_message_id=None,
                ly_message_id=int(mid),
                ly_message_date=int(row.get('message_date') or 0),
                minutes=mins,
            )
            scheduled += 1
        except Exception:
            logger.exception('ly-lib schedule delete')

    # جارو — فقط پیام‌هایی که دقیقاً marker همین اجرا را دارند (هرگز رسانهٔ قدیمی/بدون کپشن)
    # marker_base مثل ly-lib-1791... یکتا برای این run است
    try:
        _time.sleep(0.8)
        hist = ly.load_channel_history(ref, limit=25)
        sweep_count = 0
        max_sweep = 8  # سقف ایمنی
        if isinstance(hist, dict) and hist.get('ok'):
            for post in list(hist.get('messages') or []):
                if sweep_count >= max_sweep:
                    break
                prev = ' '.join(
                    str(post.get(x) or '')
                    for x in ('preview', 'caption', 'text', 'file_name')
                )
                # شرط سخت: فقط اگر marker همین تست در متن/کپشن باشد
                if marker_base not in prev:
                    continue
                try:
                    mid = int(post.get('message_id') or 0)
                    mdate = int(post.get('date') or 0)
                except (TypeError, ValueError):
                    continue
                if not mid:
                    continue
                started = _time.time()
                row = {
                    'lib': bound_lib,
                    'method': f'sweep_delete:{mid}',
                    'ok': False,
                    'error': '',
                    'message_id': mid,
                    'message_date': mdate,
                    'ms': 0,
                    'detail': (prev[:60] if prev else '') ,
                }
                try:
                    r = ly.delete_message(ref, mid, message_date=mdate)
                    row['ok'] = bool(isinstance(r, dict) and r.get('ok'))
                    row['error'] = '' if row['ok'] else str((r or {}).get('error') or 'delete_failed')[:200]
                except Exception as e:
                    row['error'] = f'{type(e).__name__}:{e}'[:200]
                row['ms'] = int((_time.time() - started) * 1000)
                trials.append(row)
                sweep_count += 1
    except Exception:
        logger.exception('ly-lib sweep delete')

    # خلاصه
    lines = [
        f'ماتریس فقط لینک‌یار | کانال: {channel.name} ({ref})',
        f'کتابخانهٔ bind: {bound_lib} | فایل محلی: {"بله" if file_path else "خیر"}',
        f'منبع تاریخچه لینک‌بانک: peer={ly_peer} mid={ly_mid} date={ly_date}',
        '— کتابخانه‌ها —',
    ]
    for name, info in libs_info.items():
        if name in ('client_methods',):
            continue
        if not isinstance(info, dict):
            continue
        if info.get('available') is True:
            lines.append(f'✓ {name} available {info.get("version") or ""}')
        elif info.get('available') is False:
            lines.append(f'✗ {name} {info.get("error") or "missing"}')
        elif name == 'linkyar_bound':
            lines.append(f'· bound={info.get("lib_name")} token={info.get("token_present")} me={info.get("me")}')
    if libs_info.get('client_methods'):
        lines.append('· client methods: ' + ', '.join(libs_info['client_methods'][:25]))
    lines.append('— ارسال —')
    for t in trials:
        if str(t['method']).startswith('delete_after:'):
            continue
        if t['method'] == 'discover_client_methods':
            continue
        mark = '✓' if t['ok'] else '✗'
        extra = t['error'] or (f'mid={t["message_id"]}' if t['message_id'] else 'ok')
        lines.append(f'{mark} [{t["lib"]}] {t["method"]} ({t["ms"]}ms) {extra}')
    lines.append('— حذف —')
    for t in trials:
        if not str(t['method']).startswith('delete_after:'):
            continue
        mark = '✓' if t['ok'] else '✗'
        extra = t['error'] or 'deleted'
        lines.append(f'{mark} [{t["lib"]}] {t["method"]} ({t["ms"]}ms) {extra}')
    if scheduled:
        lines.append(f'حذف زمان‌بندی‌شده برای {scheduled} پیام (≈{mins} دقیقه)')
    send_ok = [t for t in trials if t['ok'] and not str(t['method']).startswith('delete') and t['method'] != 'discover_client_methods']
    lines.append(f'جمع ارسال موفق: {len(send_ok)} از متدهای تست‌شده')

    return {
        'ok': True,
        'matrix': True,
        'linkyar_only': True,
        'no_bot': True,
        'probes': {
            'channel_ref': ref,
            'channel_name': channel.name,
            'ly_source': {'peer': ly_peer, 'mid': ly_mid, 'date': ly_date, 'src_ref': src_ref},
            'has_local_file': bool(file_path),
            'libs': libs_info,
        },
        'trials': trials,
        'message': '\n'.join(lines),
    }




def validate_banner_forward_source(banner_id: int) -> Dict[str, Any]:
    """مقایسهٔ فیلدهای ذخیره‌شدهٔ بنر با تاریخچهٔ زندهٔ لینک‌بانک.

    اگر rid/date ذخیره‌شده غلط یا خالی باشد، فوروارد با دادهٔ DB شکست می‌خورد
    حتی وقتی API فوروارد سالم است.
    """
    from orders.models import CustomerBanner
    from orders.banner_publish import linkbank_channel

    bn = CustomerBanner.objects.filter(id=int(banner_id)).first()
    if not bn:
        return {'ok': False, 'error': 'banner_not_found'}

    lb = linkbank_channel()
    db = {
        'banner_id': bn.id,
        'title': (bn.caption or '')[:80],
        'from_linkbank': bool(bn.from_linkbank),
        'linkbank_chat_id': str(bn.linkbank_chat_id or ''),
        'linkbank_message_id': str(bn.linkbank_message_id or ''),  # اغلب mid بات
        'linkyar_rid': str(getattr(bn, 'linkyar_rid', None) or ''),
        'linkyar_date': str(getattr(bn, 'linkyar_date', None) or ''),
        'linkyar_seq': str(getattr(bn, 'linkyar_seq', None) or ''),
        'caption_head': (bn.caption or '')[:40],
    }
    warnings: List[str] = []
    if not db['from_linkbank']:
        warnings.append('from_linkbank=False — بنر در لینک‌بانک علامت نخورده')
    if not db['linkyar_rid'] or not db['linkyar_date']:
        warnings.append('linkyar_rid/date خالی است — فوروارد لینک‌یار به mid بات تکیه می‌کند که معمولاً غلط است')
    if db['linkbank_message_id'] and db['linkyar_rid'] and db['linkbank_message_id'] == db['linkyar_rid']:
        warnings.append('linkbank_message_id با linkyar_rid یکی است (غیرعادی)')

    hist = ly.load_channel_history(db['linkbank_chat_id'] or lb, limit=60)
    live: Dict[str, Any] = {
        'ok': bool(isinstance(hist, dict) and hist.get('ok')),
        'error': (hist or {}).get('error') if isinstance(hist, dict) else 'no_hist',
        'peer_id': (hist or {}).get('peer_id') if isinstance(hist, dict) else None,
        'count': (hist or {}).get('count') if isinstance(hist, dict) else 0,
        'messages_sample': [],
    }
    posts = list((hist or {}).get('messages') or []) if isinstance(hist, dict) else []
    for p in posts[:8]:
        live['messages_sample'].append({
            'mid': p.get('message_id'),
            'date': p.get('date'),
            'kind': p.get('kind'),
            'preview': str(p.get('preview') or '')[:50],
        })

    # امتیاز تطبیق
    best = None
    best_score = -1
    for p in posts:
        score = 0
        reasons = []
        pmid = str(p.get('message_id') or '')
        pdate = str(p.get('date') or '')
        prev = str(p.get('preview') or '')
        if db['linkyar_rid'] and pmid == db['linkyar_rid']:
            score += 100
            reasons.append('rid_match')
        if db['linkyar_date'] and pdate == db['linkyar_date']:
            score += 40
            reasons.append('date_match')
        if db['linkbank_message_id'] and pmid == db['linkbank_message_id']:
            score += 20
            reasons.append('bot_mid_equals_internal')
        cap = db['caption_head']
        if cap and len(cap) >= 8 and cap in prev:
            score += 30
            reasons.append('caption_match')
        if score > best_score:
            best_score = score
            best = {
                'message_id': p.get('message_id'),
                'date': p.get('date'),
                'kind': p.get('kind'),
                'preview': prev[:60],
                'score': score,
                'reasons': reasons,
                'file_id': p.get('file_id'),
                'file_access_hash': p.get('file_access_hash'),
            }

    usable = bool(best and best_score >= 30)
    if best and best_score < 30:
        warnings.append(f'بهترین تطبیق ضعیف است (score={best_score}) — ممکن است پیام اشتباه فوروارد شود')
    if not posts:
        warnings.append('تاریخچهٔ لینک‌بانک خالی یا خوانده نشد')

    return {
        'ok': True,
        'db': db,
        'live': live,
        'best_match': best,
        'usable_for_forward': usable,
        'warnings': warnings,
        'hint': (
            'برای فوروارد از best_match.message_id + date استفاده شود، نه لزوماً linkbank_message_id بات.'
            if usable else
            'منبع زنده پیدا نشد — بنر را دوباره در لینک‌بانک منتشر کنید تا rid ذخیره شود.'
        ),
    }


def test_linkyar_forward_copy_delete(
    channel: Channel,
    banner_id: int,
    *,
    do_delete: bool = True,
) -> Dict[str, Any]:
    """فقط فوروارد / کپی / حذف — بدون آپلود، بدون جارو.

    ۱) اعتبارسنجی دادهٔ بنر در DB در برابر تاریخچهٔ زنده
    ۲) فوروارد با Message واقعی از load_history (امضای baleclient)
    ۳) در صورت موفقیت، حذف همان پیام فورواردشده
    """
    import time as _time
    from orders.banner_publish import linkbank_channel

    ref = channel_ref(channel)
    marker = f'ly-fwdchk-{int(_time.time())}'  # فقط برای لاگ
    validation = validate_banner_forward_source(int(banner_id))
    lines = [
        f'تست فوروارد لینک‌یار | کانال: {channel.name} ({ref})',
        f'بنر #{banner_id}',
        '— اعتبارسنجی منبع —',
    ]
    db = validation.get('db') or {}
    lines.append(
        f"DB: from_lb={db.get('from_linkbank')} chat={db.get('linkbank_chat_id') or '—'} "
        f"bot_mid={db.get('linkbank_message_id') or '—'} "
        f"ly_rid={db.get('linkyar_rid') or '—'} ly_date={db.get('linkyar_date') or '—'}"
    )
    for w in validation.get('warnings') or []:
        lines.append(f'⚠ {w}')
    best = validation.get('best_match')
    if best:
        lines.append(
            f"زنده: mid={best.get('message_id')} date={best.get('date')} "
            f"score={best.get('score')} reasons={best.get('reasons')} "
            f"prev={best.get('preview')!r}"
        )
    else:
        lines.append('زنده: هیچ پیامی در تاریخچهٔ لینک‌بانک تطبیق نشد')
    lines.append(validation.get('hint') or '')

    trials: List[Dict[str, Any]] = []

    def _trial(name: str, fn) -> Dict[str, Any]:
        t0 = _time.time()
        row: Dict[str, Any] = {
            'method': name, 'ok': False, 'error': '', 'message_id': None,
            'message_date': None, 'ms': 0, 'detail': '',
        }
        try:
            out = fn()
            if not isinstance(out, dict):
                out = {'ok': False, 'error': str(out)[:200]}
            row['ok'] = bool(out.get('ok'))
            row['error'] = str(out.get('error') or '')[:300]
            mid = out.get('message_id')
            try:
                row['message_id'] = int(mid) if mid is not None else None
            except (TypeError, ValueError):
                row['message_id'] = None
            if out.get('date') is not None:
                try:
                    row['message_date'] = int(out.get('date'))
                except (TypeError, ValueError):
                    pass
            row['detail'] = str({k: out.get(k) for k in ('method', 'tries', 'combo', 'note') if k in out})[:200]
        except Exception as e:
            logger.exception('fwdchk %s', name)
            row['error'] = f'{type(e).__name__}:{e}'[:300]
        row['ms'] = int((_time.time() - t0) * 1000)
        trials.append(row)
        return row

    if not validation.get('usable_for_forward') or not best:
        lines.append('— ارسال —')
        lines.append('✗ فوروارد انجام نشد: منبع بنر قابل‌اعتماد نیست (اول داده را درست کنید)')
        return {
            'ok': False,
            'validation': validation,
            'trials': trials,
            'message': '\n'.join(lines),
            'error': 'bad_banner_source',
        }

    src_ref = db.get('linkbank_chat_id') or linkbank_channel()
    want_mid = int(best['message_id'])
    want_date = int(best.get('date') or 0)

    def t_native_forward():
        async def _fn(client):
            from aiobale.enums import ChatType
            src_res = await ly._resolve_peer(client, src_ref)
            dst_res = await ly._resolve_peer(client, ref)
            if not src_res.get('ok'):
                return {'ok': False, 'error': f"src:{src_res.get('error')}"}
            if not dst_res.get('ok'):
                return {'ok': False, 'error': f"dst:{dst_res.get('error')}"}
            src_id = int(src_res['peer_id'])
            dst_id = int(dst_res['peer_id'])
            tries = []
            hist_msgs = []
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    hist_msgs = await client.load_history(chat_id=src_id, chat_type=ctype, limit=50)
                    if hist_msgs:
                        tries.append(f'hist/{ctype}:n={len(hist_msgs)}')
                        break
                except Exception as e:
                    tries.append(f'hist/{ctype}:{type(e).__name__}:{e}')
            if not hist_msgs:
                return {'ok': False, 'error': 'source_history_empty', 'tries': tries}
            target = None
            for m in hist_msgs:
                try:
                    if int(getattr(m, 'message_id', 0) or 0) == want_mid:
                        target = m
                        break
                except Exception:
                    continue
            if target is None:
                return {
                    'ok': False,
                    'error': f'source_mid_not_in_history want={want_mid}',
                    'tries': tries,
                    'available': [getattr(m, 'message_id', None) for m in hist_msgs[:10]],
                }
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    await client.forward_message(message=target, chat_id=dst_id, chat_type=ctype)
                    # verify: history dst
                    import asyncio as _aio
                    await _aio.sleep(1.2)
                    after = []
                    try:
                        after = await client.load_history(chat_id=dst_id, chat_type=ctype, limit=12)
                    except Exception as e:
                        tries.append(f'verify/{ctype}:{type(e).__name__}:{e}')
                    # pick newest
                    new_mid = None
                    new_date = None
                    if after:
                        top = after[0]
                        new_mid = getattr(top, 'message_id', None)
                        new_date = getattr(top, 'date', None)
                        if hasattr(new_date, 'value'):
                            new_date = new_date.value
                    return {
                        'ok': True,
                        'method': f'forward/{ctype}',
                        'message_id': int(new_mid) if new_mid is not None else None,
                        'date': int(new_date) if new_date is not None else None,
                        'src_mid': want_mid,
                        'tries': tries,
                    }
                except Exception as e:
                    tries.append(f'forward/{ctype}:{type(e).__name__}:{e}')
            return {'ok': False, 'error': 'forward_all_types_failed', 'tries': tries}

        return ly._run(ly._with_client(_fn))

    def t_forward_messages_list():
        async def _fn(client):
            from aiobale.enums import ChatType
            src_res = await ly._resolve_peer(client, src_ref)
            dst_res = await ly._resolve_peer(client, ref)
            if not src_res.get('ok') or not dst_res.get('ok'):
                return {'ok': False, 'error': 'resolve_failed'}
            src_id = int(src_res['peer_id'])
            dst_id = int(dst_res['peer_id'])
            msgs = []
            for ctype in (ChatType.GROUP, ChatType.CHANNEL):
                try:
                    msgs = await client.load_history(chat_id=src_id, chat_type=ctype, limit=50)
                    if msgs:
                        break
                except Exception:
                    continue
            target = None
            for m in msgs:
                try:
                    if int(getattr(m, 'message_id', 0) or 0) == want_mid:
                        target = m
                        break
                except Exception:
                    continue
            if target is None:
                return {'ok': False, 'error': 'mid_not_found'}
            last = ''
            for ctype in (ChatType.GROUP, ChatType.CHANNEL):
                try:
                    await client.forward_messages(messages=[target], chat_id=dst_id, chat_type=ctype)
                    return {'ok': True, 'method': f'forward_messages/{ctype}', 'message_id': want_mid}
                except Exception as e:
                    last = f'{ctype}:{type(e).__name__}:{e}'
            return {'ok': False, 'error': last}

        return ly._run(ly._with_client(_fn))

    lines.append('— فوروارد / کپی —')
    r1 = _trial('native forward_message', t_native_forward)
    lines.append(('✓' if r1['ok'] else '✗') + f" forward_message ({r1['ms']}ms) " + (r1['error'] or f"mid={r1['message_id']}"))
    r2 = _trial('native forward_messages', t_forward_messages_list)
    lines.append(('✓' if r2['ok'] else '✗') + f" forward_messages ({r2['ms']}ms) " + (r2['error'] or f"mid={r2['message_id']}"))

    # حذف فقط mid فورواردشده (نه جارو)
    lines.append('— حذف (فقط پیام فوروارد این تست) —')
    deleted_any = False
    if do_delete:
        for row in (r1, r2):
            if not row.get('ok') or not row.get('message_id'):
                continue
            mid = int(row['message_id'])
            mdate = int(row.get('message_date') or 0)
            # اگر mid همان src باشد، حذف نکن — اشتباه است
            if mid == want_mid:
                lines.append(f'⊘ حذف نشد mid={mid} (همان مبدأ است، فوروارد mid جدید نداد)')
                continue
            t0 = _time.time()
            try:
                dr = ly.delete_message(ref, mid, message_date=mdate)
                ok = bool(isinstance(dr, dict) and dr.get('ok'))
                err = '' if ok else str((dr or {}).get('error') or 'fail')[:160]
            except Exception as e:
                ok = False
                err = f'{type(e).__name__}:{e}'[:160]
            ms = int((_time.time() - t0) * 1000)
            trials.append({
                'method': f'delete:{mid}', 'ok': ok, 'error': err,
                'message_id': mid, 'message_date': mdate, 'ms': ms, 'detail': '',
            })
            lines.append(('✓' if ok else '✗') + f' delete mid={mid} ({ms}ms) {err}')
            if ok:
                deleted_any = True
    if not deleted_any and not any(t.get('ok') for t in trials if t['method'].startswith('native')):
        lines.append('حذفی انجام نشد (فوروارد موفق نبود یا mid جدید نداشت)')

    lines.append(f'marker={marker} (فقط لاگ — جارو غیرفعال)')
    any_fwd = any(t.get('ok') for t in trials if 'forward' in t['method'])
    return {
        'ok': any_fwd,
        'validation': validation,
        'trials': trials,
        'message': '\n'.join(lines),
        'source_mid': want_mid,
        'source_date': want_date,
    }





def test_balelink_text_forward_channels(
    *,
    source_ref: str = '@linktest',
    dest_ref: str = '@linktest2',
    do_delete: bool = True,
) -> Dict[str, Any]:
    """تست فوروارد با سشن واقعی Balelink (نه JWT تزریقی).

    نیاز: ``balelink login me`` روی سرور → ~/.balelink/me.bale
    مسیر: متن → مبدأ → فوروارد → مقصد → حذف فقط همین پیام‌ها
    """
    import os
    import time as _time

    src_ref = str(source_ref or '@linktest').strip()
    dst_ref = str(dest_ref or '@linktest2').strip()
    marker = f'ly-bl-{int(_time.time())}-{int(_time.time() * 1000) % 10000}'
    text = f'[{marker}] تست فوروارد balelink {src_ref}→{dst_ref}'
    lines = [
        f'تست فوروارد با Balelink | {src_ref} → {dst_ref}',
        f'marker: {marker}',
    ]
    trials: List[Dict[str, Any]] = []

    # peer idهای شناخته‌شده از تست‌های قبلی (در صورت نبود در dialogs)
    known_ids = {
        '@linktest': 1497133952,
        'linktest': 1497133952,
        '@linktest2': 781346644,
        'linktest2': 781346644,
    }

    def _row(method: str, ok: bool, err: str = '', mid=None, ms: int = 0, detail: str = '') -> Dict[str, Any]:
        r = {
            'method': method, 'ok': ok, 'error': (err or '')[:300],
            'message_id': int(mid) if mid is not None else None,
            'message_date': None, 'ms': ms, 'detail': detail[:200],
        }
        trials.append(r)
        return r

    try:
        from balelink import BaleClient
        from balelink.models import Chat, ChatKind
    except Exception as e:
        lines.append(f'✗ balelink نصب نیست: {type(e).__name__}: {e}')
        return {
            'ok': False, 'error': 'balelink_missing', 'message': '\n'.join(lines),
            'trials': trials, 'marker': marker,
            'hint': 'روی سرور: pip install balelink && balelink login me',
        }

    home = os.environ.get('BALELINK_HOME') or os.path.expanduser('~/.balelink')
    session_path = os.path.join(home, 'me.bale')
    lines.append(f'session: {session_path} exists={os.path.isfile(session_path)}')

    async def _run():
        async with BaleClient('me', directory=home) as bale:
            if not getattr(bale, 'is_logged_in', False):
                # بعضی نسخه‌ها is_logged_in بعد از enter ست می‌شود
                me = getattr(bale, 'me', None)
                if me is None:
                    return {'ok': False, 'error': 'not_logged_in', 'detail': f'no session at {session_path}'}

            me = getattr(bale, 'me', None)
            me_id = getattr(me, 'id', None) if me else None
            lines_local = [f'me={me_id}']

            # dialogs برای تشخیص kind
            dialogs = []
            try:
                dialogs = await bale.dialogs(limit=100)
                lines_local.append(f'dialogs={len(dialogs)}')
            except Exception as e:
                lines_local.append(f'dialogs_err:{type(e).__name__}:{e}')

            def _pick_chat(ref: str) -> Optional[Any]:
                key = ref.lstrip('@').lower()
                # 1) از dialogs با username در group_info — فقط id
                want_id = known_ids.get(ref) or known_ids.get(key)
                if want_id:
                    for d in dialogs:
                        if int(getattr(d, 'id', 0) or 0) == int(want_id):
                            return d
                    # kind را حدس بزن
                    for kind in (ChatKind.GROUP, ChatKind.CHANNEL, ChatKind.SUPER_GROUP):
                        return Chat(int(want_id), kind)
                # 2) اگر ref عددی است
                if ref.lstrip('-').isdigit():
                    for d in dialogs:
                        if int(d.id) == int(ref):
                            return d
                    return Chat(int(ref), ChatKind.GROUP)
                return None

            src_chat = _pick_chat(src_ref)
            dst_chat = _pick_chat(dst_ref)
            if src_chat is None or dst_chat is None:
                return {
                    'ok': False,
                    'error': f'resolve_failed src={src_chat} dst={dst_chat}',
                    'lines': lines_local,
                    'dialog_ids': [getattr(d, 'id', None) for d in dialogs[:20]],
                }
            lines_local.append(f'src_chat={src_chat.id}/{getattr(src_chat.kind, "value", src_chat.kind)}')
            lines_local.append(f'dst_chat={dst_chat.id}/{getattr(dst_chat.kind, "value", dst_chat.kind)}')

            # ارسال متن — اگر kind غلط بود، چند kind را امتحان کن
            sent = None
            send_err = ''
            for kind in (
                getattr(src_chat, 'kind', ChatKind.GROUP),
                ChatKind.GROUP,
                ChatKind.CHANNEL,
                ChatKind.SUPER_GROUP,
            ):
                try_chat = Chat(int(src_chat.id), kind)
                try:
                    sent = await bale.send_text(try_chat, text)
                    src_chat = try_chat
                    send_err = ''
                    break
                except Exception as e:
                    send_err = f'{kind}:{type(e).__name__}:{e}'
            if sent is None:
                return {'ok': False, 'error': f'send_failed:{send_err}', 'lines': lines_local}

            sent_id = getattr(sent, 'id', None)
            lines_local.append(f'sent id={sent_id} chat={src_chat.id}')

            # فوروارد
            fwd_err = ''
            fwd_ok = False
            for kind in (
                getattr(dst_chat, 'kind', ChatKind.GROUP),
                ChatKind.GROUP,
                ChatKind.CHANNEL,
                ChatKind.SUPER_GROUP,
            ):
                try_dst = Chat(int(dst_chat.id), kind)
                try:
                    await bale.forward_messages([sent], try_dst)
                    dst_chat = try_dst
                    fwd_ok = True
                    fwd_err = ''
                    break
                except Exception as e:
                    fwd_err = f'{kind}:{type(e).__name__}:{e}'
                    # جایگزین: message.forward
                    try:
                        await sent.forward(try_dst)
                        dst_chat = try_dst
                        fwd_ok = True
                        fwd_err = ''
                        break
                    except Exception as e2:
                        fwd_err = f'{kind}:fwd={type(e).__name__}:{e}|msg.fwd={type(e2).__name__}:{e2}'

            # تأیید در مقصد
            dest_mid = None
            if fwd_ok:
                import asyncio as _aio
                await _aio.sleep(1.2)
                try:
                    hist = await bale.history(dst_chat, limit=15)
                    for m in hist:
                        if marker in str(getattr(m, 'text', None) or ''):
                            dest_mid = getattr(m, 'id', None)
                            break
                    if dest_mid is None and hist:
                        dest_mid = getattr(hist[0], 'id', None)
                        lines_local.append('dest_marker_not_found_using_top')
                except Exception as e:
                    lines_local.append(f'dest_hist:{type(e).__name__}:{e}')

            # حذف
            deleted = []
            if do_delete:
                try:
                    await sent.delete(just_me=False)
                    deleted.append(f'src:{sent_id}:ok')
                except Exception as e:
                    deleted.append(f'src:{sent_id}:{type(e).__name__}:{e}')
                if dest_mid:
                    try:
                        # پیدا کردن Message در تاریخچه برای delete
                        hist = await bale.history(dst_chat, limit=20)
                        target_m = None
                        for m in hist:
                            if getattr(m, 'id', None) == dest_mid or marker in str(getattr(m, 'text', None) or ''):
                                target_m = m
                                break
                        if target_m:
                            await target_m.delete(just_me=False)
                            deleted.append(f'dst:{dest_mid}:ok')
                        else:
                            deleted.append(f'dst:{dest_mid}:not_found')
                    except Exception as e:
                        deleted.append(f'dst:{dest_mid}:{type(e).__name__}:{e}')

            return {
                'ok': bool(fwd_ok),
                'sent_id': sent_id,
                'dest_mid': dest_mid,
                'fwd_error': fwd_err,
                'deleted': deleted,
                'lines': lines_local,
                'src': f'{src_chat.id}/{src_chat.kind}',
                'dst': f'{dst_chat.id}/{dst_chat.kind}',
            }

    t0 = _time.time()
    try:
        out = ly._run(_run())
    except Exception as e:
        logger.exception('balelink test')
        out = {'ok': False, 'error': f'{type(e).__name__}:{e}'}
    ms = int((_time.time() - t0) * 1000)

    if not isinstance(out, dict):
        out = {'ok': False, 'error': str(out)}

    for ln in out.get('lines') or []:
        lines.append(str(ln))
    if out.get('error') and not out.get('sent_id'):
        lines.append(f'✗ {out.get("error")}')
    else:
        lines.append(('✓' if out.get('sent_id') else '✗') + f" ارسال ({ms}ms) mid={out.get('sent_id')}")
        if out.get('ok'):
            lines.append(f"✓ فوروارد به {dst_ref} dest_mid={out.get('dest_mid')}")
        else:
            lines.append(f"✗ فوروارد: {out.get('fwd_error') or out.get('error') or 'failed'}")
        for d in out.get('deleted') or []:
            lines.append(f'حذف: {d}')

    _row('balelink_send', bool(out.get('sent_id')), out.get('error') or '', out.get('sent_id'), ms)
    _row('balelink_forward', bool(out.get('ok')), out.get('fwd_error') or out.get('error') or '', out.get('dest_mid'), 0)

    lines.append('نتیجه: ' + ('فوروارد موفق (balelink)' if out.get('ok') else 'فوروارد ناموفق'))
    return {
        'ok': bool(out.get('ok')),
        'marker': marker,
        'source': src_ref,
        'dest': dst_ref,
        'source_mid': out.get('sent_id'),
        'dest_mid': out.get('dest_mid'),
        'trials': trials,
        'message': '\n'.join(lines),
        'lib': 'balelink',
        'raw': {k: out.get(k) for k in ('src', 'dst', 'fwd_error', 'deleted', 'error')},
    }



def test_linkyar_text_forward_channels(
    *,
    source_ref: str = '@linktest',
    dest_ref: str = '@linktest2',
    do_delete: bool = True,
) -> Dict[str, Any]:
    """مسیر ساده و قطعی برای تست فوروارد حساب شخصی — بدون بنر/آپلود.

    ۱) لینک‌یار یک متن یکتا به source می‌فرستد
    ۲) همان پیام را از تاریخچه برمی‌دارد
    ۳) با client.forward_message به dest فوروارد می‌کند
    ۴) در صورت درخواست، فقط همان دو پیام (متن + فوروارد) را حذف می‌کند
    """
    import time as _time

    src = str(source_ref or '@linktest').strip()
    dst = str(dest_ref or '@linktest2').strip()
    if src and not src.startswith('@') and not src.lstrip('-').isdigit():
        src = '@' + src.lstrip('@')
    if dst and not dst.startswith('@') and not dst.lstrip('-').isdigit():
        dst = '@' + dst.lstrip('@')

    marker = f'ly-chfwd-{int(_time.time())}-{int(_time.time() * 1000) % 10000}'
    text = f'[{marker}] تست فوروارد لینک‌یار linktest→linktest2'
    lines = [
        f'تست فوروارد کانال‌به‌کانال (فقط لینک‌یار)',
        f'مبدأ: {src}  →  مقصد: {dst}',
        f'marker: {marker}',
    ]
    trials: List[Dict[str, Any]] = []

    def _row(method: str, out: Dict[str, Any], ms: int) -> Dict[str, Any]:
        row = {
            'method': method,
            'ok': bool(out.get('ok')),
            'error': str(out.get('error') or '')[:300],
            'message_id': None,
            'message_date': None,
            'ms': ms,
            'detail': str({k: out.get(k) for k in ('method', 'tries', 'combo') if k in out})[:180],
        }
        mid = out.get('message_id')
        try:
            row['message_id'] = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            pass
        if out.get('date') is not None:
            try:
                row['message_date'] = int(out.get('date'))
            except (TypeError, ValueError):
                pass
        trials.append(row)
        return row

    # ۱) ارسال متن به مبدأ
    t0 = _time.time()
    try:
        sent = ly.send_text_to_channel(src, text)
    except Exception as e:
        sent = {'ok': False, 'error': f'{type(e).__name__}:{e}'}
    r_send = _row('send_text_source', sent if isinstance(sent, dict) else {'ok': False, 'error': str(sent)}, int((_time.time() - t0) * 1000))
    lines.append(('✓' if r_send['ok'] else '✗') + f" ارسال متن به {src} ({r_send['ms']}ms) " + (r_send['error'] or f"mid={r_send['message_id']}"))
    if not r_send['ok']:
        lines.append('ارسال به مبدأ ناموفق — فوروارد انجام نشد')
        return {'ok': False, 'trials': trials, 'message': '\n'.join(lines), 'marker': marker}

    src_mid = r_send.get('message_id')
    src_date = r_send.get('message_date')

    # اگر mid از send نیامد، از تاریخچه با marker پیدا کن
    def _find_in_history(channel_ref: str, needle: str) -> Dict[str, Any]:
        hist = ly.load_channel_history(channel_ref, limit=25)
        if not isinstance(hist, dict) or not hist.get('ok'):
            return {'ok': False, 'error': str((hist or {}).get('error') or 'history_failed')}
        for p in list(hist.get('messages') or []):
            prev = str(p.get('preview') or p.get('text') or p.get('caption') or '')
            if needle not in prev:
                continue
            try:
                return {
                    'ok': True,
                    'message_id': int(p.get('message_id') or 0),
                    'date': int(p.get('date') or 0),
                    'preview': prev[:60],
                }
            except (TypeError, ValueError):
                continue
        return {'ok': False, 'error': 'marker_not_in_history', 'count': hist.get('count')}

    if not src_mid:
        _time.sleep(1.0)
        found = _find_in_history(src, marker)
        r_find = _row('find_source_by_marker', found, 0)
        lines.append(('✓' if found.get('ok') else '✗') + f" پیدا کردن در مبدأ: {found.get('error') or found.get('message_id')}")
        if found.get('ok'):
            src_mid = found.get('message_id')
            src_date = found.get('date')
    else:
        # تأیید marker در تاریخچه
        _time.sleep(0.6)
        found = _find_in_history(src, marker)
        if found.get('ok') and found.get('message_id'):
            src_mid = found.get('message_id')
            src_date = found.get('date') or src_date
            lines.append(f"تأیید در تاریخچه مبدأ: mid={src_mid} date={src_date}")

    if not src_mid:
        lines.append('✗ mid مبدأ مشخص نشد')
        return {'ok': False, 'trials': trials, 'message': '\n'.join(lines), 'marker': marker}

    # ۲) فوروارد native
    def t_forward():
        async def _fn(client):
            """فوروارد با Peer کامل (access_hash) و date صحیح — نه فقط API سطح بالا بدون hash."""
            from aiobale.enums import ChatType, PeerType
            from aiobale.types import Peer, InfoMessage
            from aiobale.types.values import IntValue
            from aiobale.methods.messaging.forward_message import ForwardMessages
            from aiobale.utils import generate_id
            import asyncio as _aio

            src_res = await ly._resolve_peer(client, src)
            dst_res = await ly._resolve_peer(client, dst)
            if not src_res.get('ok'):
                return {'ok': False, 'error': f"src_resolve:{src_res.get('error')}"}
            if not dst_res.get('ok'):
                return {'ok': False, 'error': f"dst_resolve:{dst_res.get('error')}"}
            src_id = int(src_res['peer_id'])
            dst_id = int(dst_res['peer_id'])
            src_ah = src_res.get('access_hash')
            dst_ah = dst_res.get('access_hash')
            try:
                src_ah_i = int(src_ah) if src_ah not in (None, '', 0, '0') else None
            except (TypeError, ValueError):
                src_ah_i = None
            try:
                dst_ah_i = int(dst_ah) if dst_ah not in (None, '', 0, '0') else None
            except (TypeError, ValueError):
                dst_ah_i = None

            tries = [f'src={src_id} ah={src_ah_i} dst={dst_id} ah={dst_ah_i} want_mid={src_mid}']
            hist_msgs = []
            hist_ctype = None
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    hist_msgs = await client.load_history(chat_id=src_id, chat_type=ctype, limit=30)
                    if hist_msgs:
                        hist_ctype = ctype
                        tries.append(f'hist/{ctype}:n={len(hist_msgs)}')
                        break
                except Exception as e:
                    tries.append(f'hist/{ctype}:{type(e).__name__}:{e}')
            if not hist_msgs:
                return {'ok': False, 'error': 'source_history_empty', 'tries': tries}

            target = None
            for m in hist_msgs:
                try:
                    if int(getattr(m, 'message_id', 0) or 0) == int(src_mid):
                        target = m
                        break
                except Exception:
                    continue
            if target is None:
                for m in hist_msgs:
                    txt = str(getattr(m, 'text', None) or '')
                    if marker in txt:
                        target = m
                        break
            if target is None:
                return {
                    'ok': False,
                    'error': f'mid_not_in_load_history want={src_mid}',
                    'tries': tries,
                    'sample_ids': [getattr(m, 'message_id', None) for m in hist_msgs[:8]],
                }

            # date را همیشه به int خام تبدیل کن (IntValue تو در تو = InvalidArgument)
            raw_date = getattr(target, 'date', None)
            if hasattr(raw_date, 'value'):
                raw_date = raw_date.value
            try:
                date_i = int(raw_date) if raw_date is not None else int(src_date or 0)
            except (TypeError, ValueError):
                date_i = int(src_date or 0)
            mid_i = int(getattr(target, 'message_id', src_mid) or src_mid)
            tries.append(f'target mid={mid_i} date={date_i} hist_ctype={hist_ctype}')

            def _src_peer(with_ah: bool) -> Peer:
                kw = {'type': PeerType.GROUP, 'id': src_id}
                if with_ah and src_ah_i is not None:
                    kw['access_hash'] = src_ah_i
                return Peer(**kw)

            def _dst_peer(with_ah: bool) -> Peer:
                kw = {'type': PeerType.GROUP, 'id': dst_id}
                if with_ah and dst_ah_i is not None:
                    kw['access_hash'] = dst_ah_i
                return Peer(**kw)

            async def _try_fwd(label, info, dst_peer):
                new_id = generate_id()
                call = ForwardMessages(
                    peer=dst_peer,
                    message_ids=[new_id],
                    forwarded_messages=[info],
                )
                try:
                    await client(call)
                    return True, new_id, ''
                except Exception as e:
                    return False, None, f'{label}:{type(e).__name__}:{e}'

            # ترکیب‌های محتمل که InvalidArgument را پوشش می‌دهند
            combos = []
            for with_src_ah in (True, False):
                for with_dst_ah in (True, False):
                    for date_mode in ('int', 'IntValue'):
                        combos.append((with_src_ah, with_dst_ah, date_mode))

            for with_src_ah, with_dst_ah, date_mode in combos:
                if date_mode == 'int':
                    date_val = date_i
                else:
                    date_val = IntValue(value=date_i)
                info = InfoMessage(
                    peer=_src_peer(with_src_ah),
                    message_id=mid_i,
                    date=date_val,
                )
                dst_peer = _dst_peer(with_dst_ah)
                label = f'ah_src={with_src_ah}/ah_dst={with_dst_ah}/date={date_mode}'
                ok_call, new_id, err = await _try_fwd(label, info, dst_peer)
                if not ok_call:
                    tries.append(err[:180])
                    continue
                tries.append(f'{label}:api_ok new_id={new_id}')
                await _aio.sleep(1.2)
                # verify در مقصد
                for ctype in (ChatType.GROUP, ChatType.CHANNEL, hist_ctype or ChatType.GROUP):
                    if ctype is None:
                        continue
                    try:
                        after = await client.load_history(chat_id=dst_id, chat_type=ctype, limit=15)
                    except Exception as e:
                        tries.append(f'verify/{ctype}:{type(e).__name__}:{e}')
                        continue
                    for am in after or []:
                        txt = str(getattr(am, 'text', None) or '')
                        am_mid = getattr(am, 'message_id', None)
                        am_date = getattr(am, 'date', None)
                        if hasattr(am_date, 'value'):
                            am_date = am_date.value
                        if marker in txt or (new_id and am_mid == new_id):
                            return {
                                'ok': True,
                                'method': label,
                                'message_id': int(am_mid) if am_mid is not None else int(new_id),
                                'date': int(am_date) if am_date is not None else None,
                                'src_mid': mid_i,
                                'tries': tries,
                            }
                # API پذیرفت ولی در تاریخچه ندیدیم
                tries.append(f'{label}:accepted_not_visible')
                # اگر API پذیرفت، mid تولیدشده را برگردان (حذف ممکن شود)
                return {
                    'ok': True,
                    'method': label + '/unverified',
                    'message_id': int(new_id) if new_id else None,
                    'date': None,
                    'src_mid': mid_i,
                    'tries': tries,
                    'note': 'API accepted ForwardMessages; visibility not confirmed in history',
                }

            # آخرین تلاش: API سطح‌بالای کتابخانه (برای مقایسه)
            for ctype in (ChatType.GROUP, ChatType.CHANNEL):
                try:
                    await client.forward_message(message=target, chat_id=dst_id, chat_type=ctype)
                    tries.append(f'highlevel/{ctype}:ok')
                    return {
                        'ok': True,
                        'method': f'highlevel/{ctype}',
                        'message_id': None,
                        'date': None,
                        'src_mid': mid_i,
                        'tries': tries,
                    }
                except Exception as e:
                    tries.append(f'highlevel/{ctype}:{type(e).__name__}:{e}')

            return {'ok': False, 'error': 'forward_failed', 'tries': tries}

        return ly._run(ly._with_client(_fn))

    t0 = _time.time()
    fwd = t_forward()
    if not isinstance(fwd, dict):
        fwd = {'ok': False, 'error': str(fwd)}
    r_fwd = _row('forward_to_dest', fwd, int((_time.time() - t0) * 1000))
    lines.append(('✓' if r_fwd['ok'] else '✗') + f" فوروارد به {dst} ({r_fwd['ms']}ms) " + (r_fwd['error'] or f"mid={r_fwd['message_id']}"))
    if r_fwd.get('detail'):
        lines.append(f"  detail: {r_fwd['detail']}")
    if isinstance(fwd, dict) and fwd.get('tries'):
        lines.append('  tries: ' + ' | '.join(str(x) for x in fwd['tries'][:8]))

    # ۳) حذف فقط midهای این تست
    if do_delete:
        lines.append('— حذف فقط پیام‌های این تست —')
        to_del = []
        if src_mid:
            to_del.append((src, int(src_mid), int(src_date or 0), 'source'))
        if r_fwd.get('ok') and r_fwd.get('message_id') and r_fwd['message_id'] != src_mid:
            to_del.append((dst, int(r_fwd['message_id']), int(r_fwd.get('message_date') or 0), 'dest'))
        # اگر dest mid نداشت، با marker در dest پیدا کن
        if r_fwd.get('ok') and not r_fwd.get('message_id'):
            _time.sleep(0.8)
            df = _find_in_history(dst, marker)
            if df.get('ok') and df.get('message_id'):
                to_del.append((dst, int(df['message_id']), int(df.get('date') or 0), 'dest_by_marker'))
        for ch_ref, mid, mdate, label in to_del:
            t0 = _time.time()
            try:
                dr = ly.delete_message(ch_ref, mid, message_date=mdate)
                ok = bool(isinstance(dr, dict) and dr.get('ok'))
                err = '' if ok else str((dr or {}).get('error') or 'fail')[:160]
            except Exception as e:
                ok, err = False, f'{type(e).__name__}:{e}'[:160]
            ms = int((_time.time() - t0) * 1000)
            trials.append({'method': f'delete_{label}', 'ok': ok, 'error': err, 'message_id': mid, 'message_date': mdate, 'ms': ms, 'detail': ch_ref})
            lines.append(('✓' if ok else '✗') + f' حذف {label} {ch_ref} mid={mid} ({ms}ms) {err}')

    ok = bool(r_send.get('ok') and r_fwd.get('ok'))
    lines.append('نتیجه: ' + ('فوروارد موفق' if ok else 'فوروارد ناموفق'))
    return {
        'ok': ok,
        'marker': marker,
        'source': src,
        'dest': dst,
        'source_mid': src_mid,
        'dest_mid': r_fwd.get('message_id'),
        'trials': trials,
        'message': '\n'.join(lines),
    }



def _pending_deletes_path():
    from pathlib import Path
    from django.conf import settings
    root = Path(getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent))
    path = root / 'tmp' / 'pending_test_deletes.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _schedule_test_delete(
    *,
    ref: str,
    mode: str,
    bot_message_id: Optional[int],
    ly_message_id: Optional[int],
    ly_message_date: int,
    minutes: int,
) -> None:
    """حذف تستی پایدار — در فایل صف می‌شود (Passenger نخ را می‌کشد)."""
    import time as _t
    due = _t.time() + max(1, int(minutes)) * 60
    entry = {
        'due': due,
        'ref': str(ref),
        'mode': str(mode),
        'bot_message_id': int(bot_message_id) if bot_message_id else None,
        'ly_message_id': int(ly_message_id) if ly_message_id else None,
        'ly_message_date': int(ly_message_date or 0),
    }
    path = _pending_deletes_path()
    try:
        rows = []
        if path.exists():
            rows = json.loads(path.read_text(encoding='utf-8') or '[]')
            if not isinstance(rows, list):
                rows = []
        rows.append(entry)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        logger.info('scheduled test delete due=%s ref=%s mid=%s', due, ref, bot_message_id or ly_message_id)
    except Exception:
        logger.exception('schedule test delete file')
        # fallback thread (ممکن است در Passenger زنده نماند)
        def _run() -> None:
            try:
                time.sleep(max(1, int(minutes)) * 60)
                if mode == Channel.PUBLISH_BOT and bot_message_id:
                    bc.delete_message(str(ref), int(bot_message_id))
                if mode == Channel.PUBLISH_LINKYAR and ly_message_id:
                    ly.delete_message(str(ref), int(ly_message_id), message_date=int(ly_message_date or 0))
            except Exception:
                logger.exception('test delete thread failed')
        threading.Thread(target=_run, daemon=True, name=f'test-del-{ref}').start()


def process_pending_test_deletes() -> int:
    """حذف‌های تستی سررسیدشده — از poll_bot / delete_expired صدا زده شود."""
    import time as _t
    path = _pending_deletes_path()
    if not path.exists():
        return 0
    try:
        rows = json.loads(path.read_text(encoding='utf-8') or '[]')
        if not isinstance(rows, list):
            return 0
    except Exception:
        logger.exception('read pending test deletes')
        return 0
    now = _t.time()
    keep = []
    n = 0
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        if float(entry.get('due') or 0) > now:
            keep.append(entry)
            continue
        ref = str(entry.get('ref') or '')
        mode = str(entry.get('mode') or '')
        try:
            if entry.get('bot_message_id'):
                r = bc.delete_message(ref, int(entry['bot_message_id']))
                logger.info('pending test delete bot ref=%s mid=%s r=%s', ref, entry['bot_message_id'], r)
                n += 1
            if entry.get('ly_message_id'):
                r = ly.delete_message(
                    ref,
                    int(entry['ly_message_id']),
                    message_date=int(entry.get('ly_message_date') or 0),
                )
                logger.info('pending test delete ly ref=%s mid=%s r=%s', ref, entry['ly_message_id'], r)
                n += 1
        except Exception:
            logger.exception('pending test delete failed')
            keep.append(entry)  # retry later
    try:
        path.write_text(json.dumps(keep, ensure_ascii=False), encoding='utf-8')
    except Exception:
        logger.exception('write pending test deletes')
    return n


