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
    """مرجع مناسب برای Bot API: ترجیح @username، بعد chat_id عددی، بعد link."""
    link = (ch.link or '').strip()
    if link:
        s = link.replace('https://', '').replace('http://', '')
        for prefix in ('ble.ir/', 'bale.ai/'):
            if s.lower().startswith(prefix):
                s = s[len(prefix):].lstrip('/')
                break
        s = s.split('/')[0].strip()
        if s:
            if not s.startswith('@') and not s.lstrip('-').isdigit():
                s = '@' + s
            return s
    if getattr(ch, 'bale_peer_id', None):
        return str(ch.bale_peer_id)
    return str(ch.id)


def check_linkyar_admin(ch: Channel) -> str:
    state = ly.linkyar_admin_state(channel_ref(ch))
    if state in ('admin', 'not_admin'):
        ch.linkyar_is_admin = state == 'admin'
        ch.linkyar_checked_at = timezone.now()
        ch.save(update_fields=['linkyar_is_admin', 'linkyar_checked_at'])
    return state


def check_bot_admin(ch: Channel) -> str:
    state = bc.bot_admin_state(channel_ref(ch))
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
        'source_channel_ref': str(src_chat or lb),
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
    """فوروارد واقعی از لینک‌بانک با لینک‌یار (peer + access_hash + date)."""
    ref = channel_ref(ch)
    src = _resolve_linkbank_forward_source(from_chat_id, message_id, caption, banner_id)
    ly_peer = int(src.get('ly_peer_id') or 0)
    ly_mid = int(src.get('ly_message_id') or 0)
    ly_date = int(message_date or src.get('ly_message_date') or 0)
    ly_ah = src.get('ly_access_hash')
    src_ref = str(src.get('source_channel_ref') or src.get('linkbank_ref') or '')

    if not ly_peer or not ly_mid or not ly_date:
        return {
            'ok': False,
            'method': 'failed',
            'channel_ref': ref,
            'api': {
                'error': 'need_from_peer_and_date',
                'hist_error': src.get('hist_error'),
                'resolved': {'peer': ly_peer, 'mid': ly_mid, 'date': ly_date, 'ah': ly_ah},
            },
            'error': (
                f'فوروارد لینک‌یار: پیام در تاریخچه لینک‌بانک پیدا نشد '
                f'(peer={ly_peer}, mid={ly_mid}, date={ly_date})'
                + (f' — {src.get("hist_error")}' if src.get('hist_error') else '')
            )[:300],
        }

    result = ly.forward_to_channel(
        ref,
        from_peer_id=ly_peer,
        message_id=int(ly_mid),
        message_date=int(ly_date),
        from_peer_type=2,
        from_access_hash=int(ly_ah) if ly_ah is not None else None,
        source_channel_ref=src_ref or None,
    )
    if result.get('ok'):
        out = dict(result)
        out['message_date'] = int(result.get('message_date') or ly_date)
        out['message_id'] = ly_mid
        return {
            'api': out,
            'channel_ref': ref,
            'ok': True,
            'method': 'forward',
            'from_peer_id': ly_peer,
            'message_id': ly_mid,
            'message_date': out['message_date'],
        }

    err = str((result or {}).get('error') or 'فوروارد لینک‌یار ناموفق')
    tries = (result or {}).get('tries') or []
    if tries:
        err = f'{err} | {tries[0]}'[:400]
    return {
        'api': result if isinstance(result, dict) else {'ok': False},
        'channel_ref': ref,
        'ok': False,
        'method': 'failed',
        'error': err[:400],
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
        posted_bot_mid = ((res.get('api') or {}).get('result') or {}).get('message_id')
        result['bot_message_id'] = posted_bot_mid
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
        result['message'] = (result.get('message') or '') + f' — حذف خودکار تا {mins} دقیقه دیگر.'
        _schedule_test_delete(
            ref=ref,
            mode=mode,
            bot_message_id=int(posted_bot_mid) if posted_bot_mid else None,
            ly_message_id=int(posted_ly_mid) if posted_ly_mid else None,
            ly_message_date=int(posted_ly_date or 0),
            minutes=mins,
        )
    return result


def _schedule_test_delete(
    *,
    ref: str,
    mode: str,
    bot_message_id: Optional[int],
    ly_message_id: Optional[int],
    ly_message_date: int,
    minutes: int,
) -> None:
    """حذف پست تستی بعد از N دقیقه در thread پس‌زمینه."""

    def _run() -> None:
        try:
            time.sleep(max(1, int(minutes)) * 60)
            if mode == Channel.PUBLISH_BOT and bot_message_id:
                r = bc.delete_message(str(ref), int(bot_message_id))
                logger.info('test delete bot ref=%s mid=%s r=%s', ref, bot_message_id, r)
            if mode == Channel.PUBLISH_LINKYAR and ly_message_id:
                r = ly.delete_message(str(ref), int(ly_message_id), message_date=int(ly_message_date or 0))
                logger.info('test delete ly ref=%s mid=%s r=%s', ref, ly_message_id, r)
            # اگر هر دو شناسه داشتیم هر دو را امتحان کن
            if bot_message_id and mode != Channel.PUBLISH_BOT:
                try:
                    bc.delete_message(str(ref), int(bot_message_id))
                except Exception:
                    pass
            if ly_message_id and mode != Channel.PUBLISH_LINKYAR:
                try:
                    ly.delete_message(str(ref), int(ly_message_id), message_date=int(ly_message_date or 0))
                except Exception:
                    pass
        except Exception:
            logger.exception('test delete failed ref=%s', ref)

    threading.Thread(target=_run, daemon=True, name=f'test-del-{ref}').start()

