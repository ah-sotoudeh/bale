"""Scheduled publish / delete by Link Yar + daily admin health check."""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from channels_app.models import Channel, ChannelGroup, Tariff
from integrations import bale_client as bc
from integrations import linkyar_client as ly
from orders.models import OrderItem
from wallet.services import credit_manager_for_execution, OPERATOR_BALE_ID

logger = logging.getLogger(__name__)


def channel_ref(ch: Channel) -> str:
    link = (ch.link or '').strip()
    return link or str(ch.id)


def check_channel_admin(ch: Channel) -> bool:
    ok = ly.is_admin_of_channel(channel_ref(ch))
    ch.linkyar_is_admin = ok
    ch.linkyar_checked_at = timezone.now()
    ch.save(update_fields=['linkyar_is_admin', 'linkyar_checked_at'])
    return ok


def deactivate_tariffs_for_channel(ch: Channel, reason: str) -> int:
    """Hide single-channel tariffs and package tariffs that include this channel."""
    n = 0
    qs = Tariff.objects.filter(channel=ch, is_active=True)
    n += qs.update(is_active=False)
    for g in ch.groups.all():
        n += Tariff.objects.filter(group=g, is_active=True).update(is_active=False)
    if ch.manager and ch.manager.bale_user_id:
        bc.send_message(
            ch.manager.bale_user_id,
            f'⚠️ تعرفه(های) مرتبط با «{ch.name}» موقتاً از فهرست خارج شد.\n'
            f'علت: {reason}\n'
            f'لطفاً {ly.linkyar_username()} را دوباره ادمین کانال کنید.',
        )
    return n


def daily_admin_audit() -> Dict[str, int]:
    """Once per day: verify Link Yar is admin on every channel that has tariffs."""
    channel_ids = set(
        Tariff.objects.filter(is_active=True, channel__isnull=False).values_list(
            'channel_id', flat=True
        )
    )
    for gid in Tariff.objects.filter(is_active=True, group__isnull=False).values_list(
        'group_id', flat=True
    ):
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
        if not check_channel_admin(ch):
            deactivated += deactivate_tariffs_for_channel(
                ch, f'{ly.linkyar_username()} دیگر مدیر کانال نیست'
            )
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


def _post_banner_to_channel(
    ch: Channel,
    from_chat_id: str,
    message_id: int,
    caption: str = '',
) -> Dict[str, Any]:
    """Copy/forward customer banner into channel. Returns API result + message_id if any."""
    ref = channel_ref(ch)
    # Prefer copy so it appears as channel post without "forwarded from"
    result = ly.copy_message(ref, from_chat_id, int(message_id), caption=caption or None)
    mid = None
    if result.get('ok') and result.get('result'):
        res = result['result']
        mid = res.get('message_id') if isinstance(res, dict) else res
    return {'api': result, 'channel_message_id': mid, 'channel_ref': ref}


@transaction.atomic
def publish_due_items() -> Dict[str, int]:
    """Publish paid items whose start time has arrived."""
    now = timezone.now()
    items = (
        OrderItem.objects.select_related(
            'order', 'order__customer', 'channel', 'tariff', 'tariff__group', 'manager'
        )
        .filter(execution_status='paid', manager_status='approved')
        .filter(Q(manager_edited_start__lte=now) | Q(manager_edited_start__isnull=True, requested_start__lte=now))
    )
    published = 0
    failed = 0

    for item in items:
        order = item.order
        if not order.banner_message_id or not order.banner_from_chat_id:
            logger.warning('item %s missing banner', item.id)
            continue

        start = item.effective_start
        if start and start > now:
            continue

        channels = targets_for_item(item)
        if not channels:
            continue

        posts: List[Dict[str, Any]] = []
        any_ok = False
        for ch in channels:
            if not check_channel_admin(ch):
                _fail_one_channel(item, ch, 'لینک‌یار ادمین نیست')
                failed += 1
                continue
            res = _post_banner_to_channel(
                ch,
                order.banner_from_chat_id,
                int(order.banner_message_id),
                caption=order.banner_caption or '',
            )
            if res.get('channel_message_id') or (res.get('api') or {}).get('ok'):
                any_ok = True
                posts.append(
                    {
                        'channel_id': ch.id,
                        'ref': res['channel_ref'],
                        'message_id': res.get('channel_message_id'),
                    }
                )
                # proof to customer
                cust = order.customer.bale_user_id
                if cust and res.get('channel_message_id'):
                    ly.forward_message(
                        cust, res['channel_ref'], int(res['channel_message_id'])
                    )
                    bc.send_message(
                        cust,
                        f'✅ بنر شما در «{ch.name}» منتشر شد.',
                    )
            else:
                _fail_one_channel(item, ch, str((res.get('api') or {}).get('error') or 'send_failed'))
                failed += 1

        if any_ok:
            item.execution_status = 'executed'
            item.executed_at = now
            # store first message id for delete job (multi: JSON in channel_message_id field as text)
            import json

            item.channel_message_id = json.dumps(posts, ensure_ascii=False)[:500]
            item.save(update_fields=['execution_status', 'executed_at', 'channel_message_id'])
            if item.manager:
                credit_manager_for_execution(item.manager, item.price, item.id)
            published += 1
        else:
            item.execution_status = 'failed_publish'
            item.save(update_fields=['execution_status'])

    return {'published': published, 'failed_channels': failed}


def _fail_one_channel(item: OrderItem, ch: Channel, reason: str) -> None:
    msg = (
        f'❌ ارسال تبلیغ آیتم #{item.id} در کانال «{ch.name}» ناموفق بود.\n'
        f'علت: {reason}'
    )
    if ch.manager and ch.manager.bale_user_id:
        bc.send_message(ch.manager.bale_user_id, msg)
    if OPERATOR_BALE_ID:
        bc.send_message(OPERATOR_BALE_ID, msg)
    logger.warning('publish fail item=%s channel=%s %s', item.id, ch.id, reason)


def delete_expired_posts() -> int:
    """Delete channel posts after requested_end."""
    import json

    now = timezone.now()
    items = OrderItem.objects.filter(
        execution_status='executed',
        requested_end__lte=now,
    ).exclude(channel_message_id__isnull=True).exclude(channel_message_id='')

    n = 0
    for item in items:
        try:
            posts = json.loads(item.channel_message_id)
        except Exception:
            posts = []
        if not isinstance(posts, list):
            posts = []
        for p in posts:
            mid = p.get('message_id')
            ref = p.get('ref')
            if mid and ref:
                ly.delete_message(str(ref), int(mid))
                n += 1
        item.channel_message_id = ''  # cleared after delete attempt
        item.save(update_fields=['channel_message_id'])
    return n
