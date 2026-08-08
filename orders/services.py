"""Business logic for order lifecycle — shared by API webhooks and poll_bot."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from django.utils.dateparse import parse_datetime

from integrations import bale_client
from orders.models import ManagerResponse, Order, OrderItem
from users.models import User

logger = logging.getLogger(__name__)


def process_manager_response(
    order_item_id: int,
    manager_bale_id: str,
    action: str,
    new_start: Optional[str] = None,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Apply manager approve/reject/edit and advance order state."""
    action = (action or '').lower().strip()
    if action not in ('approve', 'reject', 'edit'):
        return {'ok': False, 'error': 'invalid_action', 'detail': 'action must be approve|reject|edit'}

    try:
        item = OrderItem.objects.select_related('order', 'channel', 'manager', 'order__customer').get(
            id=order_item_id
        )
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'item_not_found'}

    try:
        manager = User.objects.get(bale_user_id=str(manager_bale_id))
    except User.DoesNotExist:
        return {'ok': False, 'error': 'manager_not_found'}

    if item.manager_id and item.manager_id != manager.id:
        return {'ok': False, 'error': 'not_item_manager'}

    item.manager_status = (
        'approved' if action == 'approve' else ('rejected' if action == 'reject' else 'edited')
    )
    if action == 'edit' and new_start:
        parsed = parse_datetime(new_start)
        if parsed:
            item.manager_edited_start = parsed
    item.save()

    payload = {'order_item_id': order_item_id, 'manager_bale_id': manager_bale_id, 'action': action}
    if new_start:
        payload['new_start'] = new_start
    if extra_payload:
        payload.update(extra_payload)
    ManagerResponse.objects.create(order_item=item, manager=manager, action=action, payload=payload)

    order = item.order
    pending = order.items.filter(manager_status='pending').exists()
    result: Dict[str, Any] = {
        'ok': True,
        'order_id': order.id,
        'item_id': item.id,
        'item_status': item.manager_status,
        'order_status': order.status,
        'pending_left': pending,
    }

    if pending:
        return result

    rejected_any = order.items.filter(manager_status='rejected').exists()
    if rejected_any:
        order.status = 'rejected'
        order.save()
        result['order_status'] = order.status
        if order.customer.bale_user_id:
            bale_client.send_message(
                order.customer.bale_user_id,
                f'متاسفیم، یکی از کانال‌ها سفارش شما را رد کرد. سفارش #{order.id} رد شد.',
            )
        return result

    order.status = 'waiting_payment'
    order.save()
    result['order_status'] = order.status

    if not order.customer.bale_user_id:
        return result

    callback = os.environ.get('WEBHOOK_BASE_URL')
    if callback:
        callback = callback.rstrip('/') + '/api/webhooks/payment/'

    payment = bale_client.create_payment_request(
        chat_id=order.customer.bale_user_id,
        amount=order.total_amount,
        callback_url=callback,
        payload=f'order-{order.id}',
        title=f'پرداخت سفارش #{order.id}',
        description=f'هزینه تبلیغ — سفارش #{order.id}',
    )
    result['payment'] = {'ok': payment.get('ok'), 'error': payment.get('error')}

    # Use /paid_123 (no space) so the whole command is tappable in Bale/Telegram clients
    paid_cmd = f'/paid_{order.id}'

    if payment.get('payment_url'):
        bale_client.send_message(
            order.customer.bale_user_id,
            f"همه مدیران تایید کردند. لطفاً پرداخت را تکمیل کنید: {payment.get('payment_url')}",
        )
    elif payment.get('ok'):
        bale_client.send_message(
            order.customer.bale_user_id,
            f'همه مدیران تایید کردند. فاکتور پرداخت برای سفارش #{order.id} ارسال شد.\n'
            f'پس از پرداخت بزن: {paid_cmd}',
        )
    else:
        bale_client.send_message(
            order.customer.bale_user_id,
            f'همه مدیران تایید کردند.\n'
            f'مبلغ سفارش #{order.id}: {order.total_amount} ریال\n'
            f'برای شبیه‌سازی پرداخت در تست بزن:\n{paid_cmd}',
        )

    return result


def process_payment_paid(order_id: int) -> Dict[str, Any]:
    """Mark order paid/completed and attempt schedule/forward side-effects."""
    try:
        order = Order.objects.prefetch_related('items__channel', 'items__manager').get(id=order_id)
    except Order.DoesNotExist:
        return {'ok': False, 'error': 'order_not_found'}

    order.status = 'completed'
    order.save()

    for item in order.items.all():
        send_time = item.manager_edited_start if item.manager_edited_start else item.requested_start
        send_iso = send_time.isoformat() if send_time else ''
        channel_target = item.channel.link or str(item.channel.id)

        if bale_client.bot_is_channel_admin(channel_target):
            if item.banner_message_id:
                resp = bale_client.schedule_message(
                    channel_target,
                    {'forward_message_id': item.banner_message_id},
                    send_iso,
                )
                if resp.get('error') and item.manager and item.manager.bale_user_id:
                    bale_client.schedule_message(
                        item.manager.bale_user_id,
                        {'forward_message_id': item.banner_message_id},
                        send_iso,
                    )
                else:
                    item.banner_forwarded = True
                    item.save()
        else:
            if item.manager and item.manager.bale_user_id and item.banner_message_id:
                bale_client.schedule_message(
                    item.manager.bale_user_id,
                    {'forward_message_id': item.banner_message_id},
                    send_iso,
                )
                item.banner_forwarded = True
                item.save()

    if order.customer.bale_user_id:
        bale_client.send_message(
            order.customer.bale_user_id,
            f'سفارش شما #{order.id} با موفقیت ثبت و پرداخت شد. '
            f'تبلیغات در زمان‌های مشخص منتشر خواهد شد.',
        )

    return {'ok': True, 'order_id': order.id, 'order_status': order.status}


def notify_managers_for_order(order: Order) -> None:
    """Send Bale notifications to each item manager after order creation."""
    for item in order.items.select_related('channel', 'manager', 'order__customer').all():
        if not item.manager or not item.manager.bale_user_id:
            continue
        manager_id = item.manager.bale_user_id
        if item.banner_message_id and order.customer.bale_user_id:
            try:
                msg_id = int(item.banner_message_id)
                bale_client.forward_message(
                    to_chat_id=manager_id,
                    from_chat_id=order.customer.bale_user_id,
                    message_id=msg_id,
                )
            except (TypeError, ValueError):
                logger.warning('banner_message_id not int, skip forward: %s', item.banner_message_id)

        # Underscore form is one tappable bot-command entity in Bale/Telegram UIs
        approve_cmd = f'/approve_{item.id}'
        reject_cmd = f'/reject_{item.id}'

        bale_client.send_message(
            manager_id,
            f'📢 درخواست تبلیغ جدید\n'
            f'کانال: {item.channel.name}\n'
            f'زمان: {item.requested_start} تا {item.requested_end}\n'
            f'مبلغ آیتم: {item.price}\n'
            f'آیتم: #{item.id} | سفارش: #{order.id}\n\n'
            f'برای قبول بزن:\n{approve_cmd}\n'
            f'برای رد بزن:\n{reject_cmd}',
        )
