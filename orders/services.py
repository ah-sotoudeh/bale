"""Business logic for order lifecycle — shared by API webhooks and poll_bot."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from bot_flow.jalali import format_slot

from integrations import bale_client as bale_client
from orders.models import Order

logger = logging.getLogger(__name__)


def ensure_banner_on_reference(order: Order) -> Dict[str, Any]:
    """پس از پرداخت: بنر را در کانال مرجع (فعلاً @linktest) با فوروارد نگه می‌داریم.

    زمان انتشار از همین پیام با نقل‌قول به کانال‌های هدف می‌رود.
    اگر CustomerBanner از قبل در مرجع باشد، همان استفاده می‌شود.
    """
    from orders.banner_publish import linkbank_channel

    ref = linkbank_channel()
    cb = order.customer_banner

    if cb and cb.from_linkbank and cb.linkbank_message_id:
        # قبلاً روی مرجع است
        return {
            'ok': True,
            'ref_chat': cb.linkbank_chat_id or ref,
            'ref_message_id': cb.linkbank_message_id,
            'reused': True,
        }

    if not order.banner_message_id or not order.banner_from_chat_id:
        return {'ok': False, 'error': 'no_banner'}

    try:
        mid = int(order.banner_message_id)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'bad_banner_id'}

    # فوروارد با نقل‌قول = برند مرجع دیده می‌شود
    fwd = bale_client.forward_message(ref, str(order.banner_from_chat_id), mid)
    if not fwd.get('ok'):
        logger.error('ensure_banner_on_reference forward failed order=%s', order.id)
        return {'ok': False, 'error': 'ref_publish_failed'}

    result = fwd.get('result') or {}
    ref_mid = str(result.get('message_id') or '')
    if not ref_mid:
        return {'ok': False, 'error': 'ref_no_message_id'}

    if cb:
        cb.from_linkbank = True
        cb.linkbank_chat_id = ref
        cb.linkbank_message_id = ref_mid
        cb.save(update_fields=['from_linkbank', 'linkbank_chat_id', 'linkbank_message_id'])
    else:
        from orders.models import CustomerBanner

        cb = CustomerBanner.objects.create(
            customer=order.customer,
            caption=order.banner_caption or '',
            storage_chat_id=str(order.banner_from_chat_id),
            storage_message_id=str(order.banner_message_id),
            from_linkbank=True,
            linkbank_chat_id=ref,
            linkbank_message_id=ref_mid,
            is_active=True,
        )
        order.customer_banner = cb
        order.save(update_fields=['customer_banner'])

    # برای publish: منبع ترجیحی پیام روی مرجع
    order.banner_from_chat_id = ref
    order.banner_message_id = ref_mid
    order.save(update_fields=['banner_from_chat_id', 'banner_message_id'])

    return {'ok': True, 'ref_chat': ref, 'ref_message_id': ref_mid, 'reused': False}


def process_manager_response(
    order_item_id: int,
    manager_bale_id: str,
    action: str,
    new_start: Optional[str] = None,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """یک مسیر با سبد: رد یک کانال بقیهٔ سفارش را نمی‌بندد و /paid_ به مشتری عادی نمی‌رود."""
    del extra_payload
    action = (action or '').lower().strip()
    parsed = None
    if new_start:
        parsed = parse_datetime(new_start)
        if action == 'edit' and not parsed:
            return {'ok': False, 'error': 'invalid_new_start'}
    from orders.cart import process_manager_item

    return process_manager_item(order_item_id, str(manager_bale_id), action, new_start=parsed)


def process_payment_paid(order_id: int) -> Dict[str, Any]:
    from django.db import transaction

    try:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related('customer', 'customer_banner')
                .get(id=order_id)
            )
            if order.status == 'paid':
                return {'ok': True, 'order_id': order.id, 'order_status': 'paid', 'already': True}
            if order.status != 'waiting_payment':
                return {'ok': False, 'error': 'not_waiting_payment'}
            order.status = 'paid'
            order.save(update_fields=['status'])
    except Order.DoesNotExist:
        return {'ok': False, 'error': 'order_not_found'}

    order = Order.objects.prefetch_related(
        'items__channel', 'items__manager', 'items__tariff', 'customer_banner'
    ).select_related('customer', 'customer_banner').get(id=order_id)

    ref = ensure_banner_on_reference(order)
    if not ref.get('ok'):
        logger.warning(
            'order %s paid but reference banner failed: %s',
            order.id,
            ref.get('error'),
        )
        # پرداخت می‌ماند؛ انتشار ممکن است از چت خصوصی تلاش کند

    for item in order.items.filter(manager_status='approved'):
        item.execution_status = 'paid'
        item.save(update_fields=['execution_status'])
        if item.manager and item.manager.bale_user_id:
            target = item.channel.name if item.channel else '?'
            if item.tariff_id and item.tariff.group_id:
                target = item.tariff.group.name
            mode_code = item.channel.publish_mode if item.channel_id else 'bot'
            if mode_code == 'manual':
                follow = 'در زمان نوبت یادآوری می‌آید تا خودتان منتشر کنید.'
            elif mode_code == 'linkyar':
                follow = 'سر ساعت، لینک‌یار خودکار منتشر می‌کند.'
            else:
                follow = 'سر ساعت، لینک‌ساز خودکار منتشر می‌کند.'
            when = format_slot(timezone.localtime(item.effective_start))
            bale_client.send_message(
                item.manager.bale_user_id,
                f'💳 سفارش پرداخت شد.\n'
                f'آیتم #{item.id} — {target}\n'
                f'زمان انتشار: {when}\n'
                f'{follow}',
            )

    if order.customer.bale_user_id:
        extra = ''
        if ref.get('ok'):
            extra = f'\nبنر روی کانال مرجع ({ref.get("ref_chat")}) ثبت شد.'
        elif ref.get('error'):
            extra = '\n(ثبت روی کانال مرجع فعلاً ممکن نشد؛ پیگیری فنی)'
        bale_client.send_message(
            order.customer.bale_user_id,
            f'سفارش #{order.id} پرداخت شد. در زمان مقرر منتشر می‌شود.{extra}',
        )

    return {
        'ok': True,
        'order_id': order.id,
        'order_status': order.status,
        'reference': {'ok': ref.get('ok'), 'error': ref.get('error')},
    }


def notify_managers_for_order(order: Order) -> None:
    for item in order.items.select_related('channel', 'manager', 'order__customer', 'tariff').all():
        if not item.manager or not item.manager.bale_user_id:
            continue
        manager_id = item.manager.bale_user_id
        if order.banner_message_id and order.banner_from_chat_id:
            try:
                msg_id = int(order.banner_message_id)
                bale_client.forward_message(
                    to_chat_id=manager_id,
                    from_chat_id=order.banner_from_chat_id,
                    message_id=msg_id,
                )
            except (TypeError, ValueError):
                logger.warning('banner_message_id not int, skip forward: %s', item.banner_message_id)

        target = item.channel.name if item.channel else '?'
        if item.tariff and item.tariff.group_id:
            target = f'مجموعه «{item.tariff.group.name}»'

        kb = bale_client.manager_decision_keyboard(item.id)
        bale_client.send_message(
            manager_id,
            f'📢 درخواست تبلیغ جدید\n'
            f'هدف: {target}\n'
            f'زمان: {format_slot(timezone.localtime(item.requested_start))} تا {format_slot(timezone.localtime(item.requested_end))}\n'
            f'مبلغ: {item.price:,} تومان\n'
            f'آیتم: #{item.id} | سفارش: #{order.id}',
            reply_markup=kb,
        )
