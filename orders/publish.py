"""Scheduled publish by mode + daily admin health check + permalink recovery."""
from __future__ import annotations

import json
import logging
import os
import time
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
    me = ly.get_me()
    if not me.get('ok'):
        return None
    try:
        return int(me.get('user_id')) if me.get('user_id') is not None else None
    except (TypeError, ValueError):
        return None


def channel_ref(ch: Channel) -> str:
    link = (ch.link or '').strip()
    return link or str(ch.id)


def check_linkyar_admin(ch: Channel) -> bool:
    ok = ly.is_admin_of_channel(channel_ref(ch))
    ch.linkyar_is_admin = ok
    ch.linkyar_checked_at = timezone.now()
    ch.save(update_fields=['linkyar_is_admin', 'linkyar_checked_at'])
    return ok


def check_bot_admin(ch: Channel) -> bool:
    ok = bc.bot_is_channel_admin(channel_ref(ch))
    ch.bot_is_admin = ok
    ch.bot_checked_at = timezone.now()
    ch.save(update_fields=['bot_is_admin', 'bot_checked_at'])
    return ok


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
        if mode == Channel.PUBLISH_BOT and not check_bot_admin(ch):
            deactivated += deactivate_tariffs_for_channel(ch, 'لینک‌ساز ادمین نیست')
        elif mode == Channel.PUBLISH_LINKYAR and not check_linkyar_admin(ch):
            deactivated += deactivate_tariffs_for_channel(ch, 'لینک‌یار ادمین نیست')
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


def _post_via_bot(ch: Channel, from_chat_id: str, message_id: int, caption: str = '') -> Dict[str, Any]:
    ref = channel_ref(ch)
    result = bc.forward_message(ref, from_chat_id, int(message_id))
    if not result.get('ok'):
        result = bc.copy_message(ref, from_chat_id, int(message_id), caption=caption or None)
    return {'api': result, 'channel_ref': ref, 'ok': bool(result.get('ok'))}


def _post_via_linkyar(ch: Channel, from_chat_id: str, message_id: int, caption: str = '') -> Dict[str, Any]:
    ref = channel_ref(ch)
    result = ly.copy_message(ref, from_chat_id, int(message_id), caption=caption or None)
    return {'api': result, 'channel_ref': ref, 'ok': bool(result.get('ok'))}


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
        credit_customer_refund(order.customer, item.price, item.id, f'عدم انتشار #{item.id}')
        if item.manager:
            apply_manager_penalty(item.manager, item.price, item.id)
        if order.customer.bale_user_id:
            bc.send_message(
                order.customer.bale_user_id,
                f'مبلغ {item.price:,} تومان بابت آیتم #{item.id} به کیف پول برگشت.',
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
                if not check_bot_admin(ch):
                    _fail_one_channel(item, ch, 'لینک‌ساز ادمین نیست')
                    failed += 1
                    continue
                res = _post_via_bot(ch, from_chat, msg_id, order.banner_caption or '')
                time.sleep(1.5)
                meta = recover_permalink(ch, min_date_ms=t0_ms, preferred_senders=[x for x in [bot_id] if x])
                if meta and meta.get('permalink'):
                    any_ok = True
                    _finalize_channel_ok(item, ch, meta, posts)
                elif res.get('ok'):
                    any_ok = True
                    posts.append({'channel_id': ch.id, 'ref': channel_ref(ch), 'permalink': ''})
                    if order.customer.bale_user_id:
                        bc.send_message(order.customer.bale_user_id, f'✅ بنر در «{ch.name}» ارسال شد.')
                else:
                    _fail_one_channel(item, ch, 'ارسال ناموفق')
                    failed += 1
                continue

            if mode == Channel.PUBLISH_LINKYAR:
                if not check_linkyar_admin(ch):
                    _fail_one_channel(item, ch, 'لینک‌یار ادمین نیست')
                    failed += 1
                    continue
                _post_via_linkyar(ch, from_chat, msg_id, order.banner_caption or '')
                time.sleep(2)
                meta = recover_permalink(ch, min_date_ms=t0_ms, preferred_senders=[x for x in [ly_id] if x])
                if not (meta and meta.get('permalink')):
                    meta = recover_permalink(ch, min_date_ms=t0_ms, preferred_senders=None)
                if meta and meta.get('permalink'):
                    any_ok = True
                    _finalize_channel_ok(item, ch, meta, posts)
                else:
                    _fail_one_channel(item, ch, 'تأیید لینک‌یار ناموفق')
                    failed += 1

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
        elif not any_manual:
            item.execution_status = 'failed_publish'
            item.save(update_fields=['execution_status'])
            _refund_failed_item(item)

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
            if mid and ref:
                ly.delete_message(str(ref), int(mid), message_date=int(date or 0))
                n += 1
        item.channel_message_id = ''
        item.save(update_fields=['channel_message_id'])
    return n
